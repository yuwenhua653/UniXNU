#!/usr/bin/env python3
"""Execute patched native PAC selectors and v5 slider; inspect EL0 ABI guards.

The host replaces the hardware signing primitive with a recording stub. This
proves whether real source reaches it and with which inputs, not hardware PAC.
Locore checks inspect the actual patched assembly; they do not execute ARM code.
"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def function(source, result, name):
    start = source.index(result + '\n' + name + '(')
    end = source.index('\n}\n', start) + 3
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('device', 'upstream', 'xnu'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--cc', default='cc')
    args = parser.parse_args()
    roots = dict(device=args.device.resolve(),
                 arch=args.upstream.resolve() / 'profiles/arch/arm64e',
                 os=args.device.resolve() / 'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
    subjects = ('osfmk/arm/machine_routines_apple.c', 'osfmk/arm64/locore.s',
                'osfmk/vm/vm_shared_region.c')
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        for name in subjects:
            dest = work / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.xnu / name, dest)
        for scope in ('arch', 'os', 'device'):
            series = roots[scope] / 'patches/xnu/series'
            for line in series.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                prefix, sep, tail = line.partition(':')
                patch = (roots[prefix] / tail if sep else series.parent / line).resolve()
                source = patch.read_text()
                if any('--- a/' + n in source or '+++ b/' + n in source for n in subjects):
                    subprocess.run(['git', 'apply', *['--include=' + n for n in subjects],
                                    str(patch)], cwd=work, check=True)

        source = (work / subjects[0]).read_text()
        selectors = '\n'.join(function(source, 'uint64_t', name) for name in
                              ('ml_default_jop_pid', 'ml_non_arm64e_user_jop_pid'))
        # The counter also proves the paravirtualized branch still retrieves keys.
        prefix = '''#include <stdint.h>
#include <assert.h>
#if HAS_PARAVIRTUALIZED_PAC
static unsigned retrieved;
static uint64_t vmapple_default_jop_pid = 17;
static void vmapple_pac_get_default_keys(void) { ++retrieved; }
static uint64_t generate_jop_key(void) { return 23; }
#endif
'''
        for native, para, expected, ordinary in ((1, 0, 1, 0), (0, 1, 17, 23),
                                                 (0, 0, 0, 0), (1, 1, 17, 23)):
            test = prefix + selectors + f'''
int main(void) {{
 assert(ml_default_jop_pid() == {expected});
 assert(ml_non_arm64e_user_jop_pid() == {ordinary});
#if HAS_PARAVIRTUALIZED_PAC
 assert(retrieved == 1);
#endif
 return 0;
}}
'''
            path = work / f'selectors-{native}-{para}.c'
            path.write_text(test)
            binary = path.with_suffix('')
            subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror',
                            f'-DHAS_NATIVE_PAC={native}', f'-DHAS_PARAVIRTUALIZED_PAC={para}',
                            str(path), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=10)

        source = (work / subjects[2]).read_text()
        slider = function(source, 'kern_return_t', 'vm_shared_region_slide_part_v5')
        # Only compiler-feature spelling is adapted for the host C compiler.
        slider = slider.replace('__has_feature(ptrauth_calls)', 'TEST_PTRAUTH_CALLS')
        slider = slider.replace('__builtin_ptrauth_blend_discriminator', 'test_blend')
        prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define TEST_PTRAUTH_CALLS 1
#define CONFIG_SPTM 0
#define PAGE_SIZE 4096u
#define VM_SR_PART_NONE 0xffffu
#define KERN_SUCCESS 0
#define KERN_FAILURE 5
#define HAS_NATIVE_PAC 1
#define HAS_PARAVIRTUALIZED_PAC 0
typedef int kern_return_t;
typedef uintptr_t vm_offset_t;
typedef uint64_t mach_vm_offset_t;
typedef int ptrauth_key;
enum { ptrauth_key_asia=0, ptrauth_key_asda=2 };
struct slide_v5 { uint64_t value_add; uint32_t page_size; };
typedef struct slide_v5 *vm_shared_region_slide_info_entry_v5_t;
struct slide_entry { struct slide_v5 v5; };
struct slide_info { uint32_t si_slide; struct slide_entry *si_slide_info_entry; bool si_ptrauth; };
typedef struct slide_info *vm_shared_region_slide_info_t;
static unsigned signed_count, disabled;
static uintptr_t signed_value, signed_discriminator, blend_address;
static uint64_t signed_selector;
static ptrauth_key signed_key;
static int arm_user_jop_disabled(void) { return disabled; }
static uint64_t test_blend(void *address, uint64_t diversity) {
 blend_address=(uintptr_t)address;
 return ((uintptr_t)address & UINT64_C(0x0000ffffffffffff)) | (diversity << 48);
}
static void *pmap_sign_user_ptr(void *value, ptrauth_key key, uint64_t discriminator, uint64_t selector) {
 ++signed_count; signed_value=(uintptr_t)value; signed_key=key;
 signed_discriminator=discriminator; signed_selector=selector;
 return (void *)((uintptr_t)value ^ UINT64_C(0x00aa000000000000));
}
'''
        cases = r'''
int main(void) {
 struct slide_entry entry = { { UINT64_C(0x180000000), 16384 } };
 struct slide_info si = {0x1000, &entry, true};
 uint64_t page[PAGE_SIZE/8] = {0}; uint32_t next=0;
 uint64_t raw = (UINT64_C(1)<<63) | (UINT64_C(1)<<51) |
                (UINT64_C(1)<<50) | (UINT64_C(0x1234)<<34) | 0x88;
 uint64_t pointer=UINT64_C(0x180001088), user=UINT64_C(0x190004000);
 page[2]=raw;
 assert(vm_shared_region_slide_part_v5(&si,(uintptr_t)page,user,1,4112,true,&next,0)==KERN_SUCCESS);
 assert(!signed_count && page[2]==pointer && next==VM_SR_PART_NONE);
 page[2]=raw;
 assert(vm_shared_region_slide_part_v5(&si,(uintptr_t)page,user,1,4112,true,&next,ml_default_jop_pid())==KERN_SUCCESS);
 assert(signed_count==1 && signed_value==pointer && signed_selector==1 && signed_key==ptrauth_key_asda);
 assert(blend_address==user+16 && signed_discriminator==((user+16)|(UINT64_C(0x1234)<<48)));
 assert(page[2]==(pointer^UINT64_C(0x00aa000000000000)));
 disabled=1; page[2]=raw;
 assert(vm_shared_region_slide_part_v5(&si,(uintptr_t)page,user,1,4112,true,&next,1)==KERN_SUCCESS);
 assert(signed_count==1 && page[2]==pointer);
 disabled=0; si.si_ptrauth=false; page[2]=raw;
 assert(vm_shared_region_slide_part_v5(&si,(uintptr_t)page,user,1,4112,true,&next,1)==KERN_SUCCESS);
 assert(signed_count==1 && page[2]==pointer);
 si.si_ptrauth=true; page[2]=raw;
 assert(vm_shared_region_slide_part_v5(&si,(uintptr_t)page,user,1,4112,false,&next,1)==KERN_SUCCESS);
 assert(signed_count==1 && page[2]==raw);
 page[2]=raw;
 assert(vm_shared_region_slide_part_v5(&si,(uintptr_t)page,user,1,4112,true,&next,ml_non_arm64e_user_jop_pid())==KERN_SUCCESS);
 assert(signed_count==1 && page[2]==pointer);
 assert(vm_shared_region_slide_part_v5(&si,(uintptr_t)page,user,1,4100,true,&next,1)==KERN_FAILURE);
 return 0;
}
'''
        path = work / 'slider.c'
        path.write_text(prefix + selectors + '\n' + slider + cases)
        subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', str(path),
                        '-o', str(work / 'slider')], check=True)
        subprocess.run([str(work / 'slider')], check=True, timeout=10)

        locore = (work / subjects[1]).read_text()
        entry = locore.split('.macro EL0_64_VECTOR guest_label', 1)[1].split('#if __ARM_KERNEL_PROTECT__', 1)[0]
        exit_block = locore.split('strb\twzr, [x1, CPU_SYNC_ON_CSWITCH]', 1)[1].split('Lskip_user_jop_keys_off:', 1)[0]
        def ordered(block, tokens):
            pos = 0
            for token in tokens:
                pos = block.index(token, pos) + len(token)
        ordered(entry, ['#if HAS_NATIVE_PAC', 'mrs\t\tx0, SCTLR_EL1',
                        'SCTLR_PACIA_ENABLED_SHIFT', 'SCTLR_PAC_KEYS_ENABLED',
                        'orr\t\tx0, x0, x1', 'msr\t\tSCTLR_EL1, x0', 'isb\t\tsy'])
        ordered(exit_block, ['#if HAS_NATIVE_PAC', 'mrs\t\tx2, SPSR_EL1', 'PSR64_MODE_EL_MASK',
                             'b.ne\tLskip_user_jop_keys_off', 'TPIDR_EL1', 'TH_ARM_MACHINE_FLAGS',
                             'ARM_MACHINE_THREAD_DISABLE_USER_JOP_SHIFT, Lskip_user_jop_keys_off',
                             'mrs\t\tx2, SCTLR_EL1', 'SCTLR_PAC_KEYS_ENABLED', 'bic\t\tx2, x2, x3',
                             'msr\t\tSCTLR_EL1, x2', '#if ERET_NEEDS_ISB', 'BIT_ISB_PENDING'])
        regs = (args.xnu / 'osfmk/arm64/proc_reg.h').read_text()
        mask = re.search(r'^#define SCTLR_PAC_KEYS_ENABLED\s+(.+)$', regs, re.M).group(1)
        assert all('SCTLR_PAC' + key + '_ENABLED' in mask for key in ('IA', 'IB', 'DA', 'DB'))
        # Ensure the exact upstream additions are applied; whitespace is significant here.
        patch = (args.device / 'patches/xnu/myron-native-pac-user-abi.patch').read_text()
        added_groups, current = [], []
        for line in patch.splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                current.append(line[1:])
            elif current:
                added_groups.append('\n'.join(current)); current = []
        if current: added_groups.append('\n'.join(current))
        assert len(added_groups) == 3
        assert added_groups[0] in (work / subjects[0]).read_text()
        assert all(group in locore for group in added_groups[1:])
    print('PASS exact arch/OS/device patch stack; four selector configurations; actual v5 slider key0 unsigned/key1 signing call and ABI guards; exact locore additions and EL0/arm64 guards (static, not native PAC execution)')


if __name__ == '__main__':
    main()
