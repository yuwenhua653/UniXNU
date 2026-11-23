// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include "MyronPowerKey.h"
class MyronPowerHardware {
    IOMemoryMap *maps[4]{};
    volatile uint32_t *core=nullptr,*map=nullptr,*owners=nullptr,*observer=nullptr;
    uint16_t apid=8192;
    IOMemoryMap *volumeMap=nullptr;
    volatile uint32_t *volumePad=nullptr;
    uint32_t volumeConfig=0;
    bool volumeChanged=false;
    // Typeun/myron-device d9b6be4d: stock myron gpio-keys vol_up is GPIO101,
    // active low, GPIO input/pull-up. The pad aperture starts at 0xf100000,
    // not the 0xf000000 controller base. Never switch an alternate function.
    void openVolume() {
        volumeMap=mapping(0xf100000ULL+101*0x1000,0x1000);
        if(!volumeMap)return;
        volumePad=(volatile uint32_t*)volumeMap->getVirtualAddress();
        volumeConfig=volumePad[0];
        if(((volumeConfig>>2)&15) || (volumeConfig&(1u<<9))) {
            volumePad=nullptr;OSSafeReleaseNULL(volumeMap);return;
        }
        if((volumeConfig&3)!=3){
            volumePad[0]=(volumeConfig&~3u)|3u;
            __asm__ volatile("dsb sy":::"memory");IODelay(100);volumeChanged=true;
        }
    }
    static IOMemoryMap *mapping(uint64_t pa,unsigned bytes){
        // OSPtr is a return-type-only alias in the pinned XNU headers.
        // Keep explicit owned raw pointers, paired with release()/close().
        IODeviceMemory *memory=IODeviceMemory::withRange(pa,bytes);
        if(!memory)return nullptr;
        IOMemoryMap *result=memory->map(kIOMapAnywhere|kIOMapInhibitCache);
        memory->release();return result;
    }
public:
    MyronPowerDebounce state,volume,down;
    uint8_t report()const{return myronButtonBits(state,volume,down);}
    bool pending()const{return state.pending()||volume.pending()||down.pending();}
    void accepted(){state.accepted();volume.accepted();down.accepted();}
    unsigned errors=0,reports=0;
    uint32_t rawPon=0,rawVolume=1;
    unsigned volumeUpPresses=0,volumeDownPresses=0;
    bool volumeAvailable()const{return volumePad!=nullptr;}
    uint32_t originalVolumeConfig()const{return volumeConfig;}
    void close(){
        if(volumeChanged && volumePad && volumePad[0]==((volumeConfig&~3u)|3u)){
            volumePad[0]=volumeConfig;__asm__ volatile("dsb sy":::"memory");
        }
        volumePad=nullptr;volumeChanged=false;OSSafeReleaseNULL(volumeMap);
        for(auto &m:maps)OSSafeReleaseNULL(m);core=map=owners=observer=nullptr;apid=8192;
    }
    bool open(){
        const uint64_t addresses[]={0xc400000,0xc403000,0xc42a000,0xc4c0000};
        const unsigned sizes[]={0x1000,0x8000,0x8000,0x40000};
        for(unsigned i=0;i<4;++i){maps[i]=mapping(addresses[i],sizes[i]);if(!maps[i]){close();return false;}}
        core=(volatile uint32_t*)maps[0]->getVirtualAddress();map=(volatile uint32_t*)maps[1]->getVirtualAddress();
        owners=(volatile uint32_t*)maps[2]->getVirtualAddress();observer=(volatile uint32_t*)maps[3]->getVirtualAddress();
        uint32_t version=core[0],count=core[1]&0x1fff;
        if(version<0x80000000u || version>=0x90000000u || !count || count>8192){close();return false;}
        unsigned found=0;
        for(unsigned i=0;i<count;++i)if((map[i]&0x1fff)==0x13 && (owners[i]&7)==0){apid=static_cast<uint16_t>(i);++found;}
        if(found!=1){close();return false;}
        uint8_t value=0;
        if(!myronPowerRead(*this,apid,&value)){close();return false;}
        IOLog("myron-power: SPMI v8 EE0 APID %u, PON status %02x\n",apid,value);
        openVolume();
        IOLog("myron-power: volume-up GPIO101 input %u\n",volumePad!=nullptr);
        return true;
    }
    uint32_t read(unsigned off){uint32_t v=observer[off/4];__asm__ volatile("dmb oshld":::"memory");return v;}
    void write(unsigned off,uint32_t v){__asm__ volatile("dmb oshst":::"memory");observer[off/4]=v;__asm__ volatile("dsb osh":::"memory");}
    void delay(){IODelay(1);}
    void poll(){
        uint8_t value=0;bool ok=observer && myronPowerRead(*this,apid,&value);
        // A failed read releases held keys through debounce; a later valid
        // read can re-arm them. Do not permanently disable PON on one timeout.
        if(!ok)++errors;else rawPon=value;
        bool wasDown=down.stable,wasUp=volume.stable;
        myronPonSample(state,down,ok,value);
        if(volumePad){rawVolume=volumePad[1]&1;__asm__ volatile("dmb oshld":::"memory");}
        volume.sample(volumePad!=nullptr,rawVolume==0);
        if(!wasUp && volume.stable)++volumeUpPresses;
        if(!wasDown && down.stable)++volumeDownPresses;
    }
};
