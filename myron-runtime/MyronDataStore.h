// SPDX-License-Identifier: BSD-2-Clause-Patent
// Board-owned callbacks. The legacy sheng-data-persist write path stays closed.
#include "MyronDataGrowth.h"
static uint64_t myronDataFirst, myronDataBlocks;
static bool myronDataFailed, myronDataInitializing;
static uint64_t myronDataSelectedMarker, myronDataSelectedBytes;
static unsigned char myronDataSelectedSeed[32];
extern "C" unsigned myron_data_store_mode(void) { return 2; }
extern "C" unsigned myron_data_store_gpt_check(void) {
    unsigned result=native_ufs_store_gpt_check();
    if(result)myronDataFailed=true;
    return result;
}
// Called before the block provider is published, after hashing the original
// seed. This probe never claims a destination or writes any device block.
static bool myronDataProbeCapacity(const unsigned char seed[32],uint64_t originalBytes,
    unsigned char scratch[8192],uint64_t *logicalBytes) {
    uint64_t target=0;
    if(!seed || !scratch || !logicalBytes || myronDataFailed || myronDataBlocks ||
       myronDataSelectedBytes || originalBytes!=MyronDataSeedBytes ||
       !myron_root_start_ready || !gStoreGeometry.valid || !gHost.ready || gHost.poisoned ||
       storeMode() || logMode() || strcmp(rootPartitionName(),"unixnu") ||
       reserveBlocks()!=myron_root_geometry.reserveBlocks ||
       gStoreGeometry.first!=myron_root_geometry.first || gStoreGeometry.last!=myron_root_geometry.last ||
       !myronDataGrowthWindow(myron_root_geometry,gStoreGeometry.imageBytes,&target) ||
       myron_data_store_gpt_check())return false;
    if(hostRead4k(0,target,1,scratch)!=kIOReturnSuccess){myronDataFailed=true;return false;}
    unsigned state=myronDataGrowthMarker(scratch,target);
    if(state==3 || (!state && !myronDataBlank(scratch,4096))){myronDataFailed=true;return false;}
    if(state==2){
        if(hostRead4k(0,target+1,1,scratch+4096)!=kIOReturnSuccess ||
           !myronDataGrowthHeader(scratch+4096,seed)){myronDataFailed=true;return false;}
        myronDataSelectedMarker=target;myronDataSelectedBytes=MyronDataGrownBytes;
    }else{
        myronDataSelectedMarker=target+MyronDataGrownBlocks;myronDataSelectedBytes=originalBytes;
    }
    memcpy(myronDataSelectedSeed,seed,32);*logicalBytes=myronDataSelectedBytes;return true;
}
extern "C" __attribute__((noinline)) int myron_data_capacity_valid(uint64_t bytes) {
    return !myronDataFailed && gHost.ready && !gHost.poisoned && !myronDataInitializing && bytes==MyronDataGrownBytes &&
        myronDataSelectedBytes==bytes && myronDataBlocks==MyronDataGrownBlocks-1 &&
        myronDataFirst==myronDataSelectedMarker+1;
}
extern "C" __attribute__((noinline)) int myron_data_store_open(uint64_t blocks,uint64_t *first,const char **why) {
    uint64_t target=0;
    if(why)*why="myron Data geometry/identity refused";
    const bool grown=myronDataSelectedBytes==MyronDataGrownBytes;
    if(myronDataFailed || !first || !blocks || myronDataBlocks || !myron_root_start_ready || !gStoreGeometry.valid ||
       !gHost.ready || gHost.poisoned || storeMode() || logMode() ||
       strcmp(rootPartitionName(),"unixnu") || reserveBlocks()!=myron_root_geometry.reserveBlocks ||
       gStoreGeometry.first!=myron_root_geometry.first || gStoreGeometry.last!=myron_root_geometry.last ||
       myron_data_store_gpt_check())return 0;
    if(grown){
        if(blocks!=MyronDataGrownBlocks-1 ||
           !myronDataGrowthWindow(myron_root_geometry,gStoreGeometry.imageBytes,&target) ||
           target!=myronDataSelectedMarker)return 0;
    }else if(!myronDataWindow(myron_root_geometry,gStoreGeometry.imageBytes,gStoreGeometry.first,
                             gStoreGeometry.last,blocks+1,&target))return 0;
    if(!grown && myronDataSelectedBytes &&
       (blocks!=MyronDataOldBlocks-1 || target!=myronDataSelectedMarker))return 0;
    IOLockLock(gHost.lock);
    bool ok=!gHost.poisoned && hostStoreOpen(target,blocks+1);
    if(ok){myronDataFirst=target+1;myronDataBlocks=blocks;*first=target+1;}
    IOLockUnlock(gHost.lock);
    if(!ok)return 0;
    uint8_t marker[4096];
    if(hostRead4k(0,target,1,marker)!=kIOReturnSuccess){myronDataFailed=true;return 0;}
    unsigned state=myronDataMarker(marker,target,blocks+1);
    if(state==3){myronDataFailed=true;return 0;}
    if(grown){
        if(state!=2 || hostRead4k(0,target+1,1,marker)!=kIOReturnSuccess ||
           !myronDataGrowthHeader(marker,myronDataSelectedSeed)){myronDataFailed=true;return 0;}
        myronDataInitializing=false;
        if(why)*why="";
        return 1;
    }
    if(!state){
        // Migration from the reviewed volatile-only builds: this newly allocated
        // extent is inside unixnu, above the signed root, outside carrier/log.
        // Claim it before initializing, so later corruption is never auto-reset.
        myronDataMark(marker,target,blocks+1,1);
        if(hostWrite4k(0,target,1,marker,true)!=kIOReturnSuccess || hostSyncCache()!=kIOReturnSuccess){myronDataFailed=true;return 0;}
        state=1;
    }
    myronDataInitializing=state==1;
    if(why)*why="";
    return 1;
}
extern "C" __attribute__((noinline)) int myron_data_store_read(uint64_t rel,uint32_t n,void *out) {
    if(!out || myronDataFailed || gHost.poisoned || !myronDataRange(myronDataBlocks,rel,n))return 0;
    while(n){uint32_t chunk=n>kDataMax/4096?kDataMax/4096:n;
        if(hostRead4k(0,myronDataFirst+rel,chunk,out)!=kIOReturnSuccess){myronDataFailed=true;return 0;}
        rel+=chunk;n-=chunk;out=(uint8_t*)out+chunk*4096;
    }return 1;
}
extern "C" __attribute__((noinline)) int myron_data_store_write(uint64_t rel,uint32_t n,const void *in) {
    if(!in || myronDataFailed || gHost.poisoned || !myronDataRange(myronDataBlocks,rel,n))return 0;
    while(n){uint32_t chunk=n>kDataMax/4096?kDataMax/4096:n;
        // A successful write is durable before its bitmap can reference it.
        if(hostWrite4k(0,myronDataFirst+rel,chunk,in,true)!=kIOReturnSuccess){myronDataFailed=true;return 0;}
        rel+=chunk;n-=chunk;in=(const uint8_t*)in+chunk*4096;
    }return 1;
}
extern "C" __attribute__((noinline)) int myron_data_store_sync(void) {
    if(!myronDataBlocks || myronDataFailed || myron_data_store_gpt_check() ||
       hostSyncCache()!=kIOReturnSuccess){myronDataFailed=true;return 0;}
    return 1;
}

static bool myronDataMayInitialize(const uint8_t *header) {
    // Never reset a recognized overlay, including a foreign seed or bad CRC.
    return myronDataInitializing && memcmp(header,"SHNGDATA",8)!=0;
}
static bool myronDataCommitInitialization() {
    if(myronDataFailed)return false;
    if(!myronDataInitializing)return true;
    uint8_t marker[4096];
    myronDataMark(marker,myronDataFirst-1,myronDataBlocks+1,2);
    if(hostWrite4k(0,myronDataFirst-1,1,marker,true)!=kIOReturnSuccess || hostSyncCache()!=kIOReturnSuccess){myronDataFailed=true;return false;}
    myronDataInitializing=false;return true;
}
