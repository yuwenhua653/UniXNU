/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MYRON_FT3683_H
#define MYRON_FT3683_H
#include <stddef.h>
#include <stdint.h>

#define MYRON_FINGERS 10
#define MYRON_REPORT_BYTES (1 + 6 * MYRON_FINGERS + 1)
#define MYRON_FRAME_BYTES (4 + 8 * MYRON_FINGERS)
#define MYRON_SPI_BYTES (7 + MYRON_FRAME_BYTES + 2)

struct myron_touch_bus {
    void *context;
    /* Exactly one full duplex transaction with CS low for its entire length. */
    int (*transfer)(void *, const uint8_t *, uint8_t *, size_t);
    void (*delay_us)(void *, unsigned);
};
struct myron_touch {
    struct myron_touch_bus bus;
    uint8_t tx[MYRON_SPI_BYTES], rx[MYRON_SPI_BYTES];
    uint16_t chip_id, active, x[MYRON_FINGERS], y[MYRON_FINGERS];
    int ready;
};
typedef int (*myron_hid_submit)(void *, const uint8_t *, size_t);
#ifdef __cplusplus
extern "C" {
#endif
/* Calls are serialized by the board worker. On disconnect send releases before reprobe. */
int myron_touch_identify_and_start(struct myron_touch *);
int myron_touch_read_contacts(struct myron_touch *, myron_hid_submit, void *);
int myron_touch_release(struct myron_touch *, myron_hid_submit, void *);
extern const uint8_t myron_touch_descriptor[];
extern const size_t myron_touch_descriptor_bytes;
#ifdef __cplusplus
}
#endif
#endif
