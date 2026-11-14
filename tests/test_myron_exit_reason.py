#!/usr/bin/env python3
"""Apply selected exit hooks and exercise actual bounded fatal-reason rendering."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--device',type=Path,required=True)
p.add_argument('--upstream',type=Path,required=True)
p.add_argument('--xnu',type=Path,required=True)
p.add_argument('--cc',default='cc')
a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subjects=('bsd/kern/kern_exit.c','osfmk/kern/boot_progress.h')
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
    code=dest.read_text()
    call='\tboot_progress_exit_reason(proc_getpid(p), p->p_name,\n\t    p->p_exit_reason ? p->p_exit_reason->osr_namespace : 0,\n\t    p->p_exit_reason ? p->p_exit_reason->osr_code : 0,\n\t    exit_reason_desc);\n'
    assert code.count(call)==1
    critical=code.split('proc_handle_critical_exit(proc_t p, int rv)\n{',1)[1].split('\nvoid\nproc_prepareexit',1)[0]
    assert critical.index('sync(p,') < critical.index(call) < critical.index('panic_with_options(')
    assert critical.index('exit_reason_get_string_desc(') < critical.index(call)
    original=(a.xnu/subjects[0]).read_text().split('proc_handle_critical_exit(proc_t p, int rv)\n{',1)[1].split('\nvoid\nproc_prepareexit',1)[0]
    # The existing legacy prefix allocation and stage hook remain; all original
    # panic arguments, string limit, sync, coredump and conditions are intact.
    tail='\tif (p->p_exit_reason == OS_REASON_NULL) {\n\t\tpanic_with_options('
    assert critical.split(tail,1)[1] == original.split(tail,1)[1]
    header=(w/subjects[1]).read_text()
    (w/'kern').mkdir();(w/'kern/boot_progress.h').write_text(header)
    (w/'pexpert').mkdir();(w/'pexpert/pexpert.h').write_text('#define kPEReleaseScreen 3\nint PE_parse_boot_argn(const char *,void *,int);\nint PE_initialize_console(void *,int);\n')
    src=(a.device/'package/MyronBootProgress.c').read_text()
    for old,new in [('__asm__ volatile("mrs %0, cntvct_el0":"=r"(t));','t=test_clock;'),('__asm__ volatile("mrs %0, cntfrq_el0":"=r"(frequency));','frequency=1000;'),('__asm__ volatile("mrs %0, cntvct_el0":"=r"(epoch));','epoch=test_clock;')]:
        assert src.count(old)==1;src=src.replace(old,new)
    (w/'recorder.c').write_text('static unsigned long long test_clock;\n'+src)
    test=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "recorder.c"
int PE_parse_boot_argn(const char *k,void *v,int n){(void)k;(void)n;*(unsigned *)v=2;return 1;}
int PE_initialize_console(void *p,int n){(void)p;(void)n;return 0;}
static void reset(void){critical_exit_claimed=critical_exit_ready=critical_exit_bytes=0;panic_claimed=0;scanout_state=0;}
static void join(char *s){s[0]=0;for(unsigned r=30;r<44;r++)strcat(s,display.previous[r]);}
int main(void){
 boot_progress_init();
 size_t bytes=736*4*1500;unsigned char *mem=malloc(bytes+64);assert(mem);memset(mem,0xa5,bytes+64);
 display.frame=(uintptr_t)(mem+32);display.width=720;display.height=1500;display.stride=736*4;display.scale=2;display.bound=1;
 char *exact=malloc(800);assert(exact);for(unsigned i=0;i<800;i++)exact[i]='A'+i%26;
 // An exactly 800-byte source without NUL exercises the hard read limit.
 boot_progress_exit_reason(1,"launchd",6,1,exact);assert(critical_exit_bytes==800 && critical_exit_pid==1);
 char combined[2000];join(combined);assert(strlen(combined)==800 && !memcmp(combined,exact,800));
 assert(strstr(display.previous[28],"800-byte limit"));
 for(unsigned r=30;r<44;r++)assert(strlen(display.previous[r])<=60);
 char saved[14][BP_COLS];memcpy(saved,&display.previous[30],sizeof saved);
 boot_progress_putc('\n');boot_progress_stage("later stage");test_clock+=1000;boot_progress_irq(9,8,7);
 myron_mount_event(1,"late mount","apfs",0,0);assert(!memcmp(saved,&display.previous[30],sizeof saved));
 // The original panic still captures its own caller and preserves the reason.
 myron_boot_progress_panic("ordinary panic %s",0x1234);assert(myron_panic_pc==0x1234 && !myron_panic_esr);
 assert(!memcmp(saved,&display.previous[30],sizeof saved));
 boot_progress_exit_reason(2,"other",9,2,"replacement");assert(critical_exit_pid==1);
 reset();display.width=1200;display.stride=1216*4;free(mem);bytes=1216*4*1500;mem=malloc(bytes+64);assert(mem);memset(mem,0xa5,bytes+64);display.frame=(uintptr_t)(mem+32);memset(display.previous,0,sizeof display.previous);
 boot_progress_exit_reason(1,"launchd",6,1,exact);join(combined);assert(strlen(combined)==800);
 for(unsigned r=30;r<44;r++)assert(strlen(display.previous[r])<=96);
 // Tabs/newlines become spaces, preserving all characters within row budget.
 reset();boot_progress_exit_reason(1,"launchd",6,1,"Library not loaded:\n/usr/lib/X\r\nReason:\tmissing");join(combined);
 assert(!strcmp(combined,"Library not loaded: /usr/lib/X  Reason: missing"));
 reset();boot_progress_exit_reason(1,"launchd",6,1,NULL);join(combined);assert(!strcmp(combined,"(no exit reason description)"));
 reset();boot_progress_exit_reason(1,"launchd",6,1,"");join(combined);assert(!combined[0]);
 // Full-frame padding and guards are never touched.
 for(size_t i=0;i<32;i++)assert(mem[i]==0xa5 && mem[bytes+32+i]==0xa5);
 for(size_t y=0;y<1500;y++)for(size_t x=1200*4;x<1216*4;x++)assert(mem[32+y*1216*4+x]==0xa5);
 reset();scanout_state=2;boot_progress_exit_reason(1,"launchd",6,1,"hidden");assert(!critical_exit_ready);
 reset();panic_claimed=1;boot_progress_exit_reason(1,"launchd",6,1,"later");assert(!critical_exit_ready);
 free(exact);free(mem);return 0;
}
'''
    (w/'test.c').write_text(test)
    subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-DMYRON_EARLY_PROGRESS=1','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(w),'-I',str(a.device.resolve()/'package'),str(w/'test.c'),'-o',str(w/'test')],check=True)
    subprocess.run([str(w/'test')],check=True,timeout=20,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
    (w/'off.c').write_text('#include <kern/boot_progress.h>\nint main(void){int n=0;boot_progress_exit_reason(++n,(void*)1,++n,++n,(void*)1);return n;}\n')
    subprocess.run([a.cc,'-std=c11','-I',str(w),str(w/'off.c'),'-o',str(w/'off')],check=True)
    subprocess.run([str(w/'off')],check=True)
print('PASS selected exit patch stack, unchanged panic decisions, 800-byte bound, minimum-width/full-width wrapping, controls/null/empty descriptions, persistence through IRQ/mount/ordinary panic, scanout/first-panic ownership, disabled-board no evaluation')
