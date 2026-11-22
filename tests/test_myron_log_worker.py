#!/usr/bin/env python3
"""Run the actual board worker with stub hardware; never substitutes its guards."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True);p.add_argument('--cc',default='c++');a=p.parse_args()
ufs=a.device.resolve().parent/'sm8850/drivers/NativeUfs'
with tempfile.TemporaryDirectory() as tmp:
 t=Path(tmp);(t/'sys').mkdir();(t/'sys/msgbuf.h').write_text('''#define MSG_MAGIC 0x063061
#define MAX_MSG_BSIZE (1024*1024)
struct msgbuf {int msg_magic,msg_size,msg_bufx,msg_bufr;char *msg_bufc;};
extern "C" struct msgbuf *msgbufp;
''')
 text=(ufs/'MyronBootLog.h').read_text()
 old='__asm__ volatile("mrs %0, cntfrq_el0":"=r"(hz));';assert text.count(old)==1
 text=text.replace(old,'hz=1000;');(t/'worker.h').write_text(text)
 source=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <string>
#include "MyronBootLogCore.h"
struct Stop{};
using wait_result_t=int;using thread_t=void *;
#define THREAD_NULL nullptr
#define KERN_SUCCESS 0
#define kIOReturnSuccess 0
#define MYRON_ROOT_POLICY 1
static int displaySnapshots,keystoreSnapshots;
extern "C" void boot_process_start(){}
extern "C" size_t myron_process_snapshot(char *p,size_t n){assert(n==24576);strcpy(p,"process snapshot\n");return strlen(p);}
static int scenario,writes,syncs,locked,sleeps,gptCalls;static unsigned logArg;
static constexpr unsigned kDataMax=131072;
static int transportLock;
static struct {bool ready,poisoned;void *lock;} gHost;
static void IOLockLock(void *){assert(!transportLock);transportLock=1;}
static void IOLockUnlock(void *){assert(transportLock);transportLock=0;}
static struct {bool valid;uint64_t imageBytes,first,last;} gStoreGeometry;
static unsigned myron_root_start_ready;
static bool gStoreOpen,gLogOpen;
static uint64_t allowedFirst,allowedBlocks;
static MyronRootGeometry myron_root_geometry={256,65791,66047,264241152ULL,3616768,1024};
static unsigned storeMode(){return scenario==4;}
static unsigned logMode(){return scenario==5;}
static uint64_t reserveBlocks(){return 1024;}
static unsigned native_ufs_store_gpt_check(){++gptCalls;return scenario==6;}
static bool hostLogOpen(uint64_t first,uint64_t blocks){assert(!gLogOpen && transportLock);allowedFirst=first;allowedBlocks=blocks;gLogOpen=true;return true;}
static int hostWrite4k(unsigned lun,uint64_t first,uint32_t n,const void *p) {
 assert(!locked && lun==0 && p && first>=allowedFirst && first+n<=allowedFirst+allowedBlocks);
 ++writes;return scenario==7 ? -1 : 0;
}
static int hostSyncCache(){assert(!locked);++syncs;return 0;}
static void *IOMallocAligned(size_t bytes,size_t align){void *p=nullptr;assert(!posix_memalign(&p,align,bytes));return p;}
static void IOFreeAligned(void *p,size_t){free(p);}
static void thread_set_thread_name(void *,const char *){}
static void *current_thread(){return nullptr;}
static uint64_t timerTicks(){return 0x1234;}
static int kernel_thread_start(void (*f)(void *,wait_result_t),void *arg,thread_t *thread){*thread=(void*)1;f(arg,0);return 0;}
static void thread_deallocate(thread_t){}
static void IOSleep(unsigned ms){assert(ms==2000);++sleeps;gHost.ready=false;}
static bool PE_parse_boot_argn(const char *key,void *v,unsigned n){assert(std::string(key)=="log"&&n==4);*(unsigned*)v=logArg;return true;}
extern "C" size_t myron_display_snapshot(char *p,size_t n){++displaySnapshots;assert(n==1024);memset(p,'x',n-1);p[n-1]=0;return n-1;}
extern "C" size_t myron_touch_snapshot(char *p,size_t n){assert(n==256);strcpy(p,"touch snapshot\n");return strlen(p);}
extern "C" size_t myron_keystore_snapshot(char *p,size_t n){++keystoreSnapshots;assert(n==1024&&displaySnapshots==keystoreSnapshots);strcpy(p,"keystore snapshot\n");return strlen(p);}
extern "C" size_t myron_boot_log_snapshot(char *p,size_t n){assert(!locked&&n>12);strcpy(p,"test snapshot");return strlen(p);}
extern "C" void bsd_log_lock_safe(){assert(!locked);locked=1;}
extern "C" void bsd_log_unlock(){assert(locked);locked=0;}
#include "worker.h"
extern "C" {struct msgbuf *msgbufp;}
int main() {
 char ring[]="message ring";struct msgbuf m={MSG_MAGIC,(int)sizeof ring,0,0,ring};msgbufp=&m;
 for(scenario=0;scenario<=8;++scenario) {
  gHost={true,false,nullptr};gStoreGeometry={true,67108864ULL,256,65791};
  myron_root_start_ready=1;gStoreOpen=gLogOpen=false;myronLogStarted=0;myronLogFirst=0;
  myron_log_state=myron_log_rounds=myron_log_errors=0;writes=syncs=sleeps=gptCalls=0;logArg=1;
  if(scenario==1)myron_root_start_ready=0;
  if(scenario==2)gHost.poisoned=true;
  if(scenario==3)gStoreGeometry.first++;
  if(scenario==8)logArg=0;
  myronBootLogStart();
  if(scenario==0)assert(myron_log_rounds==1&&writes==34&&syncs==2&&sleeps==1&&gLogOpen&&displaySnapshots==1&&keystoreSnapshots==1);
  else if(scenario==7)assert(myron_log_errors==1&&writes==1&&syncs==0&&myron_log_rounds==0);
  else assert(writes==0&&syncs==0&&!gLogOpen);
  if(scenario!=8)assert(myron_log_state==3);
 }
 // Source ring copying is protected, bounded, ordered, and does not retain NULs.
 uint8_t out[32*4096];m.msg_bufx=4;
 assert(myronLogMessages(out)==strlen(ring));assert(!memcmp(out,"age ringmess",12));
 m.msg_size=MAX_MSG_BSIZE+1;assert(myronLogMessages(out)==0&&!locked);
}
'''
 (t/'test.cpp').write_text(source)
 subprocess.run([a.cc,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(t),'-I',str(ufs),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
 print('PASS actual worker: root/geometry/mode/GPT/transport guards, bounded writes, stop-on-error, locked msgbuf copy')
