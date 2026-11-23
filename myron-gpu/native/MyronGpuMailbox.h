/* SPDX-License-Identifier: MIT */
#pragma once
#include "NativeAdrenoABI.h"

/* Versioned separately from NativeAdrenoABI: a 128-IB submit is 3104 bytes,
 * larger than the old MAIL transport's 1792-byte input. One 4 KiB page still
 * fits the complete request and the largest native reply. Old peers must
 * refuse this magic rather than use the old overlapping output offset. */
enum : unsigned {
    MyronMailboxMagic = 0x3249414d, /* MAI2 */
    MyronMailboxPageBytes = 4096,
    MyronMailboxInputOffset = 0x40,
    MyronMailboxInputBytes = sizeof(NativeAdrenoAbiSubmit),
    MyronMailboxOutputOffset = 0xc80,
    MyronMailboxOutputBytes = MyronMailboxPageBytes - MyronMailboxOutputOffset,
};
static_assert(MyronMailboxInputBytes == 3104, "128-IB A840 wire record");
static_assert(MyronMailboxInputOffset + MyronMailboxInputBytes <= MyronMailboxOutputOffset,
              "mailbox input and output must not overlap");
static_assert(sizeof(NativeAdrenoAbiDeviceInfo) <= MyronMailboxOutputBytes, "device reply capacity");
static_assert(sizeof(NativeAdrenoAbiMetadata) <= MyronMailboxOutputBytes, "metadata reply capacity");
