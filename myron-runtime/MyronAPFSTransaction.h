// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "MyronAPFSGrow.h"

/* Shared by the real iOS helper and the host fault harness. All observations
 * come from adapters; this core neither chooses a disk nor writes raw blocks. */
typedef struct {
    uint64_t physical, authorized, container, containerFree, volumeBytes, freeBytes;
    uint64_t volumeID, mediaID, storeID, providerID, rawDevice;
    unsigned char fsid[8], nxUUID[16];
    char volume[25], media[25], store[25], volumeUUID[37];
} MyronGrowSnapshot;
typedef struct {
    int (*snapshot)(void *,MyronGrowSnapshot *);
    int (*prior)(void *);
    int (*minimum)(void *,const MyronGrowSnapshot *,uint64_t *);
    int (*journal)(void *,const MyronGrowSnapshot *);
    int (*resize)(void *,const MyronGrowSnapshot *);
    void (*event)(void *,const char *);
} MyronGrowOps;
typedef struct {
    MyronGrowSnapshot before,after;
    uint64_t minimumBytes;
    int decision, minimumStatus, resizeStatus, resizeCalled;
    const char *status, *reason;
} MyronGrowResult;

static inline int myronGrowSnapshotValid(const MyronGrowSnapshot *s) {
    const uint64_t old=UINT64_C(1)<<30,target=UINT64_C(16)<<30;
    return (s->physical==old || s->physical==target) &&
        (s->container==old || s->container==target) && s->container<=s->physical &&
        s->containerFree<=s->container && s->volumeBytes && s->volumeBytes<=s->container &&
        s->freeBytes<=s->volumeBytes && s->volumeID && s->mediaID && s->storeID && s->providerID &&
        s->volume[0] && s->media[0] && s->store[0] && s->volumeUUID[0];
}
static inline int myronGrowSameIdentity(const MyronGrowSnapshot *a,const MyronGrowSnapshot *b) {
    return a->physical==b->physical && a->authorized==b->authorized &&
        a->volumeID==b->volumeID && a->mediaID==b->mediaID && a->storeID==b->storeID &&
        a->providerID==b->providerID && a->rawDevice==b->rawDevice &&
        !memcmp(a->fsid,b->fsid,8) && !memcmp(a->nxUUID,b->nxUUID,16) &&
        !strcmp(a->volume,b->volume) && !strcmp(a->media,b->media) &&
        !strcmp(a->store,b->store) && !strcmp(a->volumeUUID,b->volumeUUID);
}
static inline int myronGrowRefuse(MyronGrowResult *r,const char *reason) {
    r->status="refused";r->reason=reason;return 2;
}
static inline int myronGrowTransaction(void *ctx,const MyronGrowOps *op,int requested,MyronGrowResult *r) {
    memset(r,0,sizeof(*r));op->event(ctx,"snapshot-before");
    if(op->snapshot(ctx,&r->before) || !myronGrowSnapshotValid(&r->before))
        return myronGrowRefuse(r,"live Data snapshot unavailable or inconsistent");
    const MyronGrowSnapshot *a=&r->before;
    r->decision=myronAPFSGrowthDecision(a->physical,a->container,a->authorized,requested,1,op->prior(ctx));
    if(r->decision==MyronAPFSInspect){r->status="inspected";return 0;}
    if(r->decision==MyronAPFSDone){
        if(a->volumeBytes<=(UINT64_C(15)<<30))return myronGrowRefuse(r,"mounted Data has not acquired expanded capacity");
        r->status="already-expanded";return 0;
    }
    if(r->decision!=MyronAPFSGrow)return myronGrowRefuse(r,"growth guards refused; no resize attempted");
    op->event(ctx,"minimum");r->minimumStatus=op->minimum(ctx,a,&r->minimumBytes);
    if(r->minimumStatus || !r->minimumBytes || r->minimumBytes>a->container)
        return myronGrowRefuse(r,"APFS sizing API returned implausible limits");
    MyronGrowSnapshot check={0};
    if(op->snapshot(ctx,&check) || !myronGrowSnapshotValid(&check) ||
       !myronGrowSameIdentity(a,&check) || check.container!=a->container)
        return myronGrowRefuse(r,"Data identity or capacity changed before journal");
    op->event(ctx,"journal");
    if(op->journal(ctx,a))return myronGrowRefuse(r,"operation journal not durable");
    /* Repeat after fsync: do not mutate an identity that changed during I/O. */
    if(op->snapshot(ctx,&check) || !myronGrowSnapshotValid(&check) ||
       !myronGrowSameIdentity(a,&check) || check.container!=a->container)
        return myronGrowRefuse(r,"Data identity or capacity changed before resize");
    op->event(ctx,"resize-enter");r->resizeCalled=1;r->resizeStatus=op->resize(ctx,a);
    op->event(ctx,"resize-return");
    /* Even on API failure, observe and report, but never retry the mutation. */
    int error=op->snapshot(ctx,&r->after);const MyronGrowSnapshot *b=&r->after;
    int ok=!r->resizeStatus && !error && myronGrowSnapshotValid(b) && myronGrowSameIdentity(a,b) &&
        b->container==a->physical && b->volumeBytes>(UINT64_C(15)<<30) && b->freeBytes>a->freeBytes;
    r->status=ok?"expanded-and-verified":"resize-outcome-unverified-no-auto-retry";
    return ok?0:3;
}
