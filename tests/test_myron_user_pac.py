#!/usr/bin/env python3
"""Execute the actual PAC handler and bounded recorder after exact patch application."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
for name in ('device','upstream','xnu'):p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--cc',default='cc')
a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subjects=('osfmk/arm64/sleh.c','osfmk/kern/boot_progress.h')
def handler(text):
    return 'static void\nhandle_pac_fail'+text.split('static void\nhandle_pac_fail',1)[1].split('\n}\n',1)[0]+'\n}\n'
with tempfile.TemporaryDirectory() as tmp:
    w=Path(tmp);dest=w/subjects[0];dest.parent.mkdir(parents=True);shutil.copyfile(a.xnu/subjects[0],dest)
    for scope in ('arch','os','device'):
        series=roots[scope]/'patches/xnu/series'
        for line in series.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            prefix,sep,tail=line.partition(':')
            patch=(roots[prefix]/tail if sep else series.parent/line).resolve();text=patch.read_text()
            if not any('--- a/'+n in text or '+++ b/'+n in text for n in subjects):continue
            subprocess.run(['git','apply',*[f'--include={n}' for n in subjects],str(patch)],cwd=w,check=True)
    patched_source=dest.read_text();original_source=(a.xnu/subjects[0]).read_text()
    # The handler-only harness cannot compile XNU's complete header graph.
    # Check its newly introduced dependencies too: importing BSD proc.h into
    # OSFMK collides with the Mach dev_t, daddr_t and clock_t definitions.
    def includes(source):
        return set(re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]',source,re.M))
    added_headers=includes(patched_source)-includes(original_source)
    removed_headers=includes(original_source)-includes(patched_source)
    assert added_headers=={'kern/boot_progress.h'} and not removed_headers, (
        f'Unexpected sleh.c header dependencies: added={sorted(added_headers)}, '
        f'removed={sorted(removed_headers)}; do not import BSD process types into OSFMK')
    def pid_declaration(source):
        declarations=re.findall(r'^\s*extern[^;\n]*\bproc_selfpid\s*\([^;\n]*\)\s*;',source,re.M)
        assert len(declarations)==1, 'Require one explicit proc_selfpid prototype'
        return declarations[0].strip()
    pid_decl=pid_declaration(patched_source)
    signature=lambda declaration:re.sub(r'\s+','',declaration)
    assert signature(pid_decl)==signature(pid_declaration((a.xnu/'bsd/sys/proc.h').read_text()))
    assert signature(pid_decl)==signature(pid_declaration((a.xnu/'osfmk/kern/exception.c').read_text()))
    code=handler(patched_source);original=handler(original_source)
    start=code.index('#if (defined(XNU_BOOT_PROGRESS) && XNU_BOOT_PROGRESS) || defined(MYRON_EARLY_PROGRESS)\n')
    end=code.index('#endif\n\n',start)+len('#endif\n\n')
    assert code[:start]+code[end:]==original, 'Exception decisions changed'
    hook=code[start:end]
    assert code.count('COPYIN(')==1 and 'COPYIN(' not in hook and 'proc_selfpid() == 1' in hook
    assert code.index('panic_with_thread_kernel_state(')<start<code.index('codes[1] = instr;')
    header=(w/subjects[1]).read_text();(w/'kern').mkdir();(w/'kern/boot_progress.h').write_text(header)
    (w/'pexpert').mkdir();(w/'pexpert/pexpert.h').write_text('#define kPEReleaseScreen 3\nint PE_parse_boot_argn(const char *,void *,int);\nint PE_initialize_console(void *,int);\n')
    src=(a.device/'package/MyronBootProgress.c').read_text()
    for old,new in [('__asm__ volatile("mrs %0, cntvct_el0":"=r"(t));','t=test_clock;'),('__asm__ volatile("mrs %0, cntfrq_el0":"=r"(frequency));','frequency=1000;'),('__asm__ volatile("mrs %0, cntvct_el0":"=r"(epoch));','epoch=test_clock;')]:
        assert src.count(old)==1;src=src.replace(old,new)
    (w/'recorder.c').write_text('static unsigned long long test_clock;\n'+src)
    stubs=r'''
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include "recorder.c"
typedef int exception_type_t;
typedef uint64_t mach_exception_data_type_t;
typedef unsigned mach_msg_type_number_t;
typedef unsigned ptrauth_key;
typedef struct { int is64; uint64_t pc,lr,sp,fp,cpsr,far,x[29]; } arm_saved_state_t;
static int pid=1, copies;
static uint32_t instruction=0xdac11020;
static jmp_buf escape;
static unsigned delivered_exception,delivered_num;
static uint64_t delivered_codes[2];
#define EXC_BAD_ACCESS 1
#define EXC_PTRAUTH_BIT 0x200
#define EXC_ARM_PAC_FAIL 0x105
#define PSR64_IS_KERNEL(v) ((v)&4)
#define is_saved_state64(s) ((s)->is64)
#define get_saved_state_pc(s) ((s)->pc)
#define get_saved_state_lr(s) ((s)->lr)
#define get_saved_state_sp(s) ((s)->sp)
#define get_saved_state_fp(s) ((s)->fp)
#define get_saved_state_cpsr(s) ((s)->cpsr)
#define get_saved_state_far(s) ((s)->far)
#define get_saved_state_reg(s,i) ((s)->x[(i)])
#define COPYIN(pc,dst,n) ((void)(pc), assert((n)==4), ++copies, memcpy((dst),&instruction,4))
#define ARM64_INSTR_IS_AUTxx(i) ((i)==1)
#define ARM64_INSTR_IS_AUTIx_SYSTEM(i) ((i)==2)
#define ARM64_INSTR_IS_BxRAx(i) ((i)==3)
#define ARM64_INSTR_IS_RETAx(i) ((i)==4)
static const char *ptrauth_key_to_string(ptrauth_key k){(void)k;return "IA";}
static void autxx_instruction_extract_reg(uint32_t i,char r[4]){(void)i;strcpy(r,"x0");}
static const char *autix_system_instruction_extract_reg(uint32_t i){(void)i;return "lr";}
static void bxrax_instruction_extract_reg(uint32_t i,char r[4]){(void)i;strcpy(r,"x0");}
int proc_selfpid(void){return pid;}
__attribute__((noreturn)) static void panic(const char *s,...){(void)s;longjmp(escape,2);}
__attribute__((noreturn)) static void panic_with_thread_kernel_state(const char *s,arm_saved_state_t *p){(void)s;(void)p;longjmp(escape,3);}
__attribute__((noreturn)) static void exception_triage(exception_type_t e,mach_exception_data_type_t *c,mach_msg_type_number_t n){delivered_exception=e;delivered_num=n;memcpy(delivered_codes,c,sizeof delivered_codes);longjmp(escape,1);}
int PE_parse_boot_argn(const char *k,void *v,int n){(void)k;(void)n;*(unsigned *)v=2;return 1;}
int PE_initialize_console(void *p,int n){(void)p;(void)n;return 0;}
'''
    tests=r'''
static void reset(void){user_pac_claimed=user_pac_ready=critical_exit_claimed=critical_exit_ready=critical_exit_bytes=panic_claimed=scanout_state=0;pid=1;copies=0;}
static void invoke(arm_saved_state_t *s,int result){int r=setjmp(escape);if(!r)handle_pac_fail(s,0x24000001);assert(r==result);}
int main(void){
 boot_progress_init();
 size_t bytes=736*4*1500;unsigned char *mem=malloc(bytes+64);assert(mem);memset(mem,0xa5,bytes+64);
 display.frame=(uintptr_t)(mem+32);display.width=720;display.height=1500;display.stride=736*4;display.scale=2;display.bound=1;
 arm_saved_state_t s={.is64=1,.pc=0x180001234,.lr=0x180005678,.sp=0x16fff0000,.fp=0x16fff0100,.cpsr=0,.far=0xdead0000};
 for(unsigned i=0;i<29;i++)s.x[i]=0x100000000ULL+i;
 reset();s.is64=0;invoke(&s,2);assert(!copies&&!user_pac_ready);s.is64=1;
 reset();s.cpsr=4;invoke(&s,3);assert(copies==1&&!user_pac_ready);s.cpsr=0;
 reset();pid=2;invoke(&s,1);assert(copies==1&&!user_pac_ready);
 reset();invoke(&s,1);assert(copies==1&&user_pac_ready&&!panic_claimed);
 assert(delivered_exception==(EXC_BAD_ACCESS|EXC_PTRAUTH_BIT)&&delivered_num==2&&delivered_codes[0]==0x105&&delivered_codes[1]==instruction);
 assert(user_pac_snapshot.pid==1&&user_pac_snapshot.instruction==instruction&&user_pac_snapshot.pc==s.pc&&user_pac_snapshot.lr==s.lr&&user_pac_snapshot.sp==s.sp&&user_pac_snapshot.fp==s.fp&&user_pac_snapshot.cpsr==s.cpsr&&user_pac_snapshot.esr==0x24000001&&user_pac_snapshot.far==s.far);
 assert(!memcmp(user_pac_snapshot.x,s.x,sizeof s.x));
 for(unsigned r=20;r<44;r++)assert(strlen(display.previous[r])<=60);
 assert(strstr(display.previous[24],"validity unknown"));assert(strstr(display.previous[25],"dac11020"));
 char saved[24][BP_COLS];memcpy(saved,&display.previous[20],sizeof saved);
 s.pc++;invoke(&s,1);assert(user_pac_snapshot.pc==s.pc-1);
 boot_progress_stage("later");boot_progress_putc('\n');test_clock+=1000;boot_progress_irq(8,7,6);myron_mount_event(1,"later","apfs",0,0);
 assert(!memcmp(saved,&display.previous[20],sizeof saved));
 boot_progress_exit_reason(1,"launchd",28,0x105,NULL);
 assert(strstr(display.previous[28],"launchd")&&strstr(display.previous[29],"0000000000000105"));
 assert(!memcmp(saved,&display.previous[20],8*BP_COLS));assert(!memcmp(&saved[10],&display.previous[30],14*BP_COLS));
 memcpy(saved,&display.previous[20],sizeof saved);myron_boot_progress_panic("original panic",0xabcdef);assert(myron_panic_pc==0xabcdef&&!myron_panic_esr);
 assert(!memcmp(saved,&display.previous[20],sizeof saved));
 reset();enabled=0;invoke(&s,1);assert(!user_pac_ready);enabled=1;
 reset();scanout_state=2;invoke(&s,1);assert(!user_pac_ready);
 reset();panic_claimed=1;invoke(&s,1);assert(!user_pac_ready);
 for(size_t i=0;i<32;i++)assert(mem[i]==0xa5&&mem[bytes+32+i]==0xa5);
 for(size_t y=0;y<1500;y++)for(size_t x=720*4;x<736*4;x++)assert(mem[32+y*736*4+x]==0xa5);
 free(mem);return 0;
}
'''
    # Keep the upstream handler byte-for-byte intact. Its constant strlen-based
    # array bound is a Clang extension; suppress only that diagnostic, only in
    # this extracted function. Recorder, stubs and tests retain strict warnings.
    handler_prefix='''
#if defined(__clang__)
#pragma clang diagnostic push
#if __has_warning("-Wgnu-folding-constant")
#pragma clang diagnostic ignored "-Wgnu-folding-constant"
#endif
#endif
'''
    handler_suffix='''
#if defined(__clang__)
#pragma clang diagnostic pop
#endif
'''
    (w/'test.c').write_text(pid_decl+'\n'+stubs+'\n'+handler_prefix+code+handler_suffix+'\n'+tests)
    subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-DMYRON_EARLY_PROGRESS=1','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(w),'-I',str(a.device.resolve()/'package'),str(w/'test.c'),'-o',str(w/'test')],check=True)
    subprocess.run([str(w/'test')],check=True,timeout=20,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
    (w/'off.c').write_text('#include <kern/boot_progress.h>\nint main(void){int n=0;boot_progress_user_pac((void*)(long)++n);return n;}\n')
    subprocess.run([a.cc,'-std=c11','-I',str(w),str(w/'off.c'),'-o',str(w/'off')],check=True)
    subprocess.run([str(w/'off')],check=True)
print('PASS exact PAC patch stack, OSFMK header boundary and original proc_selfpid prototype, unchanged handler and exception policy, PID 1 first snapshot, all 29 GPRs, bounded 60-column render, IRQ/mount/exit/panic retention, ownership guards and disabled hook; ASan/UBSan host execution')
