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
fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <array>
#include "SparseDisk.h"
#include "SeedDisk.h"
#include "MyronDataCapacity.h"
static unsigned fault,published,probes;
static uint64_t hashed;
struct SHA256_CTX {};
static void SHA256_Init(SHA256_CTX*){hashed=0;}
static void SHA256_Update(SHA256_CTX*,const void*,size_t n){hashed+=n;}
static void SHA256_Final(uint8_t *p,SHA256_CTX*){memset(p,0x42,32);}
// Hash bytes are stubbed; count/order must still be the original 1 GiB.
static std::array<uint8_t,32+16+4096> packedDisk;
static unsigned long gPhysBase=0x100000,gPhysSize=0x100000;
static void *ml_static_ptovirt(uint64_t){return packedDisk.data();}
static void *IOMallocZero(uint64_t n){
 if((fault==2 && n==8192)||(fault==3 && n==8*1024*1024))return nullptr;
 return calloc(1,n);
}
static void IOFree(void *p,uint64_t){free(p);}
static void *IOLockAlloc(){static int lock;return &lock;}
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
 uint8_t *memory=nullptr;void *gate=nullptr;uint64_t capacity=0;
 RamSparseDisk sparse={};SeedDisk big={};bool isBig=false,online=false;uint8_t seedHash[32]={};
 bool start(IOService*);
 void registerService(){++published;assert(online && native_ram_block_ready && probes);}
 ~NativeRamBlock(){
  if(sparse.pages){for(uint64_t i=0;i<sparse.bytes/4096;++i)free(sparse.pages[i]);free(sparse.pages);}
 }
};
''' + body + r'''
int main(){
 memcpy(packedDisk.data(),"DBRDISK1",8);uint32_t version=1,block=4096;
 uint64_t bytes=MyronDataSeedBytes,count=1,at=bytes-4096,len=4096;
 memcpy(packedDisk.data()+8,&version,4);memcpy(packedDisk.data()+12,&block,4);
 memcpy(packedDisk.data()+16,&bytes,8);memcpy(packedDisk.data()+24,&count,8);
 memcpy(packedDisk.data()+32,&at,8);memcpy(packedDisk.data()+40,&len,8);
 memset(packedDisk.data()+48,0x53,4096);
 for(fault=0;fault<=4;++fault){
  published=probes=native_ram_block_ready=0;hashed=0;
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
with tempfile.TemporaryDirectory(prefix='myron-data-start-') as tmp:
    src=Path(tmp)/'start.cpp';out=Path(tmp)/'start';src.write_text(fixture)
    subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        '-fno-sanitize-recover=all','-I',str(a.ramblock.resolve()),'-I',str(Path(__file__).resolve().parent),
        '-I',str(a.device.resolve().parent/'sm8850/drivers/NativeUfs'),str(src),'-o',str(out)],check=True)
    subprocess.run([out],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
print('PASS: actual RamBlock start, original seed hashing, 1/4 GiB publication and allocation/probe failure refusal')
