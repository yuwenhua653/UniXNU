// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include "MyronDataWindow.h"
static MyronRootGeometry myron_root_geometry={4096,8392703,8400000,31ULL<<30,4ULL<<20,262144};
static struct {bool valid;uint64_t imageBytes,first,last;} gStoreGeometry={true,16ULL<<30,4096,8392703};
static struct {bool ready,poisoned;void *lock;} gHost={true,false,nullptr};
static unsigned myron_root_start_ready=1,gptError=0,legacyMode=0;
static unsigned commands=0,syncs=0;static bool locked=false,failWrite=false,opened=false;
static uint64_t windowFirst,windowBlocks;
constexpr unsigned kDataMax=131072,kIOReturnSuccess=0;
static unsigned storeMode(){return legacyMode;}static unsigned logMode(){return 0;}
static const char *rootPartitionName(){return "unixnu";}
static uint64_t reserveBlocks(){return 262144;}
static unsigned native_ufs_store_gpt_check(){return gptError;}
static void IOLockLock(void*){assert(!locked);locked=true;}
static void IOLockUnlock(void*){assert(locked);locked=false;}
static bool hostStoreOpen(uint64_t f,uint64_t n){assert(locked);if(opened)return false;opened=true;windowFirst=f;windowBlocks=n;return true;}
static int hostRead4k(unsigned lun,uint64_t f,uint32_t n,void *out){assert(!locked && lun==0 && f>=windowFirst && f+n<=windowFirst+windowBlocks);memset(out,0,n*4096);++commands;return 0;}
static int hostWrite4k(unsigned lun,uint64_t f,uint32_t n,const void *,bool fua){assert(!locked && fua && lun==0 && f>=windowFirst && f+n<=windowFirst+windowBlocks);++commands;return failWrite?1:0;}
static int hostSyncCache(){assert(!locked);++syncs;return 0;}
static void PE_parse_boot_argn(const char *,unsigned *v,size_t){*v=0;}
static void *IOMallocZero(size_t n){return calloc(1,n);}
static void IOFree(void *p,size_t){free(p);}
#include "MyronDataStore.h"
int main(){
 uint64_t first=0;const char *why=nullptr;
 assert(!myronDataProbeCapacity(nullptr,0,nullptr,&first));
 legacyMode=2;assert(!myron_data_store_open(262153,&first,&why)&&!opened);legacyMode=0;
 gptError=1;assert(!myron_data_store_open(262153,&first,&why)&&!opened);gptError=0;
 assert(myronDataFailed);myronDataFailed=false; // simulate a new boot
 assert(myron_data_store_open(262153,&first,&why)&&opened);
 assert(!myron_data_store_open(262153,&first,&why));
 uint8_t hdr[4096]={};assert(myronDataMayInitialize(hdr));memcpy(hdr,"SHNGDATA",8);assert(!myronDataMayInitialize(hdr));
 assert(myronDataCommitInitialization() && !myronDataInitializing);memset(hdr,0,sizeof hdr);assert(!myronDataMayInitialize(hdr));
 commands=syncs=0;
 uint8_t data[33*4096]={};assert(myron_data_store_write(0,33,data));assert(commands==2);
 assert(!myron_data_store_write(262152,2,data)&&commands==2);
 assert(myron_data_store_read(0,33,data)&&commands==4);
 assert(myron_data_store_sync()&&syncs==1);
 failWrite=true;assert(!myron_data_store_write(0,1,data)&&myronDataFailed);
 unsigned before=commands;assert(!myron_data_store_read(0,1,data)&&commands==before);
 assert(!myron_data_store_write(0,1,data)&&commands==before);
}
