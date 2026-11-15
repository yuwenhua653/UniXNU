#!/usr/bin/env python3
"""Compile the selected XNU geometry and execute its real table initializers.

The test applies the selected arch/OS/device patches to the tested source files.
It compiles the actual proc_reg/board headers, actual page_table_attr layout,
initializers, indexing/root-size helpers, and the pmap-selection fragments.
Only unrelated kernel services and pmap fields are replaced by host scaffolding.
This checks source geometry and ordering; it does not execute the XNU MMU path.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


SUBJECTS = (
    'pexpert/pexpert/arm64/board_config.h',
    'pexpert/pexpert/arm64/BCM2837.h',
    'osfmk/arm64/proc_reg.h',
    'osfmk/arm/pmap/pmap_pt_geometry.h',
    'osfmk/arm/pmap/pmap.c',
    'osfmk/arm64/arm_vm_init.c',
    'osfmk/arm/arm_init.c',
    'osfmk/arm64/start.s',
    'osfmk/arm64/sleh.c',
)


def body(source, name):
    """Return a named C definition, rejecting declarations and duplicate bodies."""
    hits = list(re.finditer(r'(?m)^' + re.escape(name) + r'\([^;]*?\)\s*\{', source))
    if len(hits) != 1:
        raise AssertionError((name, 'expected one definition', len(hits)))
    start = hits[0].start()
    end = source.index('\n}\n', hits[0].end()) + 3
    return source[start:end]


def declaration(source, prefix):
    start = source.index(prefix)
    end = source.index('\n};', start) + 3
    return source[start:end] + '\n'


def apply_selected(args, work):
    roots = dict(device=args.device.resolve(),
                 arch=args.upstream.resolve() / 'profiles/arch/arm64e',
                 os=args.device.resolve() / 'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
    for name in SUBJECTS:
        dest = work / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if (args.xnu / name).is_file():
            shutil.copyfile(args.xnu / name, dest)
    applied = []
    for scope in ('arch', 'os', 'device'):
        series = roots[scope] / 'patches/xnu/series'
        for line in series.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            prefix, sep, tail = line.partition(':')
            patch = (roots[prefix] / tail if sep else series.parent / line).resolve()
            source = patch.read_text()
            if any('--- a/' + n in source or '+++ b/' + n in source for n in SUBJECTS):
                subprocess.run(['git', 'apply', *['--include=' + n for n in SUBJECTS],
                                str(patch)], cwd=work, check=True)
                applied.append(patch.name)
    assert applied.count('myron-user-pac-va43.patch') == 1, applied
    return applied


HEADER_ASSERTS = r'''
#include <arm64/proc_reg.h>
_Static_assert(ARM_PARAMETERIZED_PMAP == 1, "per-pmap attributes enabled");
_Static_assert(T0SZ_BOOT == 21 && T1SZ_BOOT == 26, "runtime widths");
_Static_assert(ARM_PTE_T0SZ(TCR_EL1_BOOT) == 26 && ARM_PTE_T1SZ(TCR_EL1_BOOT) == 26, "boot widths");
_Static_assert(ARM_PTE_T0SZ(TCR_EL1_FINAL) == 21 && ARM_PTE_T1SZ(TCR_EL1_FINAL) == 26, "final widths");
_Static_assert((TCR_EL1_BOOT ^ TCR_EL1_FINAL) == (26ULL ^ 21ULL), "only T0SZ changes");
_Static_assert(ARM_PTE_T0_REGION_MASK(TCR_EL1_FINAL) == 0x7ffffffffffULL, "user43 mask");
_Static_assert(ARM_PTE_T1_REGION_MASK(TCR_EL1_FINAL) == 0x3fffffffffULL, "kernel38 mask");
_Static_assert((T0SZ_BOOT - 16) / 9 == 0 && (T1SZ_BOOT - 16) / 9 == 1, "root levels");
_Static_assert(((ARM_PTE_T0_REGION_MASK(TCR_EL1_FINAL) >> ARM_4K_TT_L0_SHIFT) + 1) == 16, "user root entries");
_Static_assert(((ARM_PTE_T1_REGION_MASK(TCR_EL1_FINAL) >> ARM_4K_TT_L1_SHIFT) + 1) == 256, "kernel root entries");
'''


def geometry_program(work):
    source = (work / 'osfmk/arm/pmap/pmap.c').read_text()
    geometry = (work / 'osfmk/arm/pmap/pmap_pt_geometry.h').read_text()
    # Copy original declarations instead of reproducing a guessed private ABI.
    result = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
typedef uint64_t vm_offset_t;
typedef uint64_t vm_map_address_t;
typedef uint64_t pmap_paddr_t;
typedef uint64_t pt_entry_t;
typedef uint64_t tt_entry_t;
typedef uint64_t vm_size_t;
typedef struct test_pmap *pmap_t;
''' + HEADER_ASSERTS
    for name in ('page_table_level_info', 'page_table_ops', 'page_table_attr'):
        result += declaration(geometry, 'struct ' + name + ' {')
    result += r'''
typedef struct page_table_attr pt_attr_t;
struct test_pmap { const pt_attr_t *pmap_pt_attr; };
const struct page_table_ops native_pt_ops = {0};
_Static_assert(sizeof(struct page_table_attr) == 120, "native verifier attr size");
_Static_assert(offsetof(struct page_table_attr, pta_root_level) == 64, "native verifier root offset");
_Static_assert(offsetof(struct page_table_attr, pta_tcr_value) == 80, "native verifier tcr offset");
_Static_assert(offsetof(struct page_table_attr, pta_page_size) == 88, "native verifier page offset");
_Static_assert(offsetof(struct page_table_attr, pta_pagezero_size) == 96, "native verifier zero offset");
_Static_assert(offsetof(struct page_table_attr, pta_page_shift) == 104, "native verifier shift offset");
_Static_assert(offsetof(struct page_table_attr, pta_va_valid_mask) == 112, "native verifier mask offset");
'''
    macros = geometry[geometry.index('#if ARM_PARAMETERIZED_PMAP'):geometry.index('/**\n * Inline functions exported')]
    result += macros
    for name in ('pmap_table_level_info_4k', 'pmap_table_level_info_16k'):
        result += declaration(source, 'const struct page_table_level_info ' + name + '[]')
    start = source.index('const struct page_table_attr pmap_pt_attr_4k = {')
    end = source.index('#endif /* !__ARM_16K_PG__ */', start) + len('#endif /* !__ARM_16K_PG__ */')
    result += source[start:end] + '\n'
    for result_type, name in (('uint64_t', 'pt_attr_ln_shift'),
                              ('uint64_t', 'pt_attr_ln_index_mask'),
                              ('unsigned int', 'pt_attr_root_level'),
                              ('uint64_t', 'pt_attr_va_valid_mask'),
                              ('unsigned int', 'ttn_index')):
        result += 'static inline ' + result_type + '\n' + body(geometry, name)
    result += 'static vm_size_t\n' + body(source, 'pmap_root_alloc_size')
    result += 'static uint32_t\n' + body(source, 'pmap_user_va_bits')
    result += 'static uint32_t\n' + body(source, 'pmap_kernel_va_bits')
    # Execute the actual conditional assignment blocks from kernel and user paths.
    kernel = source[source.index('/*\n\t *\tInitialize the kernel pmap.'):]
    start = kernel.index('#if ARM_PARAMETERIZED_PMAP')
    end = kernel.index('#endif /* ARM_PARAMETERIZED_PMAP */', start) + len('#endif /* ARM_PARAMETERIZED_PMAP */')
    result += 'static void select_kernel(pmap_t kernel_pmap) {\n' + kernel[start:end] + '\n}\n'
    user = body(source, 'pmap_create_options_internal')
    start = user.index('#if ARM_PARAMETERIZED_PMAP')
    end = user.index('\n\tp->max = pmap_user_va_size(p);', start)
    result += 'static void select_user(pmap_t p, unsigned flags __unused) {\n' + user[start:end] + '\n}\n'
    # Preserve the existing small-table pool/accounting unit and test allocation/free agreement.
    result += '\n'.join(re.findall(r'^#define PMAP_(?:L1_MAX_ENTRY|ROOT_ALLOC_SIZE) .+$', source, re.M)) + '\n'
    result += '#define PAGE_SIZE 4096\n'
    for func, label in (('pmap_tt1_allocate', 'allocation_size'), ('pmap_tt1_deallocate', 'deallocation_size')):
        code = body(source, func)
        match = re.search(r'\tif \(\(size < PAGE_SIZE\).*?\n\t}', code, re.S)
        assert match, func
        result += 'static vm_size_t ' + label + '(vm_size_t size) {\n' + match.group() + '\nreturn size;\n}\n'
    result += r'''
int main(void) {
 struct test_pmap user = {0}, kernel = {0};
 select_kernel(&kernel);
 assert(kernel.pmap_pt_attr == &pmap_pt_attr_4k_kernel);
 assert(native_pt_attr == &pmap_pt_attr_4k_kernel);
 assert(pmap_user_va_bits(&user) == 43 && pmap_kernel_va_bits() == 38);
 assert(pmap_pt_attr_4k_kernel.pta_root_level == 1);
 assert(pmap_pt_attr_4k_kernel.pta_va_valid_mask == UINT64_C(0x3fffffffff));
 assert(pmap_root_alloc_size(&kernel) == 2048);
 assert(PMAP_ROOT_ALLOC_SIZE == 2048);
 assert(allocation_size(pmap_root_alloc_size(&kernel)) == 2048);
 assert(deallocation_size(pmap_root_alloc_size(&kernel)) == 2048);
 for (unsigned flags = 0; flags < 256; flags++) {
  select_user(&user, flags);
  assert(user.pmap_pt_attr == &pmap_pt_attr_4k);
  assert(pmap_root_alloc_size(&user) == 128);
  assert(allocation_size(pmap_root_alloc_size(&user)) == 4096);
  assert(deallocation_size(pmap_root_alloc_size(&user)) == 4096);
 }
 assert(pmap_pt_attr_4k.pta_root_level == 0);
 assert(pmap_pt_attr_4k.pta_va_valid_mask == UINT64_C(0x7ffffffffff));
 assert(pmap_pt_attr_4k.pta_tcr_value == TCR_EL1_FINAL);
 assert(pmap_pt_attr_4k_kernel.pta_tcr_value == TCR_EL1_FINAL);
 assert(pmap_pt_attr_4k.pta_page_size == 4096 && pmap_pt_attr_4k_kernel.pta_page_size == 4096);
 assert(pmap_pt_attr_4k.pta_commpage_level == 1 && pmap_pt_attr_4k_kernel.pta_commpage_level == 1);
 assert(ttn_index(user.pmap_pt_attr, UINT64_C(0x1e9d71f70), 0) == 0);
 assert(ttn_index(user.pmap_pt_attr, UINT64_C(0x741e9d71f70), 0) == 14);
 assert(ttn_index(user.pmap_pt_attr, UINT64_C(0x7ffffffffff), 0) == 15);
 assert(ttn_index(kernel.pmap_pt_attr, UINT64_C(0xffffffc000000000), 1) == 0);
 assert(ttn_index(kernel.pmap_pt_attr, UINT64_C(0xffffffffffffffff), 1) == 255);
 puts("PASS actual table layout, user/kernel selectors, indexing, and allocation/free geometry");
 return 0;
}
'''
    return result


def check_transition_sources(work):
    # Preprocessor guards are compiled separately above; check the actual three paths.
    for path, names, invalid in (
        ('osfmk/arm64/arm_vm_init.c', ('arm_vm_init',), 'set_mmu_ttb(invalid_ttep & TTBR_BADDR_MASK);'),
        ('osfmk/arm/arm_init.c', ('arm_init_cpu', 'arm_init_idle_cpu'), 'pmap_clear_user_ttb();'),
    ):
        source = (work / path).read_text()
        for name in names:
            code = body(source, name)
            assert code.count('set_tcr(TCR_EL1_FINAL);') == 1, name
            tail = code[code.index(invalid):]
            assert re.search(re.escape(invalid) + r'.*?flush_mmu_tlb\(\);.*?set_tcr\(TCR_EL1_FINAL\);.*?flush_mmu_tlb\(\);', tail, re.S), name
    startup = (work / 'osfmk/arm64/start.s').read_text()
    assert 'TCR_EL1_BOOT' in startup and 'TCR_EL1_FINAL' not in startup
    assert 'T0SZ_BOOT' not in startup, 'startup must retain the boot L1 geometry'
    sleh = (work / 'osfmk/arm64/sleh.c').read_text()
    assert 'fault_addr_bitmask(64 - T0SZ_BOOT, 54)' in sleh
    pmap = (work / 'osfmk/arm/pmap/pmap.c').read_text()
    assert 'return 64 - T0SZ_BOOT;' in body(pmap, 'pmap_user_va_bits')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('device', 'upstream', 'xnu'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--cc', default='clang')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='myron-va43-') as temp:
        work = Path(temp)
        applied = apply_selected(args, work)
        common = [args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror',
                  '-DKERNEL_PRIVATE=1', '-D__arm64__=1', '-D__arm64e__=1',
                  '-DARM64_BOARD_CONFIG_BCM2837=1', '-DXNU_NATIVE_PAN=1',
                  '-I' + str(work / 'osfmk'), '-I' + str(work / 'pexpert')]
        probe = work / 'geometry.c'
        program = geometry_program(work)
        probe.write_text(program)
        binary = work / 'geometry'
        subprocess.run([*common, str(probe), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=10)
        # Darwin sys/cdefs.h already defines this macro, with a different token
        # spelling. Exercise that case on Linux too; keep -Werror enabled.
        darwin_macro = work / 'darwin-macro.h'
        darwin_macro.write_text('#ifndef __unused\n'
                               '#define __unused __attribute__((__unused__))\n'
                               '#endif\n')
        darwin_binary = work / 'geometry-existing-unused'
        subprocess.run([*common, '-include', str(darwin_macro), str(probe),
                        '-o', str(darwin_binary)], check=True)
        subprocess.run([str(darwin_binary)], check=True, timeout=10)
        # Confirm the same actual private layout for the arm64e ABI as well as
        # the executable host model. Only compiler-owned C headers are needed.
        arm64e = work / 'arm64e-layout.c'
        layout = program[:program.index('#if ARM_PARAMETERIZED_PMAP')]
        layout = layout.replace('#include <assert.h>\n', '').replace('#include <stdio.h>\n', '')
        arm64e.write_text(layout)
        # Apple Clang otherwise inherits the runner's MacOSX SDK even for an
        # explicit iPhone triple. This layout probe needs only compiler-owned
        # stdint/stddef/stdbool headers, not either platform's SDK.
        resource = Path(subprocess.check_output(
            [args.cc, '-print-resource-dir'], text=True).strip()).resolve()
        if not (resource / 'include/stdint.h').is_file():
            raise RuntimeError('Missing Clang compiler-owned stdint.h')
        sysroot = work / 'freestanding-sysroot'
        sysroot.mkdir()
        target_env = os.environ.copy()
        for key in ('SDKROOT', 'MACOSX_DEPLOYMENT_TARGET', 'IPHONEOS_DEPLOYMENT_TARGET'):
            target_env.pop(key, None)
        subprocess.run([*common, '--target=arm64e-apple-ios18.0', '-ffreestanding',
                        '-isysroot', str(sysroot), '-nostdinc',
                        '-isystem', str(resource / 'include'),
                        '-fsyntax-only', str(arm64e)], check=True, env=target_env)
        # Override after the real board header so guards cannot be hidden by redefines.
        negatives = {
            '16k': '#define __ARM_16K_PG__ 1',
            'mixed_pages': '#define __ARM_MIXED_PAGE_SIZE__ 1',
            'sptm': '#define CONFIG_SPTM 1',
            'kernel_protect': '#define __ARM_KERNEL_PROTECT__ 1',
            'pa42': '#define __ARM_42BIT_PA_SPACE__ 1',
            'no_native_pac': '#undef HAS_NATIVE_PAC\n#define HAS_NATIVE_PAC 0',
            'no_apple_pac_abi': '#undef HAS_APPLE_PAC\n#define HAS_APPLE_PAC 0',
            'no_parameterized_pmap': '#undef ARM_PARAMETERIZED_PMAP\n#define ARM_PARAMETERIZED_PMAP 0',
            'no_independent_tnsz': '#undef HAS_ARM_INDEPENDENT_TNSZ\n#define HAS_ARM_INDEPENDENT_TNSZ 0',
            'no_kernel_subpage': '#undef __ARM64_PMAP_KERN_SUBPAGE_L1__\n#define __ARM64_PMAP_KERN_SUBPAGE_L1__ 0',
            'wrong_va_width': '#undef XNU_NATIVE_USER_VA_BITS\n#define XNU_NATIVE_USER_VA_BITS 42',
            'not_arm64e': '#undef __arm64e__',
        }
        for name, override in negatives.items():
            test = work / (name + '.c')
            test.write_text('#include <pexpert/arm64/board_config.h>\n' + override + '\n#include <arm64/proc_reg.h>\n')
            run = subprocess.run([*common, '-fsyntax-only', str(test)], text=True, capture_output=True)
            assert run.returncode and 'Native user VA43 requires' in run.stderr, (name, run.stderr)
        check_transition_sources(work)
        print('PASS existing Darwin-style __unused macro with -Werror retained')
        print('PASS arm64e private table layout matches compiled native artifact offsets')
        print('PASS actual selected headers: boot 26/26, runtime 21/26; 12 invalid configurations rejected')
        print('PASS 3 source transitions after invalid TTBR0, bootstrap unchanged, runtime PAC-width consumers')
        print('PASS selected source patches:', ', '.join(applied))


if __name__ == '__main__':
    main()
