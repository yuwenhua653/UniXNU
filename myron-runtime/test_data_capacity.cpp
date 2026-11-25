// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <array>
#include <cassert>
#include <cstdlib>
#include <map>
#include <memory>
#include "MyronDataCapacity.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#include "DirectDisk.h"
#pragma GCC diagnostic pop
using Page=std::array<unsigned char,4096>;
// Synthetic geometry, not a user's GPT or deployment.
static MyronRootGeometry myron_root_geometry={4096,8392703,8400000,31ULL<<30,4ULL<<20,262144};
static struct {bool valid;uint64_t imageBytes,first,last;} gStoreGeometry={true,16ULL<<30,4096,8392703};
static struct {bool ready,poisoned;void *lock;} gHost={true,false,nullptr};
static unsigned myron_root_start_ready=1,gptError=0,reads=0,writes=0;
static bool locked=false,opened=false;
static uint64_t windowFirst,windowBlocks;
static constexpr uint64_t dest=6819796ULL,source=7868406ULL;
static constexpr unsigned kDataMax=131072,kIOReturnSuccess=0;
static std::map<uint64_t,Page> disk;
static unsigned storeMode(){return 0;}static unsigned logMode(){return 0;}
static const char *rootPartitionName(){return "unixnu";}
static uint64_t reserveBlocks(){return 262144;}
static unsigned native_ufs_store_gpt_check(){return gptError;}
static void IOLockLock(void*){assert(!locked);locked=true;}
static void IOLockUnlock(void*){assert(locked);locked=false;}
static bool hostStoreOpen(uint64_t first,uint64_t blocks){
 assert(locked);if(opened)return false;opened=true;windowFirst=first;windowBlocks=blocks;return true;
}
static int hostRead4k(unsigned lun,uint64_t first,uint32_t n,void *out){
 assert(!locked && !lun && n && n<=32 && first>=dest && first+n<=source+MyronDataOldBlocks);
 auto p=static_cast<unsigned char*>(out);++reads;
 for(unsigned i=0;i<n;++i){auto it=disk.find(first+i);if(it==disk.end())memset(p+i*4096,0,4096);else memcpy(p+i*4096,it->second.data(),4096);}
 return 0;
}
static int hostWrite4k(unsigned lun,uint64_t first,uint32_t n,const void *in,bool fua){
 assert(!locked && !lun && fua && opened && n && n<=32 && first>=windowFirst && first+n<=windowFirst+windowBlocks);
 auto p=static_cast<const unsigned char*>(in);++writes;
 for(unsigned i=0;i<n;++i)memcpy(disk[first+i].data(),p+i*4096,4096);
 return 0;
}
static int hostSyncCache(){assert(!locked);return 0;}
#include "MyronDataStore.h"
static const unsigned char seed[32]={1};
static void reset(unsigned state){
 disk.clear();reads=writes=0;opened=locked=false;gHost.ready=true;gHost.poisoned=false;gptError=0;
 myronDataFirst=myronDataBlocks=myronDataSelectedMarker=myronDataSelectedBytes=0;
 myronDataFailed=myronDataInitializing=false;
 myronDataMark(disk[source].data(),source,MyronDataOldBlocks,2);
 persist::encodeHeader(disk[source+1].data(),MyronDataSeedBytes/4096,seed,3);
 if(state){myronDataMark(disk[dest].data(),dest,MyronDataGrownBlocks,state);
  persist::encodeHeader(disk[dest+1].data(),MyronDataGrownBytes/4096,seed,3);}
}
struct Alloc {
 bool fail=false;
 void *zero(uint64_t n){return fail?nullptr:calloc(1,n);}
 void release(void *p,uint64_t){free(p);}
};
struct Store {
 bool read(uint64_t b,uint32_t n,void *p){return myron_data_store_read(b,n,p);}
 bool write(uint64_t b,uint32_t n,const void *p){return myron_data_store_write(b,n,p);}
 bool sync(){return myron_data_store_sync();}
};
struct Buffer {
 std::array<unsigned char,512> data={};
 uint64_t copy(uint64_t at,const void *p,uint64_t n){assert(at+n<=data.size());memcpy(data.data()+at,p,n);return n;}
 uint64_t read(uint64_t at,void *p,uint64_t n){assert(at+n<=data.size());memcpy(p,data.data()+at,n);return n;}
};
int main(){
 auto scratch=std::make_unique<unsigned char[]>(8192);
 uint64_t logical=0,first=0;const char *why=nullptr;
 for(unsigned state:{0,1}){
  reset(state);assert(myronDataProbeCapacity(seed,MyronDataSeedBytes,scratch.get(),&logical));
  assert(logical==MyronDataSeedBytes && !writes && !opened);
  assert(!myron_data_store_open(MyronDataOldBlocks-2,&first,&why) && !opened);
  assert(myron_data_store_open(MyronDataOldBlocks-1,&first,&why) && first==source+1);
  assert(!myron_data_capacity_valid(MyronDataGrownBytes));
 }
 reset(2);assert(myronDataProbeCapacity(seed,MyronDataSeedBytes,scratch.get(),&logical));
 assert(logical==MyronDataGrownBytes && !writes && !opened);
 assert(!myron_data_store_open(MyronDataOldBlocks-1,&first,&why) && !opened);
 assert(!myron_data_capacity_valid(logical));
 assert(myron_data_store_open(MyronDataGrownBlocks-1,&first,&why) && first==dest+1);
 assert(myron_data_capacity_valid(logical) && !myron_data_capacity_valid(logical-4096));
 gHost.poisoned=true;assert(!myron_data_capacity_valid(logical));gHost.poisoned=false;
 assert(!myronDataMayInitialize(disk[dest+1].data()) && myronDataCommitInitialization() && !writes);
 Alloc alloc;RamSparseDisk sparse={};sparse.bytes=MyronDataSeedBytes;
 sparse.pages=static_cast<unsigned char**>(calloc(MyronDataSeedBytes/4096,sizeof(unsigned char*)));
 assert(sparse.pages);auto originalPointers=sparse.pages;
 auto oldPage=static_cast<unsigned char*>(malloc(4096));assert(oldPage);memset(oldPage,0x55,4096);
 sparse.pages[MyronDataSeedBytes/4096-1]=oldPage;sparse.resident=4096;
 alloc.fail=true;assert(!myronDataExpandSeed(sparse,logical,alloc));
 assert(sparse.pages==originalPointers && sparse.bytes==MyronDataSeedBytes && sparse.resident==4096);
 alloc.fail=false;assert(myronDataExpandSeed(sparse,logical,alloc));
 assert(sparse.bytes==logical && sparse.resident==4096 && sparse.find(MyronDataSeedBytes/4096-1)==oldPage);
 assert(!sparse.find(MyronDataSeedBytes/4096) && !sparse.find(logical/4096-1));
 auto bits=std::make_unique<unsigned char[]>(32*4096),stage=std::make_unique<unsigned char[]>(4096);
 Store store;persist::Overlay overlay;
 assert(overlay.open(store,logical/4096,seed,false,bits.get(),false)==persist::Open::Resumed);
 Buffer buffer;bool failed=false;
 assert(directDiskIO(sparse,overlay,store,stage.get(),1,false,MyronDataSeedBytes-256,512,buffer,&failed)==512 && !failed);
 for(unsigned i=0;i<512;++i)assert(buffer.data[i]==(i<256?0x55:0));
 buffer.data.fill(0x73);
 assert(directDiskIO(sparse,overlay,store,stage.get(),1,true,logical-512,512,buffer,&failed)==512 && !failed);
 buffer.data.fill(0);
 assert(directDiskIO(sparse,overlay,store,stage.get(),1,false,logical-512,512,buffer,&failed)==512 && !failed);
 for(auto b:buffer.data)assert(b==0x73);
 assert(!directDiskIO(sparse,overlay,store,stage.get(),1,true,logical,512,buffer,&failed));
 assert(myronDataHeaderFor(disk[source+1].data(),seed,MyronDataSeedBytes));
 for(unsigned i=0;i<4096;++i)assert(oldPage[i]==0x55);
 free(oldPage);free(sparse.pages);
 // Post-probe metadata corruption must stop opening the new store.
 reset(2);assert(myronDataProbeCapacity(seed,MyronDataSeedBytes,scratch.get(),&logical));
 disk[dest+1][24]^=1;assert(!myron_data_store_open(MyronDataGrownBlocks-1,&first,&why));
 assert(myronDataFailed && !myron_data_capacity_valid(logical) && !writes);
 for(unsigned fault=0;fault<5;++fault){
  reset(2);
  if(fault==0)disk[dest][32]^=1;
  if(fault==1)disk[dest+1][24]^=1;
  if(fault==2)gptError=1;
  if(fault==3)gHost.poisoned=true;
  if(fault==4)disk[dest][0]^=1;
  assert(!myronDataProbeCapacity(seed,MyronDataSeedBytes,scratch.get(),&logical) && !writes && !opened);
 }
}
