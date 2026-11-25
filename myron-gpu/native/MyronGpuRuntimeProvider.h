// SPDX-License-Identifier: BSD-2-Clause-Patent
// Appended to NativeAdrenoPublish.cpp; use its submission lock, never poll MMIO.
#include "MyronGpuRuntime.h"
extern "C" void myron_gpu_runtime(MyronGpuRuntime *out)
{
    if(!out)return;
    *out={};
    if(!g.lock || !IOLockTryLock(g.lock))return;
    out->available=1;
    // Counters are observational; some callers update them outside this lock.
    out->opens=__atomic_load_n(&native_adreno_metal_diag.opens,__ATOMIC_RELAXED);
    out->calls=__atomic_load_n(&native_adreno_metal_diag.calls,__ATOMIC_RELAXED);
    out->selector=__atomic_load_n(&native_adreno_metal_diag.last_selector,__ATOMIC_RELAXED);
    out->status=__atomic_load_n(&native_adreno_metal_diag.last_status,__ATOMIC_RELAXED);
    out->mailbox=__atomic_load_n(&native_adreno_metal_diag.mb_calls,__ATOMIC_RELAXED);
    out->inflight=__atomic_load_n(&native_adreno_metal_diag.inflight,__ATOMIC_RELAXED);
    if(g.ring){
        out->submitted=g.ring->lastSubmitted();out->retired=g.ring->completedFence();
        out->poisoned=g.ring->poisoned();
    }
    IOLockUnlock(g.lock);
}
