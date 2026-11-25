// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "MyronDataGrowth.h"

// PRE-MOUNT ONLY. This core is deliberately not wired to a boot flag yet.
// A caller must hold exclusive ownership of both extents until it publishes
// the selected Data medium. quiescent() must refuse any mounted/active writer.
// Ops reads absolute 4 KiB LBAs, writes with FUA, and syncs the device cache.
// All scratch storage is caller-owned (no large kernel-stack allocations).
// Copy failure leaves the original untouched. A READY destination is NEVER
// overwritten: it may already contain newer writes than the retained source.
struct MyronDataMigrationScratch {
    unsigned char marker[4096], header[4096], bitmap[32768];
    unsigned char data[32*4096], verify[32*4096];
};
enum class MyronDataMigrationResult {
    Ready, Refused, AlreadyReady, SourceInvalid, DestinationInvalid, IOFailed,
    ReadbackFailed, SourceChanged
};

// The future block provider must select before publishing IOMedia. A damaged
// READY copy is an error, never permission to resurrect the older Data copy.
struct MyronDataSelection { uint64_t markerLba, logicalBytes, windowBlocks; };
template<class Ops>
static bool myronDataSelect(Ops &ops,const MyronRootGeometry &geometry,uint64_t rootBytes,
    const unsigned char seed[32],unsigned char scratch[8192],MyronDataSelection &out)
{
    uint64_t dest=0;
    if(!seed || !scratch || !myronDataGrowthWindow(geometry,rootBytes,&dest) ||
       !ops.read(dest,1,scratch))return false;
    unsigned state=myronDataGrowthMarker(scratch,dest);
    if(state==3 || (!state && !myronDataBlank(scratch,4096)))return false;
    if(state==2){
        if(!ops.read(dest+1,1,scratch+4096) || !myronDataGrowthHeader(scratch+4096,seed))return false;
        out={dest,MyronDataGrownBytes,MyronDataGrownBlocks};return true;
    }
    uint64_t source=dest+MyronDataGrownBlocks;
    if(!ops.read(source,1,scratch) || !ops.read(source+1,1,scratch+4096) ||
       myronDataMarker(scratch,source,MyronDataOldBlocks)!=2 ||
       !myronDataHeaderFor(scratch+4096,seed,MyronDataSeedBytes))return false;
    out={source,MyronDataSeedBytes,MyronDataOldBlocks};return true;
}

template<class Ops>
static MyronDataMigrationResult myronDataMigrate(Ops &ops,const MyronRootGeometry &geometry,
    uint64_t rootBytes,const unsigned char seed[32],MyronDataMigrationScratch &s)
{
    using R=MyronDataMigrationResult;
    uint64_t dest=0;
    if(!seed || !ops.quiescent() || !myronDataGrowthWindow(geometry,rootBytes,&dest))return R::Refused;
    const uint64_t source=dest+MyronDataGrownBlocks;
    if(!ops.read(source,1,s.marker) || !ops.read(source+1,1,s.header) ||
       !ops.read(source+2,8,s.bitmap))return R::IOFailed;
    if(myronDataMarker(s.marker,source,MyronDataOldBlocks)!=2 ||
       !myronDataHeaderFor(s.header,seed,MyronDataSeedBytes))return R::SourceInvalid;
    if(!ops.read(dest,1,s.verify))return R::IOFailed;
    unsigned state=myronDataGrowthMarker(s.verify,dest);
    if(state==2)return R::AlreadyReady;
    if(state==3 || (!state && !myronDataBlank(s.verify,4096)))return R::DestinationInvalid;
    if(!ops.quiescent())return R::Refused;
    myronDataMark(s.data,dest,MyronDataGrownBlocks,1);
    if(!ops.write(dest,1,s.data) || !ops.sync())return R::IOFailed;
    if(!ops.read(dest,1,s.verify))return R::IOFailed;
    if(memcmp(s.data,s.verify,4096))return R::ReadbackFailed;

    // Copy CURRENT changed pages directly from the offline source, never a
    // host snapshot. New bitmap bits remain zero, so new pages read as zero.
    const uint64_t pages=MyronDataSeedBytes/4096;
    for(uint64_t i=0;i<pages;){
        if(!(s.bitmap[i/8]&(1u<<(i%8)))){++i;continue;}
        uint32_t n=1;
        while(n<32 && i+n<pages && (s.bitmap[(i+n)/8]&(1u<<((i+n)%8))))++n;
        if(!ops.read(source+10+i,n,s.data) || !ops.write(dest+34+i,n,s.data) ||
           !ops.read(dest+34+i,n,s.verify))return R::IOFailed;
        if(memcmp(s.data,s.verify,n*4096))return R::ReadbackFailed;
        i+=n;
    }
    // Retain source metadata in scratch until the final source comparison.
    memset(s.data,0,sizeof(s.data));memcpy(s.data,s.bitmap,sizeof(s.bitmap));
    if(!ops.write(dest+2,32,s.data) || !ops.read(dest+2,32,s.verify))return R::IOFailed;
    if(memcmp(s.data,s.verify,sizeof(s.data)))return R::ReadbackFailed;
    memcpy(s.data,s.header,4096);
    myronDataPut(s.data+16,MyronDataGrownBytes/4096,8);
    myronDataPut(s.data+60,myronDataCrc(s.data,60),4);
    if(!ops.write(dest+1,1,s.data) || !ops.sync() || !ops.read(dest+1,1,s.verify))return R::IOFailed;
    if(memcmp(s.data,s.verify,4096))return R::ReadbackFailed;
    if(!ops.quiescent())return R::Refused;
    if(!ops.read(source,1,s.verify) || !ops.read(source+1,1,s.verify+4096) ||
       !ops.read(source+2,8,s.verify+8192))return R::IOFailed;
    if(memcmp(s.marker,s.verify,4096) || memcmp(s.header,s.verify+4096,4096) ||
       memcmp(s.bitmap,s.verify+8192,32768))return R::SourceChanged;
    // Only now may a future backend select this copy. This changes block
    // capacity, NOT the APFS container: Apple APFS resize must follow.
    myronDataMark(s.data,dest,MyronDataGrownBlocks,2);
    if(!ops.write(dest,1,s.data) || !ops.sync() || !ops.read(dest,1,s.verify))return R::IOFailed;
    if(memcmp(s.data,s.verify,4096))return R::ReadbackFailed;
    return R::Ready;
}
