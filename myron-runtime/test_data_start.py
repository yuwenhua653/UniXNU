#!/usr/bin/env python3
"""Compile the actual transformed RamBlock start method with host API stubs."""
import argparse
from pathlib import Path
import os
import subprocess
import sys
import tempfile

p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True)
p.add_argument('--ramblock',type=Path,required=True);p.add_argument('--cxx',default='c++');a=p.parse_args()
sys.path.insert(0,str(a.device.resolve()))
from ram_data import prepare
text=prepare((a.ramblock/'NativeRamBlock.cpp').read_text())
start=text.index('bool NativeRamBlock::start(IOService *provider)')
end=text.index('\nIOReturn NativeRamBlock::doAsyncReadWrite',start)
body=text[start:end]
members=text[text.index('  IOLock *gate'):text.index('\n  bool available()')]
io=text[end:text.index('\nvoid NativeRamBlock::stop',end)]
fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <array>
#include <cstdio>
#include <vector>
#include "SparseDisk.h"
#include "SeedDisk.h"
#include "PersistOverlay.h"
#include "DirectDisk.h"
#include "MyronDataCapacity.h"
static unsigned fault,published,probes;
static uint64_t hashed;
static unsigned myronDataBootStage;
static bool myronDataFailed;
static uint32_t native_data_persist_state,native_data_persist_header,native_data_persist_gpt,native_data_persist_gpt_after;
static uint64_t native_data_persist_pages,native_data_persist_loaded,native_data_persist_writes,
 native_data_persist_syncs,native_data_persist_errors,native_data_persist_first_lba,native_data_persist_present;
static uint64_t native_ram_block_reads,native_ram_block_writes,native_ram_block_failures;
using IOLock=int;
static bool locked;
static void IOLockLock(IOLock*){assert(!locked);locked=true;}
static void IOLockUnlock(IOLock*){assert(locked);locked=false;}
static bool PE_parse_boot_argn(const char*,uint32_t*,size_t){return false;}
#define IOLog(...) ((void)0)
using UInt64=uint64_t;using IOReturn=int;
enum {kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnNotReady=2,kIOReturnIOError=3,kIOReturnNoMemory=4,kIODirectionIn=1,kIODirectionOut=2};
struct IOStorageAttributes{};
struct IOStorageCompletion {void (*action)(void*,void*,IOReturn,uint64_t);void *target,*parameter;};
struct IOMemoryDescriptor {
 uint8_t data[4096]={};
 unsigned getDirection(){return kIODirectionIn;}
 uint64_t getLength(){return sizeof(data);}
 uint64_t writeBytes(uint64_t at,const void *p,uint64_t n){assert(at+n<=sizeof(data));memcpy(data+at,p,n);return n;}
 uint64_t readBytes(uint64_t at,void *p,uint64_t n){assert(at+n<=sizeof(data));memcpy(p,data+at,n);return n;}
};
static uint64_t storePages;
static bool storeOpened;
static unsigned myron_data_store_mode(){return 2;}
static unsigned myron_data_store_gpt_check(){return fault==10;}
static int myron_data_store_open(uint64_t blocks,uint64_t *first,const char**){
 assert(!published && locked);if(fault==6)return 0;
 storePages=(fault==4?MyronDataSeedBytes:MyronDataGrownBytes)/4096;
 assert(blocks==persist::windowBlocks(storePages));*first=1234;storeOpened=true;return 1;
}
static int myron_data_store_read(uint64_t b,uint32_t n,void *p){
 assert(storeOpened && locked);if(fault==8)return 0;
 memset(p,0,n*4096);
 if(b==0){uint8_t hash[32];memset(hash,fault==9?0x43:0x42,32);persist::encodeHeader((uint8_t*)p,storePages,hash,1);}
 else if(b==1)((uint8_t*)p)[0]=1; // persisted page zero differs from immutable seed
 else if(b==persist::pageBlock(storePages,0))memset(p,0x79,n*4096);
 return 1;
}
static int myron_data_store_write(uint64_t,uint32_t,const void*){assert(false);return 0;}
static int myron_data_store_sync(){assert(false);return 0;}
static bool myronDataMayInitialize(const uint8_t*){return false;}
static bool myronDataCommitInitialization(){return fault!=11;}
struct SHA256_CTX {};
static void SHA256_Init(SHA256_CTX*){hashed=0;}
static void SHA256_Update(SHA256_CTX*,const void*,size_t n){hashed+=n;}
static void SHA256_Final(uint8_t *p,SHA256_CTX*){memset(p,0x42,32);}
// Hash bytes are stubbed; count/order must still be the original 1 GiB.
static std::array<uint8_t,32+16+4096> packedDisk;
static unsigned long gPhysBase=0x100000,gPhysSize=0x100000;
static void *ml_static_ptovirt(uint64_t){return packedDisk.data();}
static void *IOMallocZero(uint64_t n){
 if((fault==2 && n==8192)||(fault==3 && n==MyronDataGrownBytes/4096*sizeof(void*))||
    (fault==7 && n==128*4096))return nullptr;
 return calloc(1,n);
}
static void IOFree(void *p,uint64_t){free(p);}
static IOLock *IOLockAlloc(){static int lock;return &lock;}
struct IOService {};
struct IOBlockStorageDevice { bool start(IOService*){return true;} };
struct OSData {
 uint64_t range[2]={0x100000,packedDisk.size()};
 unsigned getLength(){return 16;}
 const void *getBytesNoCopy(){return range;}
};
static int gIODTPlane;
struct IORegistryEntry {
 static IORegistryEntry *fromPath(const char *,int){static IORegistryEntry map;return &map;}
 OSData *getProperty(const char *key){static OSData range;return !strcmp(key,"PackedRAMDisk")?&range:nullptr;}
 void release(){}
};
#define OSDynamicCast(type,p) static_cast<type*>(p)
static uint8_t native_ram_block_seed_sha256[32];
static uint64_t native_ram_block_bytes,native_ram_block_resident_bytes;
static unsigned native_ram_block_sparse,native_ram_block_ready;
static bool myronDataProbeCapacity(const uint8_t hash[32],uint64_t old,uint8_t *,uint64_t *selected){
 ++probes;assert(hashed==MyronDataSeedBytes && old==MyronDataSeedBytes);
 for(unsigned i=0;i<32;++i)assert(hash[i]==0x42);
 if(fault==1)return false;
 *selected=fault==4?MyronDataSeedBytes:MyronDataGrownBytes;return true;
}
struct NativeRamBlock:IOBlockStorageDevice {
/* ACTUAL_MEMBERS_AND_ATTACH */
 bool start(IOService*);
 IOReturn doAsyncReadWrite(IOMemoryDescriptor*,UInt64,UInt64,IOStorageAttributes*,IOStorageCompletion*);
 bool setProperty(const char *name,uint64_t bytes,unsigned bits){
  assert(!strcmp(name,"myron-data-grown-bytes") && bytes==MyronDataGrownBytes && bits==64);
  return fault!=5;
 }
 void registerService(){
  ++published;assert(online && native_ram_block_ready && probes);
  IOMemoryDescriptor first;bool completed=false;
  IOStorageCompletion c={[](void *p,void*,IOReturn status,uint64_t bytes){assert(!status && bytes==4096);*(bool*)p=true;},&completed,nullptr};
  assert(doAsyncReadWrite(&first,0,8,nullptr,&c)==kIOReturnSuccess && completed);
  for(uint8_t value:first.data)assert(value==0x79); // Never cached seed zeroes.
 }
 ~NativeRamBlock(){
  if(sparse.pages){for(uint64_t i=0;i<sparse.bytes/4096;++i)free(sparse.pages[i]);free(sparse.pages);}
  free(overlayBits);free(stage);
 }
};
''' + body + io + r'''
int main(){
 assert(!myronDataFailed);
 memcpy(packedDisk.data(),"DBRDISK1",8);uint32_t version=1,block=4096;
 uint64_t bytes=MyronDataSeedBytes,count=1,at=bytes-4096,len=4096;
 memcpy(packedDisk.data()+8,&version,4);memcpy(packedDisk.data()+12,&block,4);
 memcpy(packedDisk.data()+16,&bytes,8);memcpy(packedDisk.data()+24,&count,8);
 memcpy(packedDisk.data()+32,&at,8);memcpy(packedDisk.data()+40,&len,8);
 memset(packedDisk.data()+48,0x53,4096);
 for(fault=0;fault<=11;++fault){
  published=probes=native_ram_block_ready=myronDataBootStage=0;hashed=0;storeOpened=false;locked=false;
  NativeRamBlock disk;IOService parent;
  bool ok=disk.start(&parent);assert(ok==(fault==0 || fault==4));
  assert(published==(ok?1u:0u) && native_ram_block_ready==(ok?1u:0u));
  if(ok){
   uint64_t expected=fault==4?MyronDataSeedBytes:MyronDataGrownBytes;
   assert(disk.capacity*512==expected && native_ram_block_bytes==expected);
   assert(native_ram_block_sparse==1 && native_ram_block_resident_bytes==4096 && !disk.memory);
   assert(disk.sparse.find(MyronDataSeedBytes/4096-1)[0]==0x53);
   if(fault==0)assert(!disk.sparse.find(MyronDataGrownBytes/4096-1));
   for(unsigned i=0;i<32;++i)assert(native_ram_block_seed_sha256[i]==0x42);
  }
 }
}
'''
fixture=fixture.replace('/* ACTUAL_MEMBERS_AND_ATTACH */',members)
with tempfile.TemporaryDirectory(prefix='myron-data-start-') as tmp:
    src=Path(tmp)/'start.cpp';out=Path(tmp)/'start';src.write_text(fixture)
    subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        '-fno-sanitize-recover=all','-I',str(a.ramblock.resolve()),'-I',str(Path(__file__).resolve().parent),
        '-I',str(a.device.resolve().parent/'sm8850/drivers/NativeUfs'),str(src),'-o',str(out)],check=True)
    subprocess.run([out],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
    # Negative control: reproduce the old publication order in the same real
    # start/read path. The first media read must expose seed zeroes and fail
    # the persisted-byte assertion; a test that only checks flags is inadequate.
    old=fixture.index('  myronDataBootStage=1;')
    end=fixture.index('  online = true;',old)
    src.write_text(fixture[:old]+fixture[end:])
    subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        '-fno-sanitize-recover=all','-I',str(a.ramblock.resolve()),'-I',str(Path(__file__).resolve().parent),
        '-I',str(a.device.resolve().parent/'sm8850/drivers/NativeUfs'),str(src),'-o',str(out)],check=True)
    result=subprocess.run([out],capture_output=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
    assert result.returncode!=0 and b'value==0x79' in result.stderr,result.stderr.decode()
print('PASS: actual RamBlock start/attach/read: first published read uses persisted metadata at 1/16 GiB; 10 failure cases never publish')
print('PASS negative control: old publication order reads stale seed metadata and fails the first-read assertion')
