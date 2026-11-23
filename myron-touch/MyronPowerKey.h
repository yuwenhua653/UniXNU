// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <stdint.h>
// myron PMK8850 pon_hlos@1300, SID0 RT_STS bit7. SPMI v8 EE0
// observer address/layout verified against stock 3.0.306 and Linux arbiter.
struct MyronPowerDebounce {
    bool armed=false, previous=false, stable=false, delivered=false;
    unsigned equal=0, failures=0;
    void sample(bool valid, bool down) {
        if(!valid){equal=0;if(++failures>=2){stable=false;armed=false;}return;}
        failures=0;
        if(!equal || previous!=down){previous=down;equal=1;return;}
        if(equal<2)++equal;
        if(!armed){if(!down)armed=true;stable=false;return;}
        stable=down;
    }
    bool pending() const {return stable!=delivered;}
    void accepted(){delivered=stable;}
};
template<class IO> static bool myronPowerRead(IO &io,uint16_t apid,uint8_t *value) {
    if(apid>=8192 || !value)return false;
    uint32_t off=0x20u*apid;
    io.write(off,(1u<<27)|(0x10u<<4)); // EXT_READL, one byte; never PMIC write
    for(unsigned i=0;i<500;++i){
        uint32_t status=io.read(off+8);
        if(status&0x0e)return false;
        if(status&1){*value=(uint8_t)io.read(off+0x18);return true;}
        io.delay();
    }return false;
}
static const uint8_t myron_power_descriptor[]={
    0x05,0x0c,0x09,0x01,0xa1,0x01, // Consumer Control
    0x85,0x05,0x09,0x30,0x09,0xe9,0x09,0xea, // Power, Volume Up, Volume Down
    0x15,0x00,0x25,0x01,0x75,0x01,0x95,0x03,0x81,0x02,
    0x75,0x05,0x95,0x01,0x81,0x03,0xc0
};

static inline uint8_t myronButtonBits(const MyronPowerDebounce &power,const MyronPowerDebounce &volume,
                                     const MyronPowerDebounce &down) {
    return (power.stable?1u:0u)|(volume.stable?2u:0u)|(down.stable?4u:0u);
}
static inline void myronPonSample(MyronPowerDebounce &power,MyronPowerDebounce &down,
                                  bool valid,uint8_t status) {
    // PMK8850 pon_hlos@1300: PWRKEY bit 7; RESIN/KEY_VOLUMEDOWN bit 6.
    power.sample(valid,(status&0x80)!=0);
    down.sample(valid,(status&0x40)!=0);
}
