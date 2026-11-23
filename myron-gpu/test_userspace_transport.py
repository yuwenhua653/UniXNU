#!/usr/bin/env python3
"""Exercise the actual staged kernel poller and Metal mailbox methods together.

The fixture supplies scheduling/IOKit peers, not GPU execution. Test full-size
submits, reply bounds, timeout quarantine and connection replacement.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'native'))
from prepare_sources import stage


def check(tree, references, cxx):
    with tempfile.TemporaryDirectory(prefix='myron-mailbox-') as temp:
        out=Path(temp)
        stage(references,out/'kernel')
        source=(out/'kernel/NativeAdreno/NativeAdrenoPublish.cpp').read_text()
        kernel=source[source.index('void nativeAdrenoMailboxPoller(void *,wait_result_t)\n{'):source.index('/* The client log row')]
        kernel=kernel.replace('__asm__ volatile("dmb sy" ::: "memory");','__atomic_thread_fence(__ATOMIC_SEQ_CST);')
        source=(tree/'drivers/AdrenoMetal/NativeAdrenoUserTest.h').read_text()
        client=source[source.index('using IOServiceOpenFn'):source.index('\nvoid report(')]
        fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <pthread.h>
#include "MyronGpuMailbox.h"
using IOReturn=int;using wait_result_t=int;
constexpr int kIOReturnBadArgument=-10;
struct AGXDeviceUserClient {
 int refs=1;void *mailbox_task_=this;void retain(){++refs;}void release(){--refs;}
 IOReturn run(uint32_t,const void *,size_t,void *,size_t,void *);
};
struct {void *lock;} g;
void IOLockLock(void *){} void IOLockUnlock(void *){}
void *current_thread(){return nullptr;} void thread_set_thread_name(void *,const char *){}
unsigned mach_task_self(){return 0;}
struct {unsigned mb_calls;} native_adreno_metal_diag;
alignas(4096) uint32_t page[1024];
volatile uint32_t *gMailboxWords=page;
AGXDeviceUserClient first,second,*gMailboxOwner=&first;
struct Stop{};int sleeps;
void IOSleep(unsigned){if(++sleeps>1)throw Stop{};}
unsigned calls=0,mode=0;bool stalled=false;
unsigned unmaps=0;
NativeAdrenoAbiSubmit expected{};
IOReturn AGXDeviceUserClient::run(uint32_t method,const void *input,size_t is,void *output,size_t os,void *task){
 auto *owner=this;assert(task==mailbox_task_);
 ++calls;assert(owner==&first && owner->refs==2);
 assert(method==NativeAdrenoMethodSubmit && is==sizeof expected);
 assert(memcmp(input,&expected,is)==0);
 if(mode==1)return -12;
 if(mode==2){gMailboxOwner=&second;memset(page,0,sizeof page);page[0]=MyronMailboxMagic;return 0;}
 assert(os==sizeof(NativeAdrenoAbiSubmitReply));
 NativeAdrenoAbiSubmitReply reply{};reply.fence=0x12345678;memcpy(output,&reply,os);return 0;
}
'''
        fixture+=kernel+r'''
void poll(){sleeps=0;try{nativeAdrenoMailboxPoller(nullptr,0);}catch(const Stop &){} }
int usleep(unsigned){if(!stalled)poll();return 0;}
'''+client+r'''
int main(){
 Gpu opening;
 opening.map=[](unsigned,uint32_t,unsigned,uint64_t *address,uint64_t *length,uint32_t)->int{
  *address=reinterpret_cast<uint64_t>(page);*length=sizeof page;return 0;
 };
 opening.unmap=[](unsigned,uint32_t,unsigned,uint64_t)->int{++unmaps;return 0;};
 page[0]=0x4d41494c;assert(!opening.openMailbox() && !opening.mailbox && unmaps==1);
 page[0]=MyronMailboxMagic;assert(opening.openMailbox() && opening.mailbox==page);
 page[0]=MyronMailboxMagic;Gpu gpu;gpu.mailbox=page;
 expected.buffer_count=128;
 for(unsigned i=0;i<128;++i)expected.buffers[i]={0x11110000ull+i,0x40000000ull+i*4096,4096};
 struct {NativeAdrenoAbiSubmitReply reply;uint64_t canary;} output{};
 output.canary=0xfeedbabedeadcafeull;
 assert(gpu.method(NativeAdrenoMethodSubmit,&expected,sizeof expected,&output.reply,sizeof output.reply)==0);
 assert(output.reply.fence==0x12345678 && output.canary==0xfeedbabedeadcafeull);
 assert(calls==1 && first.refs==1 && page[1]==page[2]);
 uint32_t seq=page[1];
 assert(gpu.method(NativeAdrenoMethodSubmit,&expected,sizeof expected+1,nullptr,0)==-1 && page[1]==seq);
 assert(gpu.method(NativeAdrenoMethodSubmit,nullptr,0,&output,MyronMailboxOutputBytes+1)==-1 && page[1]==seq);
 mode=1;output.reply.fence=99;
 assert(gpu.method(NativeAdrenoMethodSubmit,&expected,sizeof expected,&output.reply,sizeof output.reply)==-12);
 assert(output.reply.fence==99);
 mode=0;gpu.mailboxSeq=0xffffffffu;
 assert(gpu.method(NativeAdrenoMethodSubmit,&expected,sizeof expected,&output.reply,sizeof output.reply)==0 && page[1]==1);
 stalled=true;
 assert(gpu.method(NativeAdrenoMethodSubmit,&expected,sizeof expected,&output.reply,sizeof output.reply)==-2);
 seq=page[1];const unsigned before=calls;
 assert(gpu.method(NativeAdrenoMethodSubmit,&expected,sizeof expected,&output.reply,sizeof output.reply)==-1 && page[1]==seq);
 stalled=false;poll();assert(page[2]==seq && calls==before+1);
 assert(gpu.method(NativeAdrenoMethodSubmit,&expected,sizeof expected,&output.reply,sizeof output.reply)==-1 && page[1]==seq);
 // An in-flight close/reopen cannot acknowledge the replaced connection.
 mode=2;memcpy(reinterpret_cast<uint8_t *>(page)+MyronMailboxInputOffset,&expected,sizeof expected);
 page[1]=77;page[2]=76;page[3]=NativeAdrenoMethodSubmit;page[5]=sizeof expected;page[6]=sizeof output.reply;
 poll();assert(gMailboxOwner==&second && !page[2] && first.refs==1);
 // Malformed userspace sizes are rejected by the kernel too, without copying.
 gMailboxOwner=&first;page[1]=88;page[3]=NativeAdrenoMethodSubmit;page[5]=MyronMailboxInputBytes+1;page[6]=0;
 unsigned old=calls;poll();assert(calls==old && page[2]==88 && int(page[4])==kIOReturnBadArgument);
 return 0;
}
'''
        (out/'test.cpp').write_text(fixture)
        subprocess.run([cxx,'-std=c++17','-Wall','-Wextra','-Werror','-Wunused-const-variable','-pthread',
                        '-I',str(tree/'drivers/NativeAdreno'),str(out/'test.cpp'),'-o',str(out/'test')],check=True)
        subprocess.run([str(out/'test')],check=True)
    print('PASS: actual kernel/Metal transport, 128 IBs, bounds, error replies, timeout quarantine and reopen')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tree',type=Path,required=True)
    p.add_argument('--references',type=Path,required=True);p.add_argument('--cxx',default='c++')
    a=p.parse_args();check(a.tree.resolve(),a.references.resolve(),a.cxx)
