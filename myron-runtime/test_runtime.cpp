// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
#include "MyronDataWindow.h"
#include "MyronPowerKey.h"
#include "PersistOverlay.h"
struct Store {
    std::vector<unsigned char> disk;
    unsigned writes=0,syncs=0,failAt=0;
    explicit Store(unsigned blocks):disk(blocks*4096){}
    bool read(uint64_t b,uint32_t n,void *out){if(b+n>disk.size()/4096)return false;memcpy(out,disk.data()+b*4096,n*4096);return true;}
    bool write(uint64_t b,uint32_t n,const void *in){if(++writes==failAt || b+n>disk.size()/4096)return false;memcpy(disk.data()+b*4096,in,n*4096);return true;}
    bool sync(){++syncs;return true;}
};
struct IO {
    unsigned reads=0,delays=0,writes=0;uint32_t status=1;
    void write(unsigned o,uint32_t v){assert(o==7*32 && v==((1u<<27)|0x100));++writes;}
    uint32_t read(unsigned o){++reads;return o==7*32+8?status:0x80;}
    void delay(){++delays;}
};
int main(){
    MyronRootGeometry g={4096,8392703,8400000,31ULL<<30,4ULL<<20,262144};uint64_t first=0;
    assert(myronDataWindow(g,16ULL<<30,g.first,g.last,262153,&first));
    assert(first+262153==g.last+1-g.reserveBlocks);
    assert(!myronDataWindow(g,31ULL<<30,g.first,g.last,262153,&first));
    assert(!myronDataWindow(g,16ULL<<30,g.first+1,g.last,262153,&first));
    assert(!myronDataWindow(g,UINT64_MAX,g.first,g.last,262153,&first));
    assert(!myronDataWindow(g,16ULL<<30,g.first,g.last,524307,&first));
    assert(!myronDataRange(100,99,2)&&!myronDataRange(100,0,0)&&myronDataRange(100,99,1));
    assert(!myronDataRange(100,UINT64_MAX,1));
    MyronRootGeometry phone={249424640,257813247,257813503,34241249280ULL,117911552,28928};
    assert(myronDataWindow(phone,15092154368ULL,phone.first,phone.last,262154,&first));
    assert(first==257522166ULL && first+262154==phone.last+1-phone.reserveBlocks);
    uint8_t marker[4096];myronDataMark(marker,first,262154,1);
    assert(myronDataMarker(marker,first,262154)==1);
    myronDataMark(marker,first,262154,2);assert(myronDataMarker(marker,first,262154)==2);
    marker[24]^=1;assert(myronDataMarker(marker,first,262154)==3);
    uint8_t seed[32]={1},foreign[32]={2},bits[4096],page[4096],header[4096];memset(page,0x5a,sizeof page);
    Store store(34);persist::Overlay original;
    store.read(0,1,header);assert(myronDataBlank(header,sizeof header));
    assert(original.open(store,32,seed,false,bits,true)==persist::Open::Fresh);
    assert(original.writePage(store,5,page));
    uint8_t nextBits[4096];persist::Overlay reboot;
    store.read(0,1,header);assert(!myronDataBlank(header,sizeof header));
    assert(reboot.open(store,32,seed,false,nextBits,false)==persist::Open::Resumed && reboot.has(5));
    uint8_t got[4096];assert(store.read(persist::pageBlock(32,5),1,got));assert(!memcmp(page,got,sizeof page));
    auto saved=store.disk;persist::Overlay wrong;
    assert(wrong.open(store,32,foreign,false,nextBits,false)==persist::Open::Kept && saved==store.disk);
    store.failAt=store.writes+1;assert(!reboot.writePage(store,8,page));assert(!reboot.has(8));
    MyronPowerDebounce key;
    key.sample(true,true);key.sample(true,true);assert(!key.pending()); // held at boot
    key.sample(true,false);key.sample(true,false);assert(key.armed);
    key.sample(true,true);key.sample(true,false);assert(!key.pending()); // bounce
    key.sample(true,true);key.sample(true,true);assert(key.pending()&&key.stable);
    assert(key.pending());key.accepted();assert(!key.pending()); // failed submit retries
    key.sample(false,false);assert(!key.pending());key.sample(false,false);assert(key.pending()&&!key.stable);
    key.accepted();key.sample(true,true);key.sample(true,true);assert(!key.pending()); // require release
    MyronPowerDebounce side,volume;
    for(int i=0;i<2;++i){side.sample(true,false);volume.sample(true,false);}
    for(int i=0;i<2;++i){side.sample(true,true);volume.sample(true,true);}
    assert(myronButtonBits(side,volume)==3);side.accepted();volume.accepted();
    for(int i=0;i<2;++i)side.sample(true,false);
    assert(myronButtonBits(side,volume)==2 && side.pending() && !volume.pending());
    side.accepted();for(int i=0;i<2;++i)volume.sample(true,false);
    assert(!myronButtonBits(side,volume) && volume.pending());
    IO io;uint8_t value=0;assert(myronPowerRead(io,7,&value)&&value==0x80&&io.writes==1);
    io.status=0;assert(!myronPowerRead(io,7,&value)&&io.delays==500);
    io.status=3;assert(!myronPowerRead(io,7,&value));
    assert(!myronPowerRead(io,8192,&value));
}
