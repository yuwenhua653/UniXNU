/* SPDX-License-Identifier: GPL-2.0-only */
/* FT3683 protocol-v2 decoder. No I/O and no partial frame publication. */
#ifndef FTS_MYRON_FRAME_H
#define FTS_MYRON_FRAME_H

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/types.h>
#else
#ifdef KERNEL
#include <sys/errno.h>
#else
#include <errno.h>
#endif
#include <stddef.h>
#include <stdint.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#endif

#define FTS_MYRON_POINTS 10
#define FTS_MYRON_REPORT_LEN 3120U
#define FTS_MYRON_V2_BASE 4U
#define FTS_MYRON_V2_STRIDE 8U

struct fts_myron_contact {
	u32 x, y;
	u8 id, flag, major, minor;
};

struct fts_myron_frame {
	u16 active;
	u8 count;
	struct fts_myron_contact contacts[FTS_MYRON_POINTS];
};

struct fts_myron_geometry {
	u32 xmin, ymin, xmax, ymax, factor;
};

/* Vendor CRC: reflected 0x8408, initial 0xffff, no final xor. */
static inline u16 fts_myron_crc(const u8 *data, size_t len)
{
	u16 crc = 0xffff;
	unsigned int bit;

	while (len--) {
		crc ^= *data++;
		for (bit = 0; bit < 8; bit++)
			crc = (crc >> 1) ^ ((crc & 1) ? 0x8408 : 0);
	}
	return crc;
}

static inline int fts_myron_decode(const u8 *buf, size_t len,
				   const struct fts_myron_geometry *g,
				   struct fts_myron_frame *out)
{
	struct fts_myron_frame frame = { 0 };
	u16 seen = 0;
	unsigned int i;

	if (len < FTS_MYRON_V2_BASE || !g->factor || g->factor > 100 ||
	    g->xmin >= g->xmax || g->ymin >= g->ymax)
		return -EINVAL;
	if ((buf[1] >> 4) != 2)
		return -EPROTO;
	frame.count = buf[1] & 0x0f;
	/* V2 counts events, including UP; zero is not a proven all-up frame. */
	if (!frame.count || frame.count > FTS_MYRON_POINTS)
		return -EBADMSG;
	if (len < FTS_MYRON_V2_BASE + frame.count * FTS_MYRON_V2_STRIDE)
		return -EMSGSIZE;
	for (i = 0; i < frame.count; i++) {
		const u8 *p = buf + FTS_MYRON_V2_BASE + i * FTS_MYRON_V2_STRIDE;
		struct fts_myron_contact *c = &frame.contacts[i];
		u32 raw_x, raw_y;

		c->id = p[2] >> 4;
		c->flag = p[0] >> 6;
		if (c->id >= FTS_MYRON_POINTS || c->flag > 2 ||
		    (seen & (1U << c->id)))
			return -EBADMSG;
		seen |= 1U << c->id;
		raw_x = ((u32)(p[0] & 15) << 12) | ((u32)p[1] << 4) | (p[4] >> 4);
		raw_y = ((u32)(p[2] & 15) << 12) | ((u32)p[3] << 4) | (p[4] & 15);
		/* Preserve stock precision: multiply first, then divide by 16. */
		c->x = (raw_x * g->factor) >> 4;
		c->y = (raw_y * g->factor) >> 4;
		c->major = p[5] ? p[5] : 9;
		c->minor = p[6] ? p[6] : 9;
		if (c->flag != 1) {
			if (c->x < g->xmin || c->x > g->xmax ||
			    c->y < g->ymin || c->y > g->ymax)
				return -ERANGE;
			frame.active |= 1U << c->id;
		}
		/* UP coordinates are not consumed by the input reporter. */
	}
	*out = frame;
	return 0;
}
#endif
