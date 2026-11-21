// SPDX-License-Identifier: BSD-2-Clause-Patent
// Myron QUP4 SE0 and GCC offsets from the board DT and gcc-kaanapali.
// Use the programmed clock root, including its current DFS level.
#ifndef MYRON_SE19_BUS_H
#define MYRON_SE19_BUS_H
extern "C" {
#include "GeniSpi.h"
}

class MyronSE19Bus {
    enum Window { Pll, Vote, Ahb, Root, Wrapper, Engine, Count };
    IOMemoryMap *maps[Count]{};
    geni_spi spi{};
    uint32_t addedBranches = 0, addedPll = 0;
    static constexpr uint32_t branches = 0x1fu << 22;
    static uint32_t read(void *ctx, unsigned off) {
        return static_cast<volatile uint32_t *>(ctx)[off/4];
    }
    static void write(void *ctx, unsigned off, uint32_t value) {
        static_cast<volatile uint32_t *>(ctx)[off/4] = value;
        __asm__ volatile("dsb sy" ::: "memory");
    }
    static void delay(void *, unsigned us) { IODelay(us); }
    void *regs(Window w) const { return reinterpret_cast<void *>(maps[w]->getVirtualAddress()); }
    uint32_t reg(Window w, unsigned off) const { return read(regs(w), off); }
    bool clocksOn() const {
        uint32_t m = reg(Ahb, 0x548), s = reg(Ahb, 0x54c);
        return (!(m >> 31) || (m & 2)) && (!(s >> 31) || (s & 2)) &&
               !(reg(Ahb, 0x550) >> 31) && !(reg(Ahb, 0x564) >> 31) &&
               !(reg(Root, 4) >> 31);
    }
    unsigned sourceHz(unsigned &level) const {
        const unsigned rcg = 0x14;
        uint32_t dfs = reg(Root, rcg+0x14);
        level = (dfs & 1) ? ((dfs >> 1) & 15) : 0;
        if (level >= 8) return 0;
        unsigned cfg = reg(Root, rcg+((dfs & 1) ? 0x1c+4*level : 4));
        unsigned sel = (cfg >> 8) & 7, hid = cfg & 31;
        uint64_t hz = sel == 0 ? 19200000 : sel == 1 ? 600000000 : sel == 6 ? 300000000 : 0;
        if (hid) hz = hz*2/(hid+1);
        if ((cfg >> 12) & 3) {
            unsigned m = reg(Root, rcg+((dfs & 1) ? 0x5c+4*level : 8)) & 65535;
            unsigned n = (~reg(Root, rcg+((dfs & 1) ? 0x9c+4*level : 12)) & 65535) + m;
            if (!n || !m) return 0;
            hz = hz*m/n;
        }
        return (unsigned)hz;
    }
public:
    using Map = IOMemoryMap *(*)(uint64_t, unsigned);
    int open(Map map) {
        static const uint64_t base[Count] = {0x100000,0x152000,0x123000,0x1a9000,0x1ac0000,0x1a80000};
        for (unsigned i=0; i<Count; ++i) {
            maps[i]=map(base[i],0x1000);
            if (!maps[i]) return GENI_ERR_NODEV;
        }
        if (!(reg(Pll,0) >> 31)) {
            uint32_t old = reg(Vote,0x20);
            addedPll = ~old & 1;
            write(regs(Vote),0x20,old|1);
            for (unsigned i=0; i<2000 && !(reg(Pll,0)>>31); ++i) IODelay(10);
            if (!(reg(Pll,0)>>31)) return GENI_ERR_TIMEOUT;
        }
        uint32_t old = reg(Vote,0x18);
        addedBranches = ~old & branches;
        write(regs(Vote),0x18,old|branches);
        for (unsigned i=0; i<2000 && !clocksOn(); ++i) IODelay(10);
        if (!clocksOn()) return GENI_ERR_TIMEOUT;
        spi.se = {regs(Engine),read,write,delay};
        spi.wrapper = {regs(Wrapper),read,nullptr,delay};
        if (geni_spi_read_info(&spi) || spi.info.protocol != GENI_PROTO_SPI) return GENI_ERR_PROTO;
        if (spi.info.geni_status & (GENI_STATUS_M_ACTIVE | (1u << 12))) return GENI_ERR_IO;
        if (spi.info.fifo_disabled) return GENI_ERR_NOTSUP;
        unsigned selector;
        unsigned hz = sourceHz(selector);
        if (!hz) return GENI_ERR_NODEV;
        spi.poll_limit = 2000;
        spi.poll_only = 2;
        int rc = geni_spi_init(&spi);
        if (!rc) rc = geni_spi_set_clock(&spi,9600000,hz,selector);
        if (!rc) rc = geni_spi_setup(&spi,0,0);
        return rc;
    }
    static int transfer(void *ctx,const uint8_t *tx,uint8_t *rx,size_t bytes) {
        auto self = static_cast<MyronSE19Bus *>(ctx);
        return geni_spi_transfer(&self->spi,tx,rx,bytes,0);
    }
    void close() {
        if (addedBranches) write(regs(Vote),0x18,reg(Vote,0x18)&~addedBranches);
        if (addedPll) write(regs(Vote),0x20,reg(Vote,0x20)&~addedPll);
        addedBranches=addedPll=0;
        for (auto &map : maps) OSSafeReleaseNULL(map);
    }
};
#endif
