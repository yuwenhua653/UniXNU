// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "MyronDataWindow.h"
enum : uint64_t {
    MyronDataSeedBytes=UINT64_C(1)<<30,
    MyronDataGrownBytes=UINT64_C(16)<<30,
    MyronDataOldBlocks=262154,
    MyronDataGrownBitmapBlocks=128,
    MyronDataGrownDataOffset=2+MyronDataGrownBitmapBlocks,
    MyronDataGrownBlocks=MyronDataGrownDataOffset+(MyronDataGrownBytes/4096),
    MyronDataLegacyBlocks=1048610
};
// The expanded copy is wholly BEFORE the original overlay. Neither the signed
// root, its guard, the original Data nor the log/carrier tail may be reclaimed.
static inline bool myronDataGrowthWindow(const MyronRootGeometry &g,uint64_t rootBytes,uint64_t *out) {
    uint64_t old=0;
    if(!out || !myronDataWindow(g,rootBytes,g.first,g.last,MyronDataOldBlocks,&old) ||
       old<g.first || MyronDataGrownBlocks>old-g.first)return false;
    uint64_t first=old-MyronDataGrownBlocks;
    uint64_t rootBlocks=(rootBytes-1)/4096+1;
    if(rootBlocks>first-g.first || first-g.first-rootBlocks<1024)return false;
    *out=first;return true;
}
// A header alone cannot select the new volume: its separate marker must be
// ready. A pending copy is never activated. Recognized corruption is an error.
static inline unsigned myronDataGrowthMarker(const unsigned char *marker,uint64_t first) {
    return myronDataMarker(marker,first,MyronDataGrownBlocks);
}
static inline bool myronDataHeaderFor(const unsigned char *header,const unsigned char *seed,uint64_t bytes) {
    return header && seed && !memcmp(header,"SHNGDATA",8) &&
        myronDataGet(header+8,4)==1 && myronDataGet(header+12,4)==64 &&
        myronDataGet(header+16,8)==bytes/4096 &&
        !memcmp(header+24,seed,32) && myronDataGet(header+60,4)==myronDataCrc(header,60);
}
static inline bool myronDataGrowthHeader(const unsigned char *header,const unsigned char *seed) {
    return myronDataHeaderFor(header,seed,MyronDataGrownBytes);
}
