// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
struct MyronGpuRuntime {
    uint32_t available, opens, calls, selector, status, mailbox, inflight;
    uint32_t submitted, retired, poisoned;
};
extern "C" void myron_gpu_runtime(MyronGpuRuntime *);
