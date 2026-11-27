// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

static inline uint64_t myronAPFSLE(const unsigned char *p,unsigned n) {
    uint64_t v=0;while(n)v=(v<<8)|p[--n];return v;
}
// Apple's Fletcher-64 checksum excludes the leading 8-byte checksum itself.
static inline int myronAPFSNX(const unsigned char *p,size_t n,uint64_t *bytes) {
    if(!p || n!=4096 || !bytes || memcmp(p+32,"NXSB",4) ||
       myronAPFSLE(p+36,4)!=4096 || (myronAPFSLE(p+24,4)&0xffff)!=1)return 0;
    uint64_t a=0,b=0;
    for(size_t i=8;i<n;i+=4){a=(a+myronAPFSLE(p+i,4))%UINT32_MAX;b=(b+a)%UINT32_MAX;}
    uint64_t lo=UINT32_MAX-((a+b)%UINT32_MAX),hi=UINT32_MAX-((a+lo)%UINT32_MAX);
    if(myronAPFSLE(p,8)!=((hi<<32)|lo))return 0;
    uint64_t blocks=myronAPFSLE(p+40,8);
    if(!blocks || blocks>UINT64_MAX/4096)return 0;
    *bytes=blocks*4096;return 1;
}
enum { MyronAPFSRefuse=0,MyronAPFSInspect=1,MyronAPFSGrow=2,MyronAPFSDone=3 };
static inline int myronAPFSGrowthDecision(uint64_t physical,uint64_t container,
    uint64_t authorized,int requested,int apiAvailable,int previousAttempt) {
    const uint64_t old=UINT64_C(1)<<30,target=UINT64_C(16)<<30;
    if(physical!=old && physical!=target)return MyronAPFSRefuse;
    if(container<old || container>physical)return MyronAPFSRefuse;
    if(!requested)return MyronAPFSInspect;
    if(physical!=target || authorized!=target || !apiAvailable)return MyronAPFSRefuse;
    if(container==target)return MyronAPFSDone;
    // No automatic retry after an interrupted/failed private API call.
    if(previousAttempt || container!=old)return MyronAPFSRefuse;
    return MyronAPFSGrow;
}
