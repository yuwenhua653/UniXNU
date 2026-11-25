// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
struct MyronGpuRuntime {
    uint32_t available, opens, calls, selector, status, mailbox, inflight;
    uint32_t submitted, retired, poisoned;
    uint32_t pool[8], clients[5][6], methods[20][4];
    uint64_t waits[4];
};
extern "C" void myron_gpu_runtime(MyronGpuRuntime *);
