// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include "MyronAPFSGrow.h"
static void put(unsigned char *p,uint64_t v,unsigned n){while(n--){*p++=(unsigned char)v;v>>=8;}}
static void checksum(unsigned char *p){
    uint64_t a=0,b=0;for(unsigned i=8;i<4096;i+=4){a=(a+myronAPFSLE(p+i,4))%UINT32_MAX;b=(b+a)%UINT32_MAX;}
    uint64_t lo=UINT32_MAX-(a+b)%UINT32_MAX,hi=UINT32_MAX-(a+lo)%UINT32_MAX;put(p,(hi<<32)|lo,8);
}
int main(void){
    const uint64_t one=UINT64_C(1)<<30,sixteen=UINT64_C(16)<<30;
    unsigned char p[4096]={0};uint64_t bytes=0;
    memcpy(p+32,"NXSB",4);put(p+24,0x80000001,4);put(p+36,4096,4);put(p+40,one/4096,8);checksum(p);
    assert(myronAPFSNX(p,sizeof(p),&bytes) && bytes==one);
    for(unsigned i=0;i<4096;++i){p[i]^=1;assert(!myronAPFSNX(p,sizeof(p),&bytes));p[i]^=1;}
    assert(!myronAPFSNX(p,4095,&bytes));
    put(p+40,UINT64_MAX,8);checksum(p);assert(!myronAPFSNX(p,4096,&bytes));
    assert(myronAPFSGrowthDecision(one,one,0,0,1,0)==MyronAPFSInspect);
    assert(myronAPFSGrowthDecision(sixteen,one,sixteen,1,1,0)==MyronAPFSGrow);
    assert(myronAPFSGrowthDecision(sixteen,sixteen,sixteen,1,1,1)==MyronAPFSDone);
    assert(myronAPFSGrowthDecision(sixteen,one,sixteen,1,1,1)==MyronAPFSRefuse);
    assert(myronAPFSGrowthDecision(sixteen,one,sixteen,1,0,0)==MyronAPFSRefuse);
    assert(myronAPFSGrowthDecision(sixteen,one,0,1,1,0)==MyronAPFSRefuse);
    assert(myronAPFSGrowthDecision(one,one,sixteen,1,1,0)==MyronAPFSRefuse);
    assert(myronAPFSGrowthDecision(sixteen,sixteen+4096,sixteen,1,1,0)==MyronAPFSRefuse);
}
