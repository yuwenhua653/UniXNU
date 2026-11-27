// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "MyronGpuPolicy.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    assert(myron_gpu_heap_bytes(UINT64_MAX) == UINT64_C(384)*1024*1024);
    assert(myron_gpu_heap_bytes(UINT64_C(2)*1024*1024*1024) == UINT64_C(384)*1024*1024);
    assert(myron_gpu_heap_bytes(UINT64_C(64)*1024*1024) == UINT64_C(64)*1024*1024);
    assert(myron_gpu_heap_bytes(0) == 0);
    assert(myron_gpu_pool_mib(0) == 256);
    assert(myron_gpu_pool_mib(16) == 16);
    assert(myron_gpu_pool_mib(128) == 128);
    assert(myron_gpu_pool_mib(1024) == 256);
    assert(myron_gpu_pool_mib(UINT32_MAX) == 256);
    for (unsigned available = 0; available <= 18; ++available)
        for (unsigned request = 0; request <= 20; ++request) {
            unsigned level = myron_gpu_perf_level(request, available);
            assert(level <= 7 && level <= available);
            assert(!available || level >= 1);
        }
    for (unsigned stage = 0; stage <= 11; ++stage)
        for (int first = -1; first <= 4; ++first)
            for (int second = -1; second <= 4; ++second)
                assert(myron_gpu_submission_ready(stage, first, second, 0, 2, 2) ==
                       (stage == 10 && first == 4 && second == 4));
    assert(!myron_gpu_submission_ready(10, 4, 4, 1, 2, 2));
    assert(!myron_gpu_submission_ready(10, 4, 4, 0, 2, 1));
    assert(!myron_gpu_submission_ready(10, 4, 4, 0, 1, 1));
    puts("PASS: bounded pool/OPP and both real client readbacks required");
}
