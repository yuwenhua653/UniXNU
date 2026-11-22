// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "MyronPolicyCarrier.h"
#include <string.h>
// A seed overlay belongs below the reserved carrier/log tail, wholly above
// the signed root image plus its 4 MiB guard. All units below are 4096-byte LBAs.
static inline bool myronDataWindow(const MyronRootGeometry &g, uint64_t imageBytes,
    uint64_t first, uint64_t last, uint64_t blocks, uint64_t *out) {
    if (!out || !myronRootGeometryValid(g) || first!=g.first || last!=g.last ||
        !imageBytes || !blocks || blocks>524306) return false;
    uint64_t size=last-first+1, image=(imageBytes-1)/4096+1;
    if (size<=g.reserveBlocks || blocks>size-g.reserveBlocks) return false;
    uint64_t relative=size-g.reserveBlocks-blocks;
    if (image>relative || relative-image<1024) return false;
    *out=first+relative;
    return true;
}
static inline bool myronDataRange(uint64_t capacity, uint64_t relative, uint32_t blocks) {
    return blocks && relative<capacity && blocks<=capacity-relative;
}
static inline bool myronDataBlank(const unsigned char *header, unsigned count) {
    if (!header || count!=4096) return false;
    unsigned char any=0;
    for(unsigned i=0;i<count;++i)any|=header[i];
    return any==0;
}
// A dedicated marker distinguishes first initialization from a damaged existing
// overlay. Pending -> ready only after the overlay header/bitmap are durable.
static inline uint32_t myronDataCrc(const unsigned char *p,unsigned n){
    uint32_t c=~0u;while(n--){c^=*p++;for(unsigned j=0;j<8;++j)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}return ~c;
}
static inline uint64_t myronDataGet(const unsigned char *p,unsigned n){uint64_t v=0;while(n)v=(v<<8)|p[--n];return v;}
static inline void myronDataPut(unsigned char *p,uint64_t v,unsigned n){for(unsigned i=0;i<n;++i){p[i]=(unsigned char)v;v>>=8;}}
static inline unsigned myronDataMarker(const unsigned char *p,uint64_t first,uint64_t blocks){
    if(memcmp(p,"MYRDATA",7))return 0; // unclaimed board-owned extent
    if(p[7]!='1' || myronDataGet(p+8,4)!=1 || myronDataGet(p+16,8)!=first || myronDataGet(p+24,8)!=blocks ||
       myronDataGet(p+32,4)!=myronDataCrc(p,32))return 3;
    unsigned state=(unsigned)myronDataGet(p+12,4);return state==1 || state==2?state:3;
}
static inline void myronDataMark(unsigned char *p,uint64_t first,uint64_t blocks,unsigned state){
    memset(p,0,4096);memcpy(p,"MYRDATA1",8);myronDataPut(p+8,1,4);myronDataPut(p+12,state,4);
    myronDataPut(p+16,first,8);myronDataPut(p+24,blocks,8);myronDataPut(p+32,myronDataCrc(p,32),4);
}
