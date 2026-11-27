// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef MYRON_GPU_POLICY_H
#define MYRON_GPU_POLICY_H
#include <stdint.h>

// This port owns 2 GiB, not the reference board's 4.75 GiB. The BO pool
// reservation is bounded independently of imported userspace pages.
enum { MYRON_GPU_POOL_MIB = 256, MYRON_GPU_BOOT_PERF = 7 };
// 256 MiB early pool plus at most 128 MiB reclaimable BO overflow. This does
// not raise per-object, VA-window, GPU OPP or imported-page limits.
enum { MYRON_GPU_OVERFLOW_BYTES = 128u * 1024u * 1024u };
// Vulkan's owned-memory heap shares the kernel's pool/overflow ceiling.
// This is capacity, not currently free memory, and not a per-client grant.
static inline uint64_t myron_gpu_heap_bytes(uint64_t system_heap_bytes)
{
    const uint64_t capacity = (uint64_t)MYRON_GPU_POOL_MIB * 1024u * 1024u +
                              MYRON_GPU_OVERFLOW_BYTES;
    return system_heap_bytes < capacity ? system_heap_bytes : capacity;
}
static inline unsigned myron_gpu_pool_mib(unsigned requested)
{
    return requested >= 16 && requested <= MYRON_GPU_POOL_MIB
        ? requested : (unsigned)MYRON_GPU_POOL_MIB;
}
// Index 7 is 422 MHz in the checked stock table, common to both speed bins.
// No user boot argument can raise this first bring-up's ceiling.
static inline unsigned myron_gpu_perf_level(unsigned requested, unsigned available)
{
    unsigned top = available < MYRON_GPU_BOOT_PERF ? available : (unsigned)MYRON_GPU_BOOT_PERF;
    return requested >= 1 && requested <= top ? requested : top;
}
static inline int myron_gpu_submission_ready(unsigned stage, int first, int second, int error, unsigned opened, unsigned closed)
{
    return stage == 10 && first == 4 && second == 4 && !error && opened == 2 && closed == 2;
}
#endif
