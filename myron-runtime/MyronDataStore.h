// SPDX-License-Identifier: BSD-2-Clause-Patent
// Board-owned callbacks. The legacy sheng-data-persist write path stays closed.
#include "MyronDataWindow.h"
static uint64_t myronDataFirst, myronDataBlocks;
static bool myronDataFailed, myronDataInitializing;
extern "C" unsigned myron_data_store_mode(void) { return 2; }
extern "C" unsigned myron_data_store_gpt_check(void) {
    unsigned result=native_ufs_store_gpt_check();
    if(result)myronDataFailed=true;
    return result;
}
extern "C" __attribute__((noinline)) int myron_data_store_open(uint64_t blocks,uint64_t *first,const char **why) {
    uint64_t target=0;
    if(why)*why="myron Data geometry/identity refused";
    if(myronDataFailed || !first || !blocks || blocks>524305 || myronDataBlocks || !myron_root_start_ready || !gStoreGeometry.valid ||
       !gHost.ready || gHost.poisoned || storeMode() || logMode() ||
       strcmp(rootPartitionName(),"unixnu") || reserveBlocks()!=myron_root_geometry.reserveBlocks ||
       !myronDataWindow(myron_root_geometry,gStoreGeometry.imageBytes,gStoreGeometry.first,
                       gStoreGeometry.last,blocks+1,&target) || myron_data_store_gpt_check())return 0;
    IOLockLock(gHost.lock);
    bool ok=!gHost.poisoned && hostStoreOpen(target,blocks+1);
    if(ok){myronDataFirst=target+1;myronDataBlocks=blocks;*first=target+1;}
    IOLockUnlock(gHost.lock);
    if(!ok)return 0;
    uint8_t marker[4096];
    if(hostRead4k(0,target,1,marker)!=kIOReturnSuccess){myronDataFailed=true;return 0;}
    unsigned state=myronDataMarker(marker,target,blocks+1);
    if(state==3){myronDataFailed=true;return 0;}
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
