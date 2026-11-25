// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <cassert>
#include <cstring>
#include "MyronDataGrowth.h"
int main(){
 MyronRootGeometry phone={249424640,257813247,257813503,34241249280ULL,117911552,28928};
 uint64_t target=0;assert(myronDataGrowthWindow(phone,15092154368ULL,&target));
 assert(target==256473556ULL && target+MyronDataGrownBlocks==257522166ULL);
 assert(!myronDataGrowthWindow(phone,31ULL<<30,&target));
 assert(!myronDataGrowthWindow(phone,UINT64_MAX,&target));
 assert(!myronDataGrowthWindow(phone,0,&target));
 assert(!myronDataGrowthWindow(phone,15092154368ULL,nullptr));
 assert(myronDataGrowthWindow(phone,15092154368ULL,&target));
 unsigned char m[4096]={},h[4096]={},seed[32]={1},other[32]={2};
 assert(myronDataGrowthMarker(m,target)==0);
 myronDataMark(m,target,MyronDataGrownBlocks,1);assert(myronDataGrowthMarker(m,target)==1);
 myronDataMark(m,target,MyronDataGrownBlocks,2);assert(myronDataGrowthMarker(m,target)==2);
 assert(myronDataGrowthMarker(m,target+1)==3);
 m[32]^=1;assert(myronDataGrowthMarker(m,target)==3);
 memcpy(h,"SHNGDATA",8);myronDataPut(h+8,1,4);myronDataPut(h+12,64,4);
 myronDataPut(h+16,MyronDataGrownBytes/4096,8);memcpy(h+24,seed,32);
 myronDataPut(h+60,myronDataCrc(h,60),4);
 assert(myronDataGrowthHeader(h,seed));assert(!myronDataGrowthHeader(h,other));
 for(unsigned i=0;i<64;++i){h[i]^=1;assert(!myronDataGrowthHeader(h,seed));h[i]^=1;}
 myronDataPut(h+16,MyronDataSeedBytes/4096,8);myronDataPut(h+60,myronDataCrc(h,60),4);
 assert(!myronDataGrowthHeader(h,seed));
}
