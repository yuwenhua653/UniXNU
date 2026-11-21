/* SPDX-License-Identifier: GPL-2.0-only */
/* myron's FT3683 I/O rail: stock Canoe DT, cmd-db and rpmh-rsc. */
#ifndef MYRON_TOUCH_POWER_H
#define MYRON_TOUCH_POWER_H
#ifdef MYRON_TOUCH_EDK2
typedef UINT32 uint32_t;
#else
#include <stdint.h>
#endif

#define MYRON_CMD_DB 0x81c60000ULL
#define MYRON_CMD_DB_BYTES 0x20000u
#define MYRON_APPS_DRV2 0x18920000ULL
#define MYRON_APPS_DRV_BYTES 0x2000u /* DRV header and its three active TCS windows */
enum myron_power_result { MYRON_POWER_OK, MYRON_POWER_DB, MYRON_POWER_LAYOUT,
    MYRON_POWER_BUSY, MYRON_POWER_TIMEOUT, MYRON_POWER_RESPONSE, MYRON_POWER_MAP };
struct myron_rsc_io {
    void *context;
    uint32_t (*read)(void *, unsigned);
    void (*write)(void *, unsigned, uint32_t);
    void (*delay_us)(void *, unsigned);
};

/* Read only aligned words from the uncached AOP RAM window. Identify both
 * the resource name and its VRM slave. Reject ambiguous or truncated tables. */
static inline uint32_t myron_l4i_address(const volatile uint32_t *db, uint32_t bytes)
{
    const unsigned start = 144;
    uint32_t found = 0;
    if (!db || bytes < start || db[1] != 0x0c0330db || (db[35] & 1)) return 0;
    for (unsigned s = 0; s < 8; ++s) {
        uint32_t header = db[2 + 4*s], limits = db[3 + 4*s];
        unsigned slave = header & 0xffff, count = limits >> 16;
        if (!slave) break;
        unsigned off = start + (header >> 16);
        if ((off & 3) || off > bytes || count > (bytes-off)/24) return 0;
        if (slave != 4) continue;
        for (unsigned e = 0; e < count; ++e) {
            const volatile uint32_t *entry = db + off/4 + 6*e;
            if (entry[0] != 0x5f49344c || entry[1] != 0x3045) continue; /* L4I_E0 */
            uint32_t address = entry[4];
            if (found || (address & 15) || ((address >> 16) & 15) != 4) return 0;
            found = address;
        }
    }
    return found;
}

static inline int myron_power_sync(const struct myron_rsc_io *io, unsigned offset, uint32_t value)
{
    io->write(io->context, offset, value);
    for (unsigned i = 0; i < 100; ++i) {
        if (io->read(io->context, offset) == value) return 1;
        io->delay_us(io->context, 1);
    }
    return 0;
}

static inline int myron_vote_l4i(const struct myron_rsc_io *io, uint32_t address)
{
    /* Stock drv@2 channel@0 assigns the first three TCSes to active requests.
     * This image's touchscreen is its only AP RSC client. Do not borrow any
     * sleep/wake sets or overwrite inherited work. */
    const unsigned base = 0xd00, stride = 0x2a0;
    void *ctx = io->context;
    if ((address & 15) || ((address >> 16) & 15) != 4) return MYRON_POWER_DB;
    uint32_t id = io->read(ctx, 0), config = io->read(ctx, 0x0c);
    unsigned commands = (config >> 27) & 31;
    unsigned major = (id >> 16) & 255;
    if (major < 2 || major == 255 || config == 0xffffffffu ||
        ((config >> 12) & 63) < 3 || commands < 3) return MYRON_POWER_LAYOUT;

    /* Canoe rpmh-rsc uses the 2.x or 3-and-later register layout based
     * on the HW ID. DT fixes the TCS stride for both layouts. */
    const unsigned wait = major == 2 ? 0x10 : 0x20;
    const unsigned msg = major == 2 ? 0x30 : 0x34;
    const unsigned cmdStride = major == 2 ? 20 : 24;
    /* Include the last slot if its five 32-bit registers fit before the next TCS. */
    const unsigned mappedCommands = 1 + (stride - msg - 5 * sizeof(uint32_t)) / cmdStride;
    const unsigned readable = commands < mappedCommands ? commands : mappedCommands;
    unsigned slot = 3;
    for (unsigned i = 0; i < 3; ++i) {
        unsigned t = base + i*stride;
        uint32_t enable = io->read(ctx, t+wait+12);
        if (enable) {
            /* An enabled command outside this TCS cannot be inspected. */
            if (enable >> readable) return MYRON_POWER_BUSY;
            for (unsigned c = 0; c < readable; ++c) {
                if ((enable & (1u << c)) &&
                    (io->read(ctx, t+msg+4+cmdStride*c) & ~15u) == address)
                    return MYRON_POWER_BUSY;
            }
        } else if (io->read(ctx, t+wait+8) == 1 && !(io->read(ctx, base+4) & (1u << i))) {
            slot = i;
        }
    }
    if (slot == 3) return MYRON_POWER_BUSY;
    unsigned t = base + slot*stride, bit = 1u << slot;
    uint32_t control = io->read(ctx, t+wait+4), irq = io->read(ctx, base);
    if (!myron_power_sync(io, t+wait+4, control & ~(1u<<24)) ||
        !myron_power_sync(io, t+wait+4, 0)) return MYRON_POWER_RESPONSE;
    /* Canoe uses qcom,rpmh-regulator-levels.h. Its DT value 3 is AUTO,
     * mapped to PMIC7 LDO OPM (5) by the downstream rpmh-regulator driver.
     * Apply voltage and mode before enabling the rail. */
    const uint32_t offsets[3] = {0, 8, 4}, values[3] = {1800, 5, 1};
    for (unsigned c = 0; c < 3; ++c) {
        unsigned cmd = t + msg + cmdStride*c;
        io->write(ctx, cmd, 0x10108); /* WRITE, response required */
        io->write(ctx, cmd+4, address+offsets[c]);
        io->write(ctx, cmd+8, values[c]);
    }
    io->write(ctx, t+wait, 7);
    io->write(ctx, t+wait+12, 7);
    io->write(ctx, base, irq | bit);
    if (!myron_power_sync(io, t+wait+4, 1u<<16)) {
        io->write(ctx, t+wait+12, 0);
        io->write(ctx, t+wait, 0);
        io->write(ctx, base, irq);
        return MYRON_POWER_RESPONSE;
    }
    io->write(ctx, t+wait+4, (1u<<16) | (1u<<24));
    for (unsigned poll = 0; poll < 2000; ++poll) {
        if ((io->read(ctx, base+4) & bit) && io->read(ctx, t+wait+8) == 1) {
            int status = MYRON_POWER_OK;
            for (unsigned c = 0; c < 3; ++c)
                if ((io->read(ctx, t+msg+12+cmdStride*c) & 0x10100) != 0x10100)
                    status = MYRON_POWER_RESPONSE;
            /* RSC requires trigger clear before clearing AMC enable. Firmware
             * and the kernel can now reuse this same active TCS. */
            if (!myron_power_sync(io, t+wait+4, 1u<<16) ||
                !myron_power_sync(io, t+wait+4, 0)) status = MYRON_POWER_RESPONSE;
            io->write(ctx, t+wait+12, 0);
            io->write(ctx, t+wait, 0);
            io->write(ctx, base+8, bit);
            io->write(ctx, base, irq);
            return status;
        }
        io->delay_us(ctx, 10);
    }
    /* A timed-out transfer can still be in flight. Leave its slot intact. */
    io->write(ctx, base, irq);
    return MYRON_POWER_TIMEOUT;
}
#endif
