// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include "MyronAPFSTransaction.h"
typedef struct {
    MyronGrowSnapshot initial, final;
    unsigned reads, journals, mutations, events;
    unsigned failRead, changeRead, identityField;
    int prior, minimumError, journalError, resizeError;
    uint64_t lower;
} Peer;
static void change(MyronGrowSnapshot *s,unsigned field) {
    switch(field){
    case 0:s->physical-=4096;break;case 1:s->authorized=0;break;
    case 2:s->volumeID++;break;case 3:s->mediaID++;break;
    case 4:s->storeID++;break;case 5:s->providerID++;break;
    case 6:s->rawDevice++;break;case 7:s->fsid[0]++;break;
    case 8:s->nxUUID[0]++;break;case 9:s->volume[4]++;break;
    case 10:s->media[4]++;break;case 11:s->store[4]++;break;
    case 12:s->volumeUUID[0]++;break;default:assert(0);
    }
}
static int readSnapshot(void *v,MyronGrowSnapshot *s) {
    Peer *p=v;++p->reads;
    if(p->reads==p->failRead)return 1;
    *s=p->mutations?p->final:p->initial;
    if(p->reads==p->changeRead)change(s,p->identityField);
    return 0;
}
static int prior(void *v){return ((Peer *)v)->prior;}
static int minimum(void *v,const MyronGrowSnapshot *s,uint64_t *n){
    Peer *p=v;assert(!strcmp(s->media,"disk3"));*n=p->lower;return p->minimumError;
}
static int journal(void *v,const MyronGrowSnapshot *s){
    Peer *p=v;assert(s->physical==(UINT64_C(16)<<30));++p->journals;p->prior=1;return p->journalError;
}
static int resize(void *v,const MyronGrowSnapshot *s){
    Peer *p=v;assert(p->prior && p->journals==1 && !p->journalError && !p->mutations);
    assert(!strcmp(s->media,"disk3") && s->physical==(UINT64_C(16)<<30));
    ++p->mutations;return p->resizeError;
}
static void event(void *v,const char *name){assert(name[0]);++((Peer *)v)->events;}
static MyronGrowOps ops={readSnapshot,prior,minimum,journal,resize,event};
static Peer fresh(void){
    Peer p={0};MyronGrowSnapshot *s=&p.initial;
    s->physical=s->authorized=UINT64_C(16)<<30;s->container=s->volumeBytes=UINT64_C(1)<<30;
    s->freeBytes=s->containerFree=71*UINT64_C(1048576);
    s->volumeID=1;s->mediaID=2;s->storeID=3;s->providerID=4;s->rawDevice=5;
    s->fsid[0]=6;s->nxUUID[0]=7;
    strcpy(s->volume,"disk3s1");strcpy(s->media,"disk3");strcpy(s->store,"disk1");
    strcpy(s->volumeUUID,"12345678-1234-1234-1234-123456789abc");
    p.final=*s;p.final.container=p.final.volumeBytes=s->physical;
    p.final.freeBytes=p.final.containerFree=(UINT64_C(15)<<30)+s->freeBytes;
    p.lower=UINT64_C(900)<<20;return p;
}
static void denied(Peer *p,unsigned journalCount){
    MyronGrowResult r;assert(myronGrowTransaction(p,&ops,1,&r)==2);
    assert(!r.resizeCalled && !p->mutations && p->journals==journalCount);
    assert(!strcmp(r.status,"refused"));
}
int main(void){
    unsigned cases=0;Peer p;MyronGrowResult r;
    p=fresh();assert(!myronGrowTransaction(&p,&ops,1,&r));
    assert(p.reads==4 && p.mutations==1 && r.resizeCalled && !strcmp(r.status,"expanded-and-verified"));++cases;
    /* A second run observes real capacity; it does not blindly repeat resize. */
    assert(!myronGrowTransaction(&p,&ops,1,&r));assert(p.mutations==1 && !r.resizeCalled && !strcmp(r.status,"already-expanded"));++cases;
    p=fresh();assert(!myronGrowTransaction(&p,&ops,0,&r));assert(!p.journals && !p.mutations && !strcmp(r.status,"inspected"));++cases;
    p=fresh();p.prior=1;denied(&p,0);++cases;
    p=fresh();p.minimumError=5;denied(&p,0);++cases;
    p=fresh();p.lower=0;denied(&p,0);++cases;
    p=fresh();p.lower=p.initial.container+1;denied(&p,0);++cases;
    p=fresh();p.journalError=28;denied(&p,1);++cases;
    for(unsigned i=1;i<=3;++i){p=fresh();p.failRead=i;denied(&p,i==3);++cases;}
    for(unsigned at=2;at<=4;++at)for(unsigned field=0;field<13;++field){
        p=fresh();p.changeRead=at;p.identityField=field;
        if(at<4)denied(&p,at==3);
        else{assert(myronGrowTransaction(&p,&ops,1,&r)==3);assert(p.mutations==1);}
        ++cases;
    }
    for(unsigned kind=0;kind<7;++kind){
        p=fresh();
        if(kind==0)p.resizeError=5;
        if(kind==1)p.failRead=4;
        if(kind==2)p.final.container=p.initial.container;
        if(kind==3)p.final.volumeBytes=p.initial.volumeBytes;
        if(kind==4)p.final.freeBytes=p.initial.freeBytes;
        if(kind==5)p.final.freeBytes=UINT64_MAX;
        if(kind==6)p.final.containerFree=UINT64_MAX;
        assert(myronGrowTransaction(&p,&ops,1,&r)==3 && r.resizeCalled && p.mutations==1);
        assert(!strcmp(r.status,"resize-outcome-unverified-no-auto-retry"));++cases;
    }
    p=fresh();p.initial.container=p.initial.physical;denied(&p,0);++cases;
    p=fresh();p.initial.freeBytes=UINT64_MAX;denied(&p,0);++cases;
    p=fresh();p.initial.authorized=0;denied(&p,0);++cases;
    printf("PASS: %u real transaction-core cases; no APFS or phone runtime exercised\n",cases);
}
