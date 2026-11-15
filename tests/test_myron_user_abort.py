#!/usr/bin/env python3
"""Execute exact unresolved-user-abort handler and shared first-context renderer."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
for name in ('device', 'upstream', 'xnu'):
    p.add_argument('--' + name, type=Path, required=True)
p.add_argument('--cc', default='cc')
a = p.parse_args()
roots = dict(device=a.device.resolve(), arch=a.upstream.resolve()/'profiles/arch/arm64e',
             os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subjects = ('osfmk/arm64/sleh.c', 'osfmk/kern/boot_progress.h', 'bsd/kern/kern_exit.c')


def handler(text):
    return 'static void\nhandle_user_abort' + text.split('static void\nhandle_user_abort', 1)[1].split('\n}\n', 1)[0] + '\n}\n'


with tempfile.TemporaryDirectory() as tmp:
    w = Path(tmp)
    dest = w/subjects[0]
    for name in subjects:
        if (a.xnu/name).exists():
            (w/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a.xnu/name, w/name)
    for scope in ('arch', 'os', 'device'):
        series = roots[scope]/'patches/xnu/series'
        for line in series.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            prefix, sep, tail = line.partition(':')
            patch = (roots[prefix]/tail if sep else series.parent/line).resolve()
            text = patch.read_text()
            if any('--- a/'+n in text or '+++ b/'+n in text for n in subjects):
                subprocess.run(['git', 'apply', *[f'--include={n}' for n in subjects], str(patch)], cwd=w, check=True)
    patched = dest.read_text()
    original_source = (a.xnu/subjects[0]).read_text()
    includes = lambda s: set(re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', s, re.M))
    assert includes(patched) - includes(original_source) == {'kern/boot_progress.h'}
    assert not includes(original_source) - includes(patched)
    code = handler(patched)
    original = handler(original_source)
    start = code.index('\tboot_progress_user_abort(state, esr, fault_addr);\n')
    end = code.index('#endif\n', start) + len('#endif\n')
    hook = code[start:end]
    assert code[:start] + code[end:] == original, 'Original user-abort decisions changed'
    assert 'copyin' not in hook.lower() and 'COPYIN' not in hook
    assert 'proc_selfpid() == 1' in hook and 'PSR64_IS_USER64' in hook and 'is_saved_state64' in hook
    assert code.index('result == KERN_SUCCESS || result == KERN_ABORTED') < start
    assert code.index('codes[1] = fault_addr;') < start < code.index('const self_restrict_mode_t')
    assert 'uint32_t task_shared_region_slide;' in (a.xnu/'osfmk/kern/task.h').read_text()
    exit_source = (w/subjects[2]).read_text()
    prepare_exit = exit_source.split('proc_prepareexit(proc_t p, int rv, boolean_t perf_notify)\n{', 1)[1]
    fallback = 'boot_progress_exit_mach(1, (unsigned)ut->uu_exception, (uint64_t)ut->uu_code, (uint64_t)ut->uu_subcode);'
    assert exit_source.count(fallback) == 1
    assert prepare_exit.index('ut = get_bsdthread_info(self);') < prepare_exit.index(fallback) < prepare_exit.index('proc_handle_critical_exit(p, rv);')
    assert 'if (proc_getpid(p) == 1 && ut != NULL && get_threadtask(self) == task)' in prepare_exit
    fallback_start = prepare_exit.index('#if (defined(XNU_BOOT_PROGRESS) && XNU_BOOT_PROGRESS) || defined(MYRON_EARLY_PROGRESS)')
    fallback_end = prepare_exit.index('#endif\n', fallback_start) + len('#endif\n')
    fallback_code = 'static void capture_exit_hook(struct test_proc *p,thread_t self,struct exit_uthread *ut,task_t task) {\n' + prepare_exit[fallback_start:fallback_end] + '}\n'
    tail = '\tif (p->p_crash_behavior != 0 || p == initproc) {'
    assert prepare_exit.split(tail, 1)[1] == (a.xnu/subjects[2]).read_text().split('proc_prepareexit(proc_t p, int rv, boolean_t perf_notify)\n{', 1)[1].split(tail, 1)[1]

    (w/'kern').mkdir()
    (w/'kern/boot_progress.h').write_text((w/subjects[1]).read_text())
    (w/'pexpert').mkdir()
    (w/'pexpert/pexpert.h').write_text('#define kPEReleaseScreen 3\nint PE_parse_boot_argn(const char *,void *,int);\nint PE_initialize_console(void *,int);\n')
    src = (a.device/'package/MyronBootProgress.c').read_text()
    for old, new in [('__asm__ volatile("mrs %0, cntvct_el0":"=r"(t));', 't=test_clock;'),
                     ('__asm__ volatile("mrs %0, cntfrq_el0":"=r"(frequency));', 'frequency=1000;'),
                     ('__asm__ volatile("mrs %0, cntvct_el0":"=r"(epoch));', 'epoch=test_clock;')]:
        assert src.count(old) == 1
        src = src.replace(old, new)
    (w/'recorder.c').write_text('static unsigned long long test_clock;\n' + src)
    # A host compiler is not arm64e. Select both sides of this one original
    # classification conditional explicitly; every executable handler line is
    # otherwise copied verbatim from the full selected patch stack.
    assert code.count('#if __has_feature(ptrauth_calls)') == 1
    code = code.replace('#if __has_feature(ptrauth_calls)', '#if TEST_PTRAUTH')
    stubs = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include "recorder.c"
typedef int exception_type_t, kern_return_t, fault_status_t, vm_prot_t, self_restrict_mode_t;
typedef uint64_t mach_exception_data_type_t, vm_offset_t;
typedef unsigned mach_msg_type_number_t;
typedef void *expected_fault_handler_t;
typedef struct { int is64; uint64_t pc,lr,sp,fp,cpsr,far,esr,x[29]; } arm_saved_state_t;
typedef struct pmap { int unused; } *pmap_t;
typedef struct vm_map { pmap_t pmap; } *vm_map_t;
typedef struct task { uint32_t task_shared_region_slide; int thread_count; } *task_t;
typedef struct thread {
 vm_map_t map;
 task_t task;
 int iotier_override, syscalls_unix;
 struct { int trr_fault_state; } t_rr_state;
 struct { uint64_t recover_esr, recover_far; arm_saved_state_t *upcb; } machine;
} *thread_t;
static struct pmap test_pmap;
static struct vm_map test_map={&test_pmap};
static struct task test_task={.task_shared_region_slide=0x12340000};
static struct thread test_thread={.map=&test_map,.task=&test_task};
struct test_proc { int pid; };
struct exit_uthread { int uu_exception; int64_t uu_code,uu_subcode; };
#define proc_getpid(p) ((p)->pid)
static vm_map_t kernel_map;
static int pid=1, vm_result, fast_result, vm_calls, fast_calls, alignment_result, alignment_vm_result, alignment_recover, pac_match;
static uint64_t vm_address, delivered_codes[2];
static unsigned delivered_exception,delivered_num;
static jmp_buf escape;
#define EXC_BAD_ACCESS 1
#define EXC_PTRAUTH_BIT 0x200
#define EXC_ARM_DA_ALIGN 0x101
#define KERN_SUCCESS 0
#define KERN_INVALID_ADDRESS 1
#define KERN_PROTECTION_FAILURE 2
#define KERN_FAILURE 5
#define KERN_ABORTED 14
#define KERN_INVALID_GUARD_OBJECT_SLOT 58
#define VM_PROT_READ 1
#define VM_PROT_WRITE 2
#define VM_PROT_EXECUTE 4
#define FSC_TRANSLATION 4
#define FSC_PERMISSION 13
#define FSC_ACCESS_FLAG_FAULT_L3 11
#define FSC_ALIGNMENT 33
#define FSC_PARITY 16
#define ESR_EC_SHIFT 26
#define ESR_EC_MASK (63ULL<<26)
// Hardware-width fixture: this host test does not validate the pinned XNU
// enum integer-promotion expression used during alignment recovery.
#define ESR_EC_DABORT_EL0 0x24ULL
#define ESR_EC(v) (((v)>>26)&63)
#define THROTTLE_LEVEL_NONE 0
#define TRR_FAULT_NONE 0
#define VM_KERN_MEMORY_NONE 0
#define THREAD_ABORTSAFE 0
#define TRUE 1
#define FALSE 0
#define PX_KTRIAGE 0
#define OS_REASON_MTE_FAIL 37
#define OS_REASON_SELF_RESTRICT 42
#define SELF_RESTRICT_NONE 0
#define SELF_RESTRICT_ANY 255
#if MACH_ASSERT
static self_restrict_mode_t panic_on_jit_guard;
static void diagnostic_printf(const char *format,...){(void)format;}
#define printf diagnostic_printf
#endif
#define __improbable(v) (v)
#define assertf(c,...) assert(c)
#define SPSR_INTERRUPTS_ENABLED(v) (!((v)&0x80))
#define PSR64_IS_USER64(v) (((v)&0x1f)==0)
#define is_saved_state64(s) ((s)->is64)
#define get_saved_state_pc(s) ((s)->pc)
#define get_saved_state_lr(s) ((s)->lr)
#define get_saved_state_sp(s) ((s)->sp)
#define get_saved_state_fp(s) ((s)->fp)
#define get_saved_state_cpsr(s) ((s)->cpsr)
#define get_saved_state_far(s) ((s)->far)
#define get_saved_state_esr(s) ((s)->esr)
#define get_saved_state_reg(s,i) ((s)->x[(i)])
#define set_saved_state_esr(s,v) ((s)->esr=(uint64_t)(v))
#define set_saved_state_far(s,v) ((s)->far=(v))
#define current_thread() (&test_thread)
#define current_task() (&test_task)
#define current_proc() ((void *)1)
#define get_threadtask(t) ((t)->task)
#define VM_USER_STRIP_TBI(v) ((v)&0x00ffffffffffffffULL)
int proc_selfpid(void){return pid;}
static int is_servicible_fault(fault_status_t f,uint64_t e,vm_offset_t a,pmap_t p){(void)f;(void)e;(void)a;(void)p;return 1;}
static void thread_reset_pcs_done_faulting(thread_t t){t->t_rr_state.trr_fault_state=0;}
static int is_vm_fault(fault_status_t f){return f==FSC_TRANSLATION||f==FSC_PERMISSION||f==FSC_ACCESS_FLAG_FAULT_L3;}
static int is_translation_fault(fault_status_t f){return f==FSC_TRANSLATION;}
static int is_alignment_fault(fault_status_t f){return f==FSC_ALIGNMENT;}
static int is_parity_error(fault_status_t f){return f==FSC_PARITY;}
static int arm_fast_fault(pmap_t p,vm_offset_t a,vm_prot_t t,bool flag,bool user){(void)p;(void)a;(void)t;(void)flag;(void)user;++fast_calls;return fast_result;}
static int vm_fault(vm_map_t m,vm_offset_t a,vm_prot_t t,int w,int tag,int intr,pmap_t p,uint64_t pa){(void)m;(void)t;(void)w;(void)tag;(void)intr;(void)p;(void)pa;vm_address=a;++vm_calls;return vm_result;}
static int handle_alignment_fault_from_user(arm_saved_state_t *s,kern_return_t *k){(void)s;*k=alignment_vm_result;if(alignment_recover){test_thread.machine.recover_esr=0x94000007;test_thread.machine.recover_far=0xbeef1234;}return alignment_result;}
static self_restrict_mode_t user_fault_in_self_restrict_mode(thread_t t){(void)t;return SELF_RESTRICT_NONE;}
static int task_is_jit_exception_fatal(task_t t){(void)t;return 0;}
#if TEST_PTRAUTH
static bool user_fault_matches_pac_error_code(vm_offset_t a,uint64_t pc,bool data){(void)a;(void)pc;(void)data;return pac_match;}
#endif
static void exit_with_fatal_exception_and_notify(void *p,int ns,exception_type_t e,uint64_t c,uint64_t a,int f){(void)p;(void)ns;(void)e;(void)c;(void)a;(void)f;}
__attribute__((noreturn)) static void thread_exception_return(void){longjmp(escape,3);}
__attribute__((noreturn)) static void panic(const char *s,...){(void)s;longjmp(escape,2);}
__attribute__((noreturn)) static void panic_with_thread_kernel_state(const char *s,arm_saved_state_t *p){(void)s;(void)p;longjmp(escape,2);}
__attribute__((noreturn)) static void exception_triage(exception_type_t e,mach_exception_data_type_t *c,mach_msg_type_number_t n){delivered_exception=e;delivered_num=n;memcpy(delivered_codes,c,sizeof delivered_codes);longjmp(escape,1);}
int PE_parse_boot_argn(const char *k,void *v,int n){(void)k;(void)n;*(unsigned *)v=2;return 1;}
int PE_initialize_console(void *p,int n){(void)p;(void)n;return 0;}
'''
    tests = r'''
static void reset(void){
 user_pac_claimed=user_pac_ready=critical_exit_claimed=critical_exit_ready=critical_exit_bytes=panic_claimed=scanout_state=0;
 exit_mach_claimed=exit_mach_ready=exit_mach_exception=0;exit_mach_code=exit_mach_subcode=0;
 myron_user_abort_count=0;pid=1;vm_calls=fast_calls=0;vm_result=KERN_INVALID_ADDRESS;fast_result=KERN_FAILURE;
 alignment_result=-1;alignment_vm_result=KERN_PROTECTION_FAILURE;alignment_recover=0;pac_match=0;
 test_task.task_shared_region_slide=0x12340000;memset(&user_pac_snapshot,0,sizeof user_pac_snapshot);
 memset(display.previous,0,sizeof display.previous);
}
static void invoke(arm_saved_state_t *s,uint64_t esr,uint64_t far,int fsc,int access,int result){
 test_thread.machine.upcb=s;
 int r=setjmp(escape);
 if(!r)handle_user_abort(s,esr,far,fsc,access,NULL);
 assert(r==result);
}
int main(void){
 boot_progress_init();
 size_t bytes=736*4*1500;unsigned char *mem=malloc(bytes+64);assert(mem);memset(mem,0xa5,bytes+64);
 display.frame=(uintptr_t)(mem+32);display.width=720;display.height=1500;display.stride=736*4;display.scale=2;display.bound=1;
 arm_saved_state_t s={.is64=1,.pc=0x180001234,.lr=0x180005678,.sp=0x16fff0000,.fp=0x16fff0100,.cpsr=0,.far=0xab000000dead0000ULL,.esr=0x90000007};
 for(unsigned i=0;i<29;i++)s.x[i]=0x100000000ULL+i;
 // Ordinary successful/aborted faults must not consume the first record.
 reset();vm_result=KERN_SUCCESS;invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,0);assert(vm_calls==1&&!user_pac_ready&&!myron_user_abort_count);
 reset();vm_result=KERN_ABORTED;invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,0);assert(!user_pac_ready&&!myron_user_abort_count);
 reset();fast_result=KERN_SUCCESS;invoke(&s,s.esr,s.far,FSC_PERMISSION,1,0);assert(fast_calls==1&&!vm_calls&&!user_pac_ready);
 reset();vm_result=KERN_FAILURE;invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,2);assert(!user_pac_ready);
 reset();vm_result=KERN_INVALID_GUARD_OBJECT_SLOT;invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,3);assert(!user_pac_ready);
 // Actual failed VM path: TBI-stripped lookup, original effective exception address.
 reset();invoke(&s,s.esr,s.far,FSC_TRANSLATION,3,1);
 assert(vm_address==0xdead0000 && delivered_exception==EXC_BAD_ACCESS && delivered_num==2);
 assert(delivered_codes[0]==KERN_INVALID_ADDRESS&&delivered_codes[1]==s.far);
 assert(user_pac_ready&&user_pac_snapshot.kind==1&&myron_user_abort_count==1);
 assert(user_pac_snapshot.pc==s.pc&&user_pac_snapshot.lr==s.lr&&user_pac_snapshot.sp==s.sp&&user_pac_snapshot.fp==s.fp);
 assert(user_pac_snapshot.esr==s.esr&&user_pac_snapshot.saved_esr==s.esr&&user_pac_snapshot.far==s.far);
 assert(user_pac_snapshot.exception_code==KERN_INVALID_ADDRESS&&user_pac_snapshot.exception_address==s.far);
 assert(user_pac_snapshot.fault_type==3&&user_pac_snapshot.fault_status==FSC_TRANSLATION&&user_pac_snapshot.cache_slide==0x12340000);
 assert(!memcmp(user_pac_snapshot.x,s.x,sizeof s.x));
 assert(strstr(display.previous[20],"data")&&strstr(display.previous[24],"CODE_ADDR="));
 assert(strstr(display.previous[26],"0x12340000")&&strstr(display.previous[26],"ACCESS=0x03"));
 for(unsigned r=20;r<44;r++)assert(strlen(display.previous[r])<=60);
 char saved[24][BP_COLS];memcpy(saved,&display.previous[20],sizeof saved);
 struct boot_progress_user_pac_state first=user_pac_snapshot;
 s.pc++;invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,1);assert(!memcmp(&first,&user_pac_snapshot,sizeof first));s.pc--;
 boot_progress_stage("later");boot_progress_putc('\n');test_clock+=1000;boot_progress_irq(8,7,6);myron_mount_event(1,"later","apfs",0,0);
 assert(!memcmp(saved,&display.previous[20],sizeof saved));
 boot_progress_exit_reason(1,"launchd",2,11,NULL);
 assert(strstr(display.previous[29],"000000000000000b"));
 assert(!memcmp(saved,&display.previous[20],8*BP_COLS)&&!memcmp(&saved[10],&display.previous[30],14*BP_COLS));
 memcpy(saved,&display.previous[20],sizeof saved);myron_boot_progress_panic("original panic",0xabcdef);
 assert(myron_panic_pc==0xabcdef&&!myron_panic_esr&&!memcmp(saved,&display.previous[20],sizeof saved));
 // A later unrelated DYLD exit must keep its useful description, even if
 // an earlier exception was delivered and handled by userspace.
 reset();invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,1);
 boot_progress_exit_reason(1,"launchd",6,1,"Library not loaded: test.dylib");
 assert(!strcmp(display.previous[30],"Library not loaded: test.dylib"));
 myron_boot_progress_panic("dyld panic",0x1234);
 assert(!strcmp(display.previous[30],"Library not loaded: test.dylib"));
 // Scalar exit fallback covers a signal exit with no captured user abort,
 // without fabricating a PC or hiding DYLD text. First values are immutable.
 reset();boot_progress_exit_mach(2,1,2,3);assert(!exit_mach_ready);
 struct test_proc proc={.pid=1};struct exit_uthread ut={1,2,0x98765432};struct task foreign={0};
 capture_exit_hook(&proc,&test_thread,&ut,&foreign);assert(!exit_mach_ready);
 capture_exit_hook(&proc,&test_thread,NULL,&test_task);assert(!exit_mach_ready);
 proc.pid=2;capture_exit_hook(&proc,&test_thread,&ut,&test_task);assert(!exit_mach_ready);proc.pid=1;
 capture_exit_hook(&proc,&test_thread,&ut,&test_task);assert(exit_mach_ready);
 boot_progress_exit_mach(1,4,5,6);assert(exit_mach_exception==1&&exit_mach_code==2);
 boot_progress_exit_reason(1,"launchd",2,11,NULL);
 assert(strstr(display.previous[20],"no saved user state")&&strstr(display.previous[22],"98765432"));
 assert(!strstr(display.previous[21],"PC=")&&!strcmp(display.previous[30],"(no exit reason description)"));
 memcpy(saved,&display.previous[20],sizeof saved);myron_boot_progress_panic("signal exit",0x1234);
 assert(!memcmp(saved,&display.previous[20],sizeof saved));
 reset();boot_progress_exit_mach(1,0,0,0);boot_progress_exit_reason(1,"launchd",2,11,NULL);
 assert(strstr(display.previous[23],"Zero codes"));
 reset();boot_progress_exit_mach(1,1,2,3);boot_progress_exit_reason(1,"launchd",6,1,"DYLD precise description");
 assert(!strstr(display.previous[20],"EXIT MACH")&&!strcmp(display.previous[30],"DYLD precise description"));
 reset();invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,1);boot_progress_exit_mach(1,1,2,3);
 boot_progress_exit_reason(1,"launchd",2,11,NULL);assert(strstr(display.previous[20],"USER ABORT"));
 // Execute fault preserves full lookup address and protection result.
 reset();vm_result=KERN_PROTECTION_FAILURE;test_task.task_shared_region_slide=UINT32_MAX;
 invoke(&s,0x8000000d,s.far,FSC_PERMISSION,5,1);
 assert(vm_address==s.far&&delivered_codes[0]==KERN_PROTECTION_FAILURE&&user_pac_snapshot.fault_type==5);
 assert(strstr(display.previous[20],"instruction")&&strstr(display.previous[26],"0xffffffff"));
 reset();test_task.task_shared_region_slide=0;invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,1);assert(user_pac_snapshot.cache_slide==0);
 // Existing PAC classification is retained, whichever compile side is selected.
 reset();pac_match=1;invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,1);
 assert(delivered_exception==(EXC_BAD_ACCESS|(TEST_PTRAUTH?EXC_PTRAUTH_BIT:0)));
 assert(user_pac_snapshot.exception==delivered_exception);
 // Emulation success returns without a snapshot; recovery preserves both ESRs.
 reset();alignment_result=0;invoke(&s,0x90000021,s.far,FSC_ALIGNMENT,3,3);assert(!user_pac_ready);
 reset();alignment_result=EFAULT;invoke(&s,0x90000021,s.far,FSC_ALIGNMENT,3,1);assert(delivered_codes[0]==KERN_INVALID_ADDRESS);
 reset();alignment_result=EFAULT;alignment_recover=1;invoke(&s,0x90000021,s.far,FSC_ALIGNMENT,3,1);
 assert(delivered_codes[0]==KERN_PROTECTION_FAILURE&&delivered_codes[1]==0xbeef1234);
 assert(user_pac_snapshot.esr==0x90000021&&user_pac_snapshot.saved_esr==0x90000007&&user_pac_snapshot.far==0xbeef1234);
 assert(user_pac_snapshot.exception_address==0xbeef1234);
 // Shared claim: existing PAC state wins, and the later abort never overwrites it.
 reset();struct boot_progress_user_pac_state pac={.pid=1,.kind=0,.pc=0xfeed1234};boot_progress_user_pac(&pac);
 invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,1);assert(user_pac_snapshot.pc==pac.pc&&user_pac_snapshot.kind==0);
 boot_progress_exit_reason(1,"launchd",2,11,NULL);assert(strstr(display.previous[20],"USER PAC"));
 for(int mode=0;mode<6;mode++){
  reset();pid=mode==0?2:1;s.is64=mode==1?0:1;s.cpsr=mode==2?4:0;enabled=mode==3?0:1;
  scanout_state=mode==4?2:0;panic_claimed=mode==5?1:0;
  invoke(&s,s.esr,s.far,FSC_TRANSLATION,1,1);assert(!user_pac_ready);
 }
 enabled=1;s.is64=1;s.cpsr=0;
 for(size_t i=0;i<32;i++)assert(mem[i]==0xa5&&mem[bytes+32+i]==0xa5);
 for(size_t y=0;y<1500;y++)for(size_t x=720*4;x<736*4;x++)assert(mem[32+y*736*4+x]==0xa5);
 free(mem);return 0;
}
'''
    (w/'test.c').write_text(stubs + '\n' + code + '\n' + fallback_code + '\n' + tests)
    for feature in (0, 1):
        subprocess.run([a.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-DMYRON_EARLY_PROGRESS=1',
                        f'-DTEST_PTRAUTH={feature}', f'-DMACH_ASSERT={feature}', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-I', str(w), '-I', str(a.device.resolve()/'package'), str(w/'test.c'), '-o', str(w/'test')], check=True)
        subprocess.run([str(w/'test')], check=True, timeout=20, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    (w/'off.c').write_text('#include <kern/boot_progress.h>\nint main(void){int n=0;boot_progress_user_abort_context((void*)(long)++n);boot_progress_exit_mach(++n,++n,++n,++n);return n;}\n')
    subprocess.run([a.cc, '-std=c11', '-I', str(w), str(w/'off.c'), '-o', str(w/'off')], check=True)
    subprocess.run([str(w/'off')], check=True)
print('PASS exact user-abort handler and patch stack, unchanged VM/exception policy, successful/aborted/fast faults excluded, data/instruction failures, alignment recovery, both PAC-classification branches, PID1/user64 guards, cached raw slide, all29 GPRs, first-event ownership, SIGSEGV/panic/IRQ retention, exit-thread Mach fallback without DYLD overwrite, 60-column bounds, disabled hook; ASan/UBSan host execution')
