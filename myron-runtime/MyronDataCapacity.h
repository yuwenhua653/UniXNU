// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "MyronDataGrowth.h"

// Expand only the pointer index after hashing the ORIGINAL immutable seed.
// New slots are zero; DirectDisk reads them as zero unless the overlay has a
// durable page. This allocates 32 MiB of pointers, never a 16 GiB RAM disk.
template<class Disk,class Alloc>
static bool myronDataExpandSeed(Disk &disk,uint64_t capacity,Alloc &alloc) {
    if(capacity==disk.bytes)return true;
    if(disk.bytes!=MyronDataSeedBytes || capacity!=MyronDataGrownBytes || !disk.pages)return false;
    const uint64_t oldBytes=(disk.bytes/4096)*sizeof(*disk.pages);
    const uint64_t newBytes=(capacity/4096)*sizeof(*disk.pages);
    auto pages=static_cast<unsigned char **>(alloc.zero(newBytes));
    if(!pages)return false;
    memcpy(pages,disk.pages,oldBytes);
    alloc.release(disk.pages,oldBytes);
    disk.pages=pages;disk.bytes=capacity;return true;
}
