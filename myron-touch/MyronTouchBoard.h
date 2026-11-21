/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Myron stock DTBO and Typeun/myron-device d9b6be4, MyronTouchBoard.h.
 * The seven pads below belong to the internal digitizer.
 */
#ifndef MYRON_TOUCH_BOARD_H
#define MYRON_TOUCH_BOARD_H
#include <stdint.h>
#include <stddef.h>
enum myron_pin { MISO, MOSI, SCLK, CS, RESET, AVDD, ATTENTION, PIN_COUNT };
static const unsigned myron_gpio[PIN_COUNT] = {48,49,50,51,66,117,158};
#define MYRON_TLMM_PADS 0x0f100000ULL
#define MYRON_PAD_STRIDE 0x1000
struct myron_gpio_io {
    void *context;
    uint32_t (*read)(void *, enum myron_pin, unsigned);
    void (*write)(void *, enum myron_pin, unsigned, uint32_t);
    void (*delay_us)(void *, unsigned);
};
/* SPI mode 0: MSB first, sample MISO on the rising edge, hold CS across the
 * full command and response. These GPIO operations require no DMA mapping. */
static inline int myron_spi_transfer(void *ctx, const uint8_t *tx, uint8_t *rx, size_t count)
{
    struct myron_gpio_io *io = (struct myron_gpio_io *)ctx;
    io->write(io->context, CS, 4, 0);
    io->delay_us(io->context, 1);
    for (size_t i = 0; i < count; ++i) {
        unsigned byte = 0;
        for (unsigned mask = 0x80; mask; mask >>= 1) {
            io->write(io->context, MOSI, 4, (tx[i] & mask) ? 2 : 0);
            io->delay_us(io->context, 1);
            io->write(io->context, SCLK, 4, 2);
            io->delay_us(io->context, 1);
            byte = (byte << 1) | (io->read(io->context, MISO, 4) & 1);
            io->write(io->context, SCLK, 4, 0);
        }
        rx[i] = (uint8_t)byte;
    }
    io->write(io->context, CS, 4, 2);
    return 0;
}
#endif
