#!/usr/bin/env python3
"""Apply the selected series and execute the actual Lockdown Mode source."""
import argparse
import os
import signal
from pathlib import Path
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
for name in ('device','upstream','xnu'):p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--cc',default='clang')
a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',
           os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subject='bsd/kern/lockdown_mode.c'
with tempfile.TemporaryDirectory() as tmp:
    w=Path(tmp);target=w/subject;target.parent.mkdir(parents=True)
    shutil.copyfile(a.xnu/subject,target);before=target.read_text();applied=[]
    for scope in ('arch','os','device'):
        series=roots[scope]/'patches/xnu/series'
        for line in series.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            prefix,sep,tail=line.partition(':')
            patch=(roots[prefix]/tail if sep else series.parent/line).resolve()
            if '+++ b/'+subject not in patch.read_text():continue
            subprocess.run(['git','apply','--include='+subject,str(patch)],cwd=w,check=True)
            applied.append(patch.name)
    assert applied==['myron-lockdown-public-state.patch'],applied
    after=target.read_text()
    start=after.index('/*\n * Darwin 26 clients query')
    end=after.index('int\nget_lockdown_mode_state(void)',start)
    assert after[:start]+after[end:]==before,'Existing state/init/NVRAM behavior changed'
    # The real private header supplies the accessor prototype; no fake task layout.
    (w/'sys').mkdir();shutil.copyfile(a.xnu/'bsd/sys/lockdown_mode.h',w/'sys/lockdown_mode.h')
    shim=r'''
#ifndef SHIM_H
#define SHIM_H
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#define KERNEL_PRIVATE 1
#define XNU_KERNEL_PRIVATE 1
#define XNU_TARGET_OS_XR 0
#define __startup_func
#define LCK_GRP_DECLARE(n,s) int n
#define LCK_MTX_DECLARE(n,g) int n
#define STARTUP(...)
#define kIOKitSystemGUID "test"
#define TRUE 1
typedef int boolean_t;
typedef int kern_return_t;
typedef void *thread_t;
typedef void (*thread_continue_t)(void);
#define KERN_SUCCESS 0
int kernel_thread_start(thread_continue_t,void *,thread_t *);
void thread_deallocate(thread_t);
void panic(const char *);
void lck_mtx_lock(int *);
void lck_mtx_unlock(int *);
int msleep(void *,int *,int,const char *,void *);
void wakeup(void *);
int PEReadNVRAMBooleanProperty(const char *,int *);
void PEWriteNVRAMBooleanProperty(const char *,int);
void PERemoveNVRAMProperty(const char *);
struct sysctl_oid { int unused; };
struct sysctl_req { void *oldptr; size_t oldlen,oldidx; int fail; };
#define SYSCTL_HANDLER_ARGS (struct sysctl_oid *oidp,void *arg1,int arg2,struct sysctl_req *req)
#define CTLTYPE_INT 2
#define CTLFLAG_RD 0x80000000U
#define CTLFLAG_WR 0x40000000U
#define CTLFLAG_LOCKED 0x00800000U
#define OID_AUTO (-1)
#define SYSCTL_DECL(...)
#define SYSCTL_INT(...)
struct registration { const char *parent,*name; unsigned flags; int (*handler) SYSCTL_HANDLER_ARGS; };
#define SYSCTL_PROC(parent,nbr,name,access,ptr,arg,handler,fmt,descr) \
 static const struct registration record={#parent,#name,access,handler}
int output(struct sysctl_req *,const void *,size_t);
#define SYSCTL_OUT(req,p,n) output(req,p,n)
#endif
'''
    (w/'shim.h').write_text(shim)
    for path in ('libkern/libkern.h','sys/sysctl.h','IOKit/IOPlatformExpert.h','IOKit/IOKitKeysPrivate.h'):
        header=w/path;header.parent.mkdir(exist_ok=True);header.write_text('#include "shim.h"\n')
    harness=r'''
#include "bsd/kern/lockdown_mode.c"
static int locked,waits,writes,nvram;
void lck_mtx_lock(int *p){(void)p;assert(!locked);locked=1;}
void lck_mtx_unlock(int *p){(void)p;assert(locked);locked=0;}
int msleep(void *p,int *m,int f,const char *s,void *t){
 (void)m;(void)f;(void)s;(void)t;assert(locked);assert(p==&lockdown_mode_init_done);
 waits++;lockdown_mode_init_done=1;return 0;
}
void wakeup(void *p){assert(p==&lockdown_mode_init_done);assert(locked);}
int PEReadNVRAMBooleanProperty(const char *s,int *v){(void)s;*v=nvram;return 1;}
void PEWriteNVRAMBooleanProperty(const char *s,int v){(void)s;writes++;nvram=v;}
void PERemoveNVRAMProperty(const char *s){(void)s;writes++;nvram=0;}
int kernel_thread_start(thread_continue_t c,void *p,thread_t *t){(void)c;(void)p;*t=0;return 0;}
void thread_deallocate(thread_t t){(void)t;}
void panic(const char *s){(void)s;assert(0);}
boolean_t IOServiceWaitForMatchingResource(const char *s,uint64_t n){(void)s;(void)n;return 1;}
int output(struct sysctl_req *r,const void *p,size_t n){
 assert(n==sizeof(int));r->oldidx=n;
 if(r->fail)return r->fail;
 if(!r->oldptr)return 0;
 if(r->oldlen<n)return ENOMEM;
 memcpy(r->oldptr,p,n);return 0;
}
static int read_state(struct sysctl_req *r){return record.handler(NULL,NULL,0,r);}
int main(void){
 assert(!strcmp(record.parent,"_security_mac"));
 assert(!strcmp(record.name,"lockdown_mode_state_public"));
 assert(record.flags==(CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED));
 assert(!(record.flags&CTLFLAG_WR));
 struct {unsigned before;int value;unsigned after;} out={0xaabbccdd,-1,0x11223344};
 struct sysctl_req r={&out.value,sizeof(int),0,0};
 nvram=1;lockdown_mode_init();assert(read_state(&r)==0&&out.value==1);
 assert(r.oldidx==sizeof(int)&&!locked&&writes==0);
 disable_lockdown_mode();assert(read_state(&r)==0&&out.value==0&&writes==1);
 enable_lockdown_mode();assert(read_state(&r)==0&&out.value==1&&writes==2);
 lockdown_mode_init_done=0;assert(read_state(&r)==0&&out.value==1&&waits==1&&!locked);
 r.oldptr=NULL;assert(read_state(&r)==0&&r.oldidx==sizeof(int));
 r.oldptr=&out.value;r.oldlen=sizeof(int)-1;assert(read_state(&r)==ENOMEM);
 r.oldlen=sizeof(int);r.fail=EFAULT;assert(read_state(&r)==EFAULT);
 assert(out.before==0xaabbccdd&&out.after==0x11223344&&writes==2);
 return 0;
}
'''
    (w/'test.c').write_text(harness)
    command=[a.cc,'-std=c11','-Werror=implicit-function-declaration','-Wno-unknown-pragmas',
             '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(w),str(w/'test.c'),'-o',str(w/'test')]
    environment=dict(os.environ,ASAN_OPTIONS='detect_leaks=0')
    subprocess.run(command,check=True);subprocess.run([str(w/'test')],check=True,env=environment,timeout=20)
    # The same harness must detect a stub that always reports disabled.
    target.write_text(after.replace('int state = get_lockdown_mode_state();','int state = 0;'))
    subprocess.run(command,check=True)
    rejected=subprocess.run([str(w/'test')],capture_output=True,env=environment,timeout=20)
    assert rejected.returncode==-signal.SIGABRT and b'out.value==1' in rejected.stderr,'Constant-off negative control did not reach the expected assertion'
print('PASS real patch chain, original state/init preserved, readonly registration, enabled/disabled state, wait, length/error propagation, bounds; constant-off rejected')
