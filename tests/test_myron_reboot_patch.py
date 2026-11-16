#!/usr/bin/env python3
"""Apply the real reboot hooks and execute the authorized BSD entry path.

No shutdown timeout or authorization policy may be removed by this patch.
The recorder itself is exercised/cross-compiled by test_myron_progress.py.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
for n in ('device','upstream','xnu'): p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--cc',default='clang')
a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',
           os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
paths=['bsd/kern/kern_xxx.c','bsd/kern/kern_shutdown.c','osfmk/kern/machine.c',
       'iokit/Kernel/IOPlatformExpert.cpp','iokit/Kernel/IOPMrootDomain.cpp','osfmk/kern/boot_progress.h']
with tempfile.TemporaryDirectory() as td:
    w=Path(td)
    for name in paths[:-1]:
        dest=w/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((a.xnu/name).read_bytes())
    for scope in ('arch','os','device'):
        series=roots[scope]/'patches/xnu/series'
        for line in series.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            prefix,sep,tail=line.partition(':')
            patch=(roots[prefix]/tail if sep else series.parent/line).resolve()
            if not any('+++ b/'+name in patch.read_text() for name in paths):continue
            subprocess.run(['git','apply',*['--include='+n for n in paths],str(patch)],cwd=w,check=True)
    own=(roots['device']/'patches/xnu/myron-reboot-evidence.patch').read_text()
    assert not [l for l in own.splitlines() if l.startswith('-') and not l.startswith('---')], 'Original policy removed'
    pe=(w/paths[3]).read_text();pm=(w/paths[4]).read_text()
    assert 'panic("Halt/Restart Timed Out");' in pe
    assert pe.index('myron_boot_reboot_request(4') < pe.index('pmRootDomain->handlePlatformHaltRestart(type)')
    assert pm.index('"PM: NVRAM sync enter"') < pm.index('PESyncNVRAM();') < pm.index('"PM: NVRAM sync returned"')
    assert pm.index('"PM: driver callback enter"') < pm.index('service->systemWillShutdown(') < pm.index('"PM: driver acknowledgement wait"')
    source=(w/paths[0]).read_text()
    source=source[source.index('int\nreboot('):source.index('\nint\nsys_panic_with_data')]
    assert source.index('if (!error)') < source.index('myron_boot_reboot_request') < source.index('backtrace_user(') < source.index('error = reboot_kernel(')
    (w/'kern').mkdir();(w/'kern/boot_progress.h').write_bytes((w/paths[-1]).read_bytes())
    shim=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#define MYRON_EARLY_PROGRESS 1
#define DEVELOPMENT 1
#define DEBUG 0
#define CONFIG_MACF 1
#define __unused __attribute__((unused))
#define kPanicStringMaxLen 1024
#define RB_PANIC 0x100
#define USER_ADDR_NULL 0
#define Z_WAITOK 1
#define Z_ZERO 2
#define P_REBOOT 0x1000
#define ENOMEM 12
#define ENAMETOOLONG 63
#define EDEADLK 11
#define AUDIT_ARG(...) ((void)0)
#define __builtin_ptrauth_strip(p,k) (p)
#include <kern/boot_progress.h>
struct proc {int p_acflag,p_flag,pid;char p_comm[32];};
struct reboot_args {int opt;uintptr_t msg;};
struct backtrace_user_info {int btui_error;unsigned btui_info;};
#define BTUINFO_INIT {0,0}
static int permission_error,mac_error,interrupt_ok=1,interrupt_context;
static int recorded,traced,rebooted,unwound,allocation_fail,skip_trace;
static const char *expected_message;
static void *kauth_cred_get(void){return NULL;}
static int suser(void *c,int *f){(void)c;(void)f;return permission_error;}
static void *kalloc_data(size_t n,int f){(void)f;return allocation_fail ? NULL : calloc(1,n);}
static void kfree_data(void *p,size_t n){(void)n;free(p);}
static int copyinstr(uintptr_t p,void *out,size_t n,size_t *got){strncpy(out,(char *)p,n);*got=strlen(out);return 0;}
static void *current_cached_proc_cred(struct proc *p){return p;}
static int mac_system_check_reboot(void *p,int opt){(void)p;(void)opt;return mac_error;}
static void OSBitOrAtomic(int bit,int *p){*p|=bit;}
static int proc_getpid(struct proc *p){return p->pid;}
static int ml_get_interrupts_enabled(void){return interrupt_ok;}
static int ml_at_interrupt_context(void){return interrupt_context;}
uint32_t boot_progress_current_cache_slide(void){return 0x4000;}
static unsigned backtrace_user(uintptr_t *f,unsigned n,void *c,struct backtrace_user_info *i){
 (void)c;assert(n==8 && recorded==1);unwound++;i->btui_error=0;i->btui_info=1;
 for(unsigned x=0;x<n;x++){f[x]=0x10000+x*4;}
 return 8;
}
int myron_boot_reboot_request(unsigned s,int pid,const char *name,unsigned opt,unsigned detail,uint64_t pc,const char *message){
 (void)pc;assert(s==1 && pid==1 && !strcmp(name,"launchd") && opt && !detail);
 assert(!traced && !rebooted);assert((message==NULL)==(expected_message==NULL));
 if(message){assert(!strcmp(message,expected_message));}
 recorded++;return !skip_trace;
}
void myron_boot_reboot_trace(const struct boot_progress_exit_trace *s){
 assert(recorded==1 && !rebooted && s->cache_slide==0x4000);
 if(interrupt_ok && !interrupt_context)assert(s->count==8 && s->frames[7]==0x1001c && s->flags==1);
 else assert(s->count==0 && s->error==EDEADLK);
 traced++;
}
static int reboot_kernel(int options,char *message){(void)options;(void)message;assert(recorded==1&&traced==!skip_trace);rebooted++;return 16;}
'''
    tests=r'''
int main(void){
 struct proc p={0,0,1,"launchd"};struct reboot_args a={0x80,0};int32_t ret=0;
 permission_error=1;assert(reboot(&p,&a,&ret)==1 && !recorded && !p.p_flag);
 permission_error=0;mac_error=2;assert(reboot(&p,&a,&ret)==2 && !recorded && !p.p_flag);
 mac_error=0;assert(reboot(&p,&a,&ret)==16 && recorded==1&&traced==1&&unwound==1&&rebooted==1);
 assert(p.p_flag==P_REBOOT);
 for(int mode=0;mode<2;mode++){
  recorded=traced=rebooted=unwound=0;interrupt_ok=mode;interrupt_context=mode;
  assert(reboot(&p,&a,&ret)==16&&traced==1&&!unwound);
 }
 recorded=traced=rebooted=unwound=0;interrupt_ok=1;interrupt_context=0;
 a.opt=RB_PANIC;a.msg=(uintptr_t)"copied reason";expected_message="copied reason";
 allocation_fail=1;assert(reboot(&p,&a,&ret)==ENOMEM&&!recorded);
 allocation_fail=0;assert(reboot(&p,&a,&ret)==16&&recorded==1&&traced==1);
 recorded=traced=rebooted=unwound=0;skip_trace=1;
 assert(reboot(&p,&a,&ret)==16&&recorded==1&&!traced&&!unwound&&rebooted==1);
 return 0;
}
'''
    (w/'test.c').write_text(shim+source+tests)
    subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',
                    '-I',str(w),str(w/'test.c'),'-o',str(w/'test')],check=True)
    subprocess.run([str(w/'test')],check=True,timeout=20)
print('PASS selected shutdown patch chain; timeout/policy preserved; BSD authorization, MAC denial, copied reason, bounded unwind/context guard, and original return propagation')
