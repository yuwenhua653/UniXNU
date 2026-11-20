/*
 * Copyright (c) 2000 Apple Computer, Inc. All rights reserved.
 *
 * @APPLE_OSREFERENCE_LICENSE_HEADER_START@
 *
 * This file contains Original Code and/or Modifications of Original Code
 * as defined in and that are subject to the Apple Public Source License
 * Version 2.0 (the 'License'). You may not use this file except in
 * compliance with the License. The rights granted to you under the License
 * may not be used to create, or enable the creation or redistribution of,
 * unlawful or unlicensed copies of an Apple operating system, or to
 * circumvent, violate, or enable the circumvention or violation of, any
 * terms of an Apple operating system software license agreement.
 *
 * Please obtain a copy of the License at
 * http://www.opensource.apple.com/apsl/ and read it before using this file.
 *
 * The Original Code and all software distributed under the License are
 * distributed on an 'AS IS' basis, WITHOUT WARRANTY OF ANY KIND, EITHER
 * EXPRESS OR IMPLIED, AND APPLE HEREBY DISCLAIMS ALL SUCH WARRANTIES,
 * INCLUDING WITHOUT LIMITATION, ANY WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE, QUIET ENJOYMENT OR NON-INFRINGEMENT.
 * Please see the License for the specific language governing rights and
 * limitations under the License.
 *
 * @APPLE_OSREFERENCE_LICENSE_HEADER_END@
 */
/*
 *  appleboot.h - Apple logo shown during boot
 *
 *  Copyright (c) 2002 Apple Computer, Inc.
 *
 *  DRI: Josh de Cesare
 */

/* Modified for myron: monochrome row spans of Apple's indexed boot artwork.
 * Source: apple-oss-distributions/xnu, pexpert/pexpert/AppleBoot.h
 * The caller owns the 32-bit framebuffer and supplies its accessible byte size.
 */
#ifndef MYRON_BOOT_LOGO_H
#define MYRON_BOOT_LOGO_H
static const unsigned char myron_logo_spans[128][4] = {
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {77, 85, 0, 0},
  {75, 85, 0, 0},
  {74, 85, 0, 0},
  {72, 85, 0, 0},
  {71, 84, 0, 0},
  {70, 84, 0, 0},
  {69, 84, 0, 0},
  {68, 83, 0, 0},
  {67, 83, 0, 0},
  {67, 83, 0, 0},
  {66, 82, 0, 0},
  {65, 82, 0, 0},
  {65, 81, 0, 0},
  {64, 80, 0, 0},
  {64, 80, 0, 0},
  {64, 79, 0, 0},
  {63, 78, 0, 0},
  {63, 77, 0, 0},
  {63, 75, 0, 0},
  {63, 74, 0, 0},
  {63, 73, 0, 0},
  {63, 71, 0, 0},
  {63, 68, 0, 0},
  {43, 52, 80, 89},
  {39, 55, 76, 92},
  {37, 57, 73, 94},
  {35, 60, 70, 96},
  {34, 63, 66, 98},
  {32, 99, 0, 0},
  {31, 100, 0, 0},
  {30, 101, 0, 0},
  {29, 102, 0, 0},
  {28, 103, 0, 0},
  {27, 103, 0, 0},
  {27, 103, 0, 0},
  {26, 102, 0, 0},
  {25, 100, 0, 0},
  {25, 99, 0, 0},
  {24, 98, 0, 0},
  {24, 98, 0, 0},
  {23, 97, 0, 0},
  {23, 96, 0, 0},
  {22, 95, 0, 0},
  {22, 95, 0, 0},
  {22, 94, 0, 0},
  {22, 94, 0, 0},
  {21, 93, 0, 0},
  {21, 93, 0, 0},
  {21, 93, 0, 0},
  {21, 93, 0, 0},
  {21, 93, 0, 0},
  {21, 92, 0, 0},
  {21, 92, 0, 0},
  {21, 92, 0, 0},
  {21, 92, 0, 0},
  {21, 93, 0, 0},
  {21, 93, 0, 0},
  {21, 93, 0, 0},
  {21, 93, 0, 0},
  {21, 93, 0, 0},
  {21, 94, 0, 0},
  {21, 94, 0, 0},
  {21, 94, 0, 0},
  {21, 95, 0, 0},
  {21, 95, 0, 0},
  {21, 96, 0, 0},
  {22, 97, 0, 0},
  {22, 97, 0, 0},
  {22, 98, 0, 0},
  {22, 99, 0, 0},
  {23, 100, 0, 0},
  {23, 101, 0, 0},
  {23, 102, 0, 0},
  {24, 104, 0, 0},
  {24, 105, 0, 0},
  {24, 105, 0, 0},
  {25, 105, 0, 0},
  {25, 105, 0, 0},
  {25, 105, 0, 0},
  {26, 104, 0, 0},
  {26, 104, 0, 0},
  {27, 104, 0, 0},
  {27, 103, 0, 0},
  {28, 103, 0, 0},
  {28, 102, 0, 0},
  {29, 102, 0, 0},
  {30, 101, 0, 0},
  {30, 101, 0, 0},
  {31, 100, 0, 0},
  {32, 100, 0, 0},
  {32, 99, 0, 0},
  {33, 98, 0, 0},
  {34, 98, 0, 0},
  {34, 97, 0, 0},
  {35, 96, 0, 0},
  {36, 95, 0, 0},
  {37, 94, 0, 0},
  {38, 93, 0, 0},
  {39, 92, 0, 0},
  {40, 63, 70, 91},
  {41, 59, 73, 90},
  {43, 56, 76, 88},
  {45, 54, 79, 86},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
  {0, 0, 0, 0},
};
static inline int myron_draw_boot_logo(volatile unsigned int *frame, unsigned long long bytes,
                                       unsigned width, unsigned height, unsigned stride)
{
  if (!frame || width < 128 || width > 8192 || height < 128 || height > 8192 ||
      stride < width * 4 || stride > 65536 || (stride & 3) ||
      bytes < (unsigned long long)stride * height) return 0;
  unsigned scale = width >= 1024 && height >= 512 ? 2 : 1;
  unsigned left = (width - 128 * scale) / 2, top = (height - 128 * scale) / 2;
  for (unsigned y = 0; y < height; ++y) {
    volatile unsigned int *row = frame + (unsigned long long)y * (stride / 4);
    for (unsigned x = 0; x < width; ++x) row[x] = 0;
    if (y < top || y >= top + 128 * scale) continue;
    const unsigned char *span = myron_logo_spans[(y - top) / scale];
    for (unsigned i = 0; i < 4; i += 2)
      for (unsigned x = left + span[i] * scale; x < left + span[i+1] * scale; ++x)
        row[x] = 0x00ffffff;
  }
  return 1;
}
#endif
