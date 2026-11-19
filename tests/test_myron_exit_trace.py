#!/usr/bin/env python3
"""Exercise the selected SIGABRT exit hook and bounded framebuffer recorder."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
for name in ('device', 'upstream', 'xnu'):
    p.add_argument('--' + name, type=Path, required=True)
p.add_argument('--cc', default='clang')
a = p.parse_args()
roots = dict(device=a.device.resolve(), arch=a.upstream.resolve()/'profiles/arch/arm64e',
             os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subjects = ('bsd/kern/kern_exit.c', 'osfmk/kern/boot_progress.h', 'osfmk/kern/task.c')
with tempfile.TemporaryDirectory() as tmp:
    w = Path(tmp)
    for name in subjects:
        if (a.xnu/name).exists():
            (w/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a.xnu/name, w/name)
    before = None
    for scope in ('arch', 'os', 'device'):
        series = roots[scope]/'patches/xnu/series'
        for line in series.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            prefix, sep, tail = line.partition(':')
            patch = (roots[prefix]/tail if sep else series.parent/line).resolve()
            if patch.name == 'myron-sigabrt-exit-trace.patch':
                before = (w/subjects[0]).read_text()
            if any('--- a/'+n in patch.read_text() or '+++ b/'+n in patch.read_text() for n in subjects):
                subprocess.run(['git', 'apply', *[f'--include={n}' for n in subjects], str(patch)], cwd=w, check=True)
    code = (w/subjects[0]).read_text()
    marker = '\t/* PID 1 panics before the ordinary crash-report backtrace below.'
    start = code.rfind('#if ', 0, code.index(marker))
    end = code.index('#endif\n', start) + len('#endif\n')
    hook = code[start:end]
    # Both board probes are additive. Removing both must restore the exact baseline.
    board_call = code.index('myron_desktop_exit(slot,')
    board_start = code.rfind('#if defined(MYRON_EARLY_PROGRESS)', 0, board_call)
    assert board_start >= 0
    board_end = code.index('#endif\n', board_start) + len('#endif\n')
    assert board_start < board_call < board_end <= start
    assert (code[:board_start] + code[board_end:start] + code[end:]).replace('#include <machine/machine_routines.h>\n', '') == before
    assert code.index('ut = get_bsdthread_info(self);', code.index('proc_prepareexit(proc_t p')) < start
    assert end < code.index('proc_handle_critical_exit(p, rv);', end)
    assert 'backtrace_user(' in hook and 'copyin(' not in hook
    assert 'task->' not in hook
    assert 'boot_progress_current_cache_slide()' in hook
    assert 'backtrace_user(bt, 2, NULL, &btinfo)' in before
    mach_source = (w/subjects[2]).read_text()
    accessor = 'uint32_t\nboot_progress_current_cache_slide(void)\n{' + mach_source.split(
        'uint32_t\nboot_progress_current_cache_slide(void)\n{', 1)[1].split('\n}\n', 1)[0] + '\n}\n'
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
    stubs = r'''
#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include "recorder.c"
#define TASK_NULL NULL
struct proc { int pid; };
typedef struct proc *proc_t;
/* Match the BSD compilation boundary: the layout is unavailable here. */
struct task;
typedef struct task *task_t;
struct thread { task_t task; };
typedef struct thread *thread_t;
static struct proc init={1}, other={2};
extern struct task own, foreign;
static struct thread th={&own};
static proc_t current=&init;
static unsigned reads, frames_to_return=20, trace_error, trace_flags=3;
static int irqs=1, interrupt_context;
struct backtrace_user_info { int btui_error; unsigned btui_info; };
#define BTUINFO_INIT ((struct backtrace_user_info){0})
static proc_t current_proc(void){return current;}
static int proc_getpid(proc_t p){return p->pid;}
static task_t get_threadtask(thread_t t){return t->task;}
static int ml_get_interrupts_enabled(void){return irqs;}
static int ml_at_interrupt_context(void){return interrupt_context;}
static unsigned backtrace_user(uintptr_t *bt,unsigned n,const void *ctl,struct backtrace_user_info *info){
 assert(n==20 && ctl==NULL);reads++;
 for(unsigned i=0;i<n;i++)bt[i]=0x180000000ULL+i*4;
 info->btui_error=trace_error;info->btui_info=trace_flags;return frames_to_return;
}
int PE_parse_boot_argn(const char *s,void *v,int n){(void)s;(void)n;*(unsigned*)v=2;return 1;}
int PE_initialize_console(void *p,int n){(void)p;(void)n;return 0;}
static void capture(proc_t p,int rv,void *ut,thread_t self,task_t task){
'''
    tests = r'''
}
static void reset(void){
 exit_trace_claimed=exit_trace_ready=critical_exit_claimed=critical_exit_ready=0;
 user_pac_claimed=user_pac_ready=exit_mach_claimed=exit_mach_ready=panic_claimed=scanout_state=0;
 reads=0;current=&init;irqs=1;interrupt_context=0;frames_to_return=20;trace_error=0;trace_flags=3;
 memset(display.previous,0,sizeof display.previous);
}
int main(void){
 boot_progress_init();
 size_t bytes=736*4*1500;unsigned char *mem=malloc(bytes+64);assert(mem);memset(mem,0xa5,bytes+64);
 display.frame=(uintptr_t)(mem+32);display.width=720;display.height=1500;display.stride=736*4;display.scale=2;display.bound=1;
 reset();capture(&other,6,&th,&th,&own);assert(!reads&&!exit_trace_ready);
 reset();capture(&init,11,&th,&th,&own);assert(!reads&&!exit_trace_ready);
 reset();capture(&init,0,&th,&th,&own);assert(!reads&&!exit_trace_ready);
 reset();current=&other;capture(&init,6,&th,&th,&own);assert(!reads&&!exit_trace_ready);
 reset();capture(&init,6,NULL,&th,&own);assert(!reads&&!exit_trace_ready);
 reset();capture(&init,6,&th,&th,NULL);assert(!reads&&!exit_trace_ready);
 reset();capture(&init,6,&th,&th,&foreign);assert(!reads&&!exit_trace_ready);
 reset();capture(&init,6,&th,&th,&own);assert(reads==1&&exit_trace_ready&&exit_trace_snapshot.count==20);
 assert(exit_trace_snapshot.frames[19]==0x18000004cULL&&exit_trace_snapshot.cache_slide==0x02e3c000);
 boot_progress_exit_reason(1,"launchd",2,6,NULL);
 assert(strstr(display.previous[20],"SIGABRT"));assert(strstr(display.previous[39],"BT19=0x000000018000004c"));
 char saved[44][BP_COLS];memcpy(saved,display.previous,sizeof saved);
 boot_progress_putc('\n');boot_progress_stage("later");test_clock+=1000;boot_progress_irq(9,8,7);
 myron_mount_event(1,"later","apfs",0,0);myron_boot_progress_panic("panic",0x1234);
 assert(!memcmp(&saved[20],&display.previous[20],24*BP_COLS));
 reset();irqs=0;capture(&init,6,&th,&th,&own);assert(!reads&&exit_trace_ready&&exit_trace_snapshot.error==EDEADLK);
 reset();interrupt_context=1;capture(&init,6,&th,&th,&own);assert(!reads&&exit_trace_snapshot.error==EDEADLK);
 reset();frames_to_return=3;trace_error=EFAULT;capture(&init,6,&th,&th,&own);
 assert(exit_trace_snapshot.count==3&&exit_trace_snapshot.error==EFAULT);
 boot_progress_exit_reason(1,"launchd",2,6,NULL);assert(strstr(display.previous[31],"BT02="));assert(!strstr(display.previous[31],"BT03="));
 reset();frames_to_return=0;trace_error=EINVAL;capture(&init,6,&th,&th,&own);
 boot_progress_exit_reason(1,"launchd",2,6,NULL);assert(!display.previous[30][0]&&strstr(display.previous[22],"0000000016"));
 reset();frames_to_return=100;capture(&init,6,&th,&th,&own);assert(exit_trace_snapshot.count==20);
 struct boot_progress_exit_trace replacement={.count=1,.error=9};boot_progress_exit_trace(&replacement);assert(exit_trace_snapshot.count==20);
 reset();scanout_state=2;boot_progress_exit_trace(&replacement);assert(!exit_trace_ready);
 reset();panic_claimed=1;boot_progress_exit_trace(&replacement);assert(!exit_trace_ready);
 reset();boot_progress_exit_trace(NULL);assert(!exit_trace_ready);
 reset();capture(&init,6,&th,&th,&own);boot_progress_exit_reason(1,"launchd",6,1,"dyld reason");assert(strstr(display.previous[30],"dyld reason"));
 reset();capture(&init,6,&th,&th,&own);char reason[801];memset(reason,'A',800);reason[800]=0;
 boot_progress_exit_reason(1,"launchd",2,6,reason);unsigned count=0;for(unsigned r=30;r<44;r++)count+=strlen(display.previous[r]);assert(count==800);
 reset();capture(&init,6,&th,&th,&own);struct boot_progress_user_pac_state fault={.pid=1,.kind=1,.esr=0x92000004};
 boot_progress_user_abort_context(&fault);boot_progress_exit_reason(1,"launchd",2,6,NULL);assert(strstr(display.previous[20],"USER ABORT"));
 for(size_t i=0;i<32;i++)assert(mem[i]==0xa5&&mem[bytes+32+i]==0xa5);
 for(size_t y=0;y<1500;y++)for(size_t x=720*4;x<736*4;x++)assert(mem[32+y*736*4+x]==0xa5);
 free(mem);return 0;
}
'''
    # Compile the real accessor in a separate Mach-side translation unit.
    # Its layout is deliberately not visible to the BSD hook above.
    (w/'mach.c').write_text('''#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <kern/boot_progress.h>
struct task { uint32_t task_shared_region_slide; };
typedef struct task *task_t;
#define TASK_NULL NULL
struct task own={0x02e3c000}, foreign={0};
static task_t active_task=&own;
static task_t current_task(void){return active_task;}
''' + accessor + '''
void check_accessor(void){
 assert(boot_progress_current_cache_slide()==0x02e3c000);
 active_task=NULL;assert(boot_progress_current_cache_slide()==UINT32_MAX);
 active_task=&foreign;assert(boot_progress_current_cache_slide()==0);
 active_task=&own;
}
''')
    (w/'test.c').write_text(stubs+hook+tests.replace(' boot_progress_init();',' extern void check_accessor(void);check_accessor();\n boot_progress_init();',1))
    subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-DMYRON_EARLY_PROGRESS=1',
                    '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(w),
                    '-I',str(a.device.resolve()/'package'),str(w/'test.c'),str(w/'mach.c'),'-o',str(w/'test')],check=True)
    # Negative control: the exact old private-field access must fail to compile
    # with the opaque BSD task, on Linux and macOS alike.
    bad = (w/'test.c').read_text().replace('snapshot.cache_slide = boot_progress_current_cache_slide();',
                                        'snapshot.cache_slide = task->task_shared_region_slide;')
    assert bad != (w/'test.c').read_text()
    (w/'bad.c').write_text(bad)
    result=subprocess.run([a.cc,'-std=c11','-DMYRON_EARLY_PROGRESS=1','-I',str(w),
                          '-I',str(a.device.resolve()/'package'),'-fsyntax-only',str(w/'bad.c')],capture_output=True,text=True)
    assert result.returncode != 0 and ('incomplete' in result.stderr or 'undefined type' in result.stderr), result.stderr
    subprocess.run([str(w/'test')],check=True,timeout=20,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
    (w/'off.c').write_text('#include <kern/boot_progress.h>\nint main(void){int n=0;boot_progress_exit_trace((void*)(long)++n);return n;}\n')
    subprocess.run([a.cc,'-std=c11','-I',str(w),str(w/'off.c'),'-o',str(w/'off')],check=True)
    subprocess.run([str(w/'off')],check=True)
print('PASS opaque BSD task boundary and private Mach accessor, old field-access negative control; exact exit hook guards, bounded/partial/empty trace, first snapshot, framebuffer bounds, panic persistence, full reason and fault priority, disabled-board no evaluation')
