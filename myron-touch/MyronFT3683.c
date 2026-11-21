/* SPDX-License-Identifier: GPL-2.0-only */
/* Myron FT3683 TIC protocol, from the myron Android driver. */
#include "MyronFT3683.h"
#include "fts_myron_frame.h"
#ifdef KERNEL
#define memcpy __builtin_memcpy
#define memset __builtin_memset
#else
#include <string.h>
#endif

#define FINGER_COLLECTION \
    0x09,0x22,0xa1,0x02, /* Finger */ \
    0x09,0x42,0x15,0,0x25,1,0x75,1,0x95,1,0x81,2,0x09,0x47,0x81,2, \
    0x75,6,0x95,1,0x81,3, \
    0x09,0x51,0x25,9,0x75,8,0x95,1,0x81,2, \
    0x05,1,0x09,0x30,0x26,0xff,0x7f,0x75,16,0x95,1,0x81,2,0x09,0x31,0x81,2, \
    0xc0,0x05,0x0d
const uint8_t myron_touch_descriptor[] = {
    0x05,0x0d,0x09,0x04,0xa1,1,0x85,3, /* Digitizers / Touch Screen */
    FINGER_COLLECTION,FINGER_COLLECTION,FINGER_COLLECTION,FINGER_COLLECTION,FINGER_COLLECTION,
    FINGER_COLLECTION,FINGER_COLLECTION,FINGER_COLLECTION,FINGER_COLLECTION,FINGER_COLLECTION,
    0x09,0x54,0x25,10,0x75,8,0x95,1,0x81,2, /* Contact Count */
    0x85,4,0x09,0x55,0x25,10,0x75,8,0x95,1,0xb1,2,0xc0 /* Feature: maximum count */
};
const size_t myron_touch_descriptor_bytes = sizeof(myron_touch_descriptor);

static int exchange(struct myron_touch *t, uint8_t reg, int read, size_t payload)
{
    size_t total = 7 + payload + (read ? 2 : 0);
    int rc = -EIO;
    for (unsigned i = 0; i < 3; ++i) {
        memset(t->tx, 0, total);
        memset(t->rx, 0, total);
        t->tx[0] = reg;
        t->tx[1] = read ? 0xa0 : 0;
        t->tx[2] = (uint8_t)(payload >> 8);
        t->tx[3] = (uint8_t)payload;
        rc = t->bus.transfer(t->bus.context, t->tx, t->rx, total);
        t->bus.delay_us(t->bus.context, 150);
        if (rc) {
            t->bus.delay_us(t->bus.context, 2000);
            continue;
        }
        if (t->rx[3] & 0xa0) { rc = -EIO; continue; }
        if (!read) return 0;
        const uint8_t *end = t->rx + 7 + payload;
        if (fts_myron_crc(t->rx + 7, payload) == (uint16_t)(end[0] | end[1] << 8))
            return 0;
        rc = -EBADMSG;
    }
    return rc;
}

int myron_touch_identify_and_start(struct myron_touch *t)
{
    if (!t || !t->bus.transfer || !t->bus.delay_us) return -EINVAL;
    t->ready = 0;
    t->chip_id = 0;
    int rc = exchange(t, 0xa3, 1, 1);
    if (rc) return rc;
    unsigned high = t->rx[7];
    rc = exchange(t, 0x9f, 1, 1);
    if (rc) return rc;
    unsigned id = (high << 8) | t->rx[7];
    if (id != 0x3683 && id != 0x5672) return -ENODEV;
    t->chip_id = (uint16_t)id;
    for (unsigned i = 0; i < 3; ++i) {
        rc = exchange(t, 0x9e, 0, 1); /* volatile TIC mode = 0 */
        if (!rc) {
            t->bus.delay_us(t->bus.context, 1000);
            rc = exchange(t, 0x9e, 1, 1);
        }
        if (!rc && !t->rx[7]) { t->ready = 1; return 0; }
        if (!rc) rc = -EIO;
        t->bus.delay_us(t->bus.context, 1000);
    }
    return rc;
}

static uint16_t scale(uint32_t v, uint32_t maximum)
{
    return (uint16_t)(((uint64_t)v * 32767) / maximum);
}

static int submit_frame(struct myron_touch *t, const struct fts_myron_frame *f,
                        myron_hid_submit submit, void *context)
{
    uint16_t xs[MYRON_FINGERS], ys[MYRON_FINGERS];
    uint8_t report[MYRON_REPORT_BYTES] = {3};
    memcpy(xs, t->x, sizeof(xs));
    memcpy(ys, t->y, sizeof(ys));
    for (unsigned i = 0; i < f->count; ++i) {
        const struct fts_myron_contact *c = f->contacts + i;
        if (c->flag != 1) {
            xs[c->id] = scale(c->x, 119999);
            ys[c->id] = scale(c->y, 260799);
        }
    }
    /* Hardware IDs are 0..9. The union of old and new IDs always fits. */
    unsigned n = 0;
    const uint16_t groups[2] = {f->active, (uint16_t)(t->active & ~f->active)};
    for (unsigned group = 0; group < 2; ++group) {
        for (unsigned id = 0; id < MYRON_FINGERS; ++id) {
            if (!(groups[group] & (1u << id))) continue;
            uint8_t *contact = report + 1 + 6 * n++;
            contact[0] = group == 0 ? 3 : 2;
            contact[1] = (uint8_t)id;
            contact[2] = (uint8_t)xs[id];
            contact[3] = (uint8_t)(xs[id] >> 8);
            contact[4] = (uint8_t)ys[id];
            contact[5] = (uint8_t)(ys[id] >> 8);
        }
    }
    if (!n) return 0;
    report[sizeof(report)-1] = (uint8_t)n;
    int rc = submit(context, report, sizeof(report));
    if (!rc) {
        t->active = f->active;
        memcpy(t->x, xs, sizeof(xs));
        memcpy(t->y, ys, sizeof(ys));
    }
    return rc;
}
int myron_touch_read_contacts(struct myron_touch *t, myron_hid_submit submit, void *context)
{
    static const struct fts_myron_geometry geom = {0, 0, 119999, 260799, 100};
    struct fts_myron_frame frame;
    if (!t || !submit || !t->ready) return -ENODEV;
    int rc = exchange(t, 1, 1, MYRON_FRAME_BYTES);
    if (rc) return rc;
    const uint8_t *data = t->rx + 7;
    if (data[0] == 0xff && data[1] == 0xff) {
        rc = myron_touch_release(t, submit, context);
        if (!rc) t->ready = 0;
        return rc;
    }
    /* An empty TIC-v2 poll has no transitions. Only a contact snapshot or an
     * explicit UP/restart can release a finger that is resting on the panel. */
    if (data[1] == 0x20) return 0;
    if ((data[1] >> 4) == 0) {
        unsigned reported = data[1] & 15, down = 0, seen = 0;
        if (reported > MYRON_FINGERS) return -EBADMSG;
        memset(&frame, 0, sizeof(frame));
        for (unsigned i = 0; i < MYRON_FINGERS; ++i) {
            const uint8_t *p = data + 2 + i * 6;
            unsigned id = p[2] >> 4, flag = p[0] >> 6;
            if (id == 15) break;
            if (id >= MYRON_FINGERS || flag > 2 || (seen & (1u << id))) return -EBADMSG;
            seen |= 1u << id;
            struct fts_myron_contact *c = &frame.contacts[frame.count++];
            c->id = id;
            c->flag = flag;
            if (flag == 1) continue;
            c->x = (((p[0] & 15u) << 8) | p[1]) * geom.factor;
            c->y = (((p[2] & 15u) << 8) | p[3]) * geom.factor;
            if (c->x > geom.xmax || c->y > geom.ymax) return -ERANGE;
            frame.active |= 1u << id;
            ++down;
        }
        if (down != reported) return -EBADMSG;
        return submit_frame(t, &frame, submit, context);
    }
    rc = fts_myron_decode(data, MYRON_FRAME_BYTES, &geom, &frame);
    return rc ? rc : submit_frame(t, &frame, submit, context);
}
int myron_touch_release(struct myron_touch *t, myron_hid_submit submit, void *ctx)
{
    const struct fts_myron_frame frame = {0};
    if (!t || !submit) return -EINVAL;
    return submit_frame(t, &frame, submit, ctx);
}
