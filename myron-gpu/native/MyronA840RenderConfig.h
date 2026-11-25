// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
// myron 0x44050a31: KGSL writes all ones to the busy-counter mask, but
// the device readback is 0x3ff. Keep that upstream
// write and compare the entire returned word, including unexpected high bits.
#define MYRON_A840_GPU_BUSY_READBACK 0x000003ffu
// SM8850 KGSL gen8_start, UBWC 6.0: mode2=5, yuvnotcomptofc=1,
// amsbc=rgb565_predicator=rgba8888_lossless=fp16compoptdis=0, MAL=32.
// RB_CMP bits 1/2 are compression features, NOT RB_CCU's bank-bit fields.
// Keep full-word verification: the old generated 0x28046 enabled UBWC5 flags.
#define MYRON_A840_RB_CMP_UBWC6 ((5u << 15) | (1u << 6))
#define MYRON_A840_BICUBIC_BASE 0x0b606u
// gen8_0_0_bicubic_regs, also used by gen8_start on gen8.2. Index zero
// retains the documented default; all twenty registers are installed once.
static const uint32_t MyronA840Bicubic[20] = {
    0x00000000, 0x3fe05ff4, 0x3fa0ebee, 0x3f5193ed, 0x3f0243f0,
    0x00000000, 0x3fd093e8, 0x3f4133dc, 0x3ea1dfdb, 0x3e0283e0,
    0x0000ac2b, 0x0000f01d, 0x00114412, 0x0021980a, 0x0051ec05,
    0x0000380e, 0x3ff09001, 0x3fc10bfa, 0x3f9193f7, 0x3f7227f7,
};
