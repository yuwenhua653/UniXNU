#!/usr/bin/env python3
"""Execute the staged NativeUfsBlock callback with faults and nested completion."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import os
p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True);p.add_argument('--cxx',default='c++');a=p.parse_args()
sys.path.insert(0,str(a.device.resolve()))
from prepare_ufs_transport import patch_driver
upstream=a.device.parent/'sm8850/drivers/NativeUfs/upstream'
text=patch_driver((upstream/'NativeUfs.cpp').read_bytes()).decode()
start=text.index('IOReturn NativeUfsBlock::doAsyncReadWrite (')
end=text.index('\nvoid NativeUfsBlock::free ()',start)
function=text[start:end]
prefix=r'''
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cassert>
#include <mutex>
#include <vector>
using UInt64=uint64_t;
using IOReturn=uint32_t;
constexpr IOReturn kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnIOError=2,
 kIOReturnNotPrivileged=3,kIOReturnNotWritable=4,kIOReturnNotReady=5;
constexpr unsigned kIODirectionIn=1,kDataMax=131072;
struct IOStorageAttributes{};
struct IOLock {std::mutex m;bool held=false;};
void IOLockLock(IOLock *l){l->m.lock();l->held=true;}
void IOLockUnlock(IOLock *l){l->held=false;l->m.unlock();}
struct vr_view{};
static int fault;
static int vr_xnu_crypto;
constexpr int VR_OK=0;
int vr_verify_block(const vr_view *,uint64_t,const void *,size_t,const int *){return fault==2?1:0;}
uint64_t timerTicks(){static uint64_t t;return ++t;}
volatile uint64_t native_ufs_read_ticks,native_ufs_verify_ticks,native_ufs_verified_blocks,
 native_ufs_block_reads,native_ufs_block_failures;
volatile uint32_t native_ufs_integrity_failures;
struct {const char *stage;uint32_t verify,result;} gRootDiagnostic;
void rootDiagnosticFailure(const char *){}
static unsigned events,completions;
void event(unsigned s,const char *p,const char *n,uint64_t,uint64_t){assert((s==2||s==4)&&p&&n);++events;}
#define MYRON_UFS_EVENT(s,p,n,a,b) event(s,p,n,a,b)
#define NATIVE_VERIFIED_BLOCK 1
IOReturn hostRead4k(unsigned,uint64_t,uint32_t n,void *dst){if(fault==1)return kIOReturnIOError;memset(dst,0x5a,n*4096);return 0;}
struct IOMemoryDescriptor {
 uint8_t data[8192];unsigned direction=kIODirectionIn;
 uint64_t getLength(){return sizeof(data);}
 unsigned getDirection(){return direction;}
 uint64_t writeBytes(uint64_t offset,const void *p,uint64_t n){assert(offset+n<=sizeof(data));
  if(fault==3)--n;memcpy(data+offset,p,n);return n;}
};
struct IOStorageCompletion {void(*action)(void*,void*,IOReturn,uint64_t);void *target,*parameter;};
#include "RootWindowRead.h"
class NativeUfsBlock {
public:
 uint64_t absolute=4096,bytes=16384;
 uint8_t bounce[kDataMax];const char *label="OS";
 IOLock mutex;IOLock *windowLock=&mutex;bool online=true;vr_view verified;
 IOReturn doAsyncReadWrite(IOMemoryDescriptor*,UInt64,UInt64,IOStorageAttributes*,IOStorageCompletion*);
};
'''
suffix=r'''
struct Context {NativeUfsBlock *dev;bool nested;IOReturn want;uint64_t done;};
void completed(void *target,void *,IOReturn status,uint64_t bytes) {
 auto *c=static_cast<Context *>(target);assert(!c->dev->mutex.held);
 assert(status==c->want && bytes==c->done);++completions;
 if(c->nested){Context child{c->dev,false,0,4096};IOMemoryDescriptor buf{};
  IOStorageCompletion cb{completed,&child,nullptr};
  assert(c->dev->doAsyncReadWrite(&buf,8,8,nullptr,&cb)==0);
  for(auto v:buf.data)assert(v==0x5a || v==0);
 }
}
int main(){
 NativeUfsBlock dev;
 for(fault=0;fault<4;fault++){
  IOMemoryDescriptor buf{};Context ctx{&dev,fault==0,
   fault==0?0u:fault==2?kIOReturnNotPrivileged:kIOReturnIOError,
   fault==0?4096u:fault==3?4095u:0u};IOStorageCompletion cb{completed,&ctx,nullptr};
  unsigned before=completions;
  assert(dev.doAsyncReadWrite(&buf,0,8,nullptr,&cb)==0);
  assert(completions-before==(fault==0?2u:1u));assert(!dev.mutex.held);
  if(fault==2)for(auto v:buf.data)assert(v==0); // Never copy failed integrity blocks.
 }
 unsigned before=completions;IOMemoryDescriptor buf{};Context ctx{&dev,false,0,0};IOStorageCompletion cb{completed,&ctx,nullptr};
 assert(dev.doAsyncReadWrite(&buf,32,8,nullptr,&cb)==kIOReturnBadArgument);
 buf.direction=2;assert(dev.doAsyncReadWrite(&buf,0,8,nullptr,&cb)==kIOReturnNotWritable);
 assert(completions==before && events>0 && native_ufs_integrity_failures==1);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    (root/'RootWindowRead.h').write_bytes((upstream/'RootWindowRead.h').read_bytes())
    (root/'test.cpp').write_text(prefix+function+suffix)
    subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-pthread',str(root/'test.cpp'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'),timeout=10)
print('PASS staged UFS request: callback outside lock, nested read, read/integrity/short-copy errors, rejected writes')
