// SPDX-License-Identifier: BSD-2-Clause-Patent
// Appended to NativeAdrenoPublish.cpp; use its submission lock, never poll MMIO.
#include "MyronGpuRuntime.h"
extern "C" {
extern volatile uint32_t native_adreno_pool_stats[8];
extern volatile uint32_t native_adreno_client_stats[5][6];
extern volatile uint32_t native_adreno_method_stats[20][4];
extern volatile uint64_t native_adreno_wait_outer[4];
}
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
    for(unsigned i=0;i<8;++i)out->pool[i]=__atomic_load_n(&native_adreno_pool_stats[i],__ATOMIC_RELAXED);
    for(unsigned i=0;i<5;++i)for(unsigned j=0;j<6;++j)
        out->clients[i][j]=__atomic_load_n(&native_adreno_client_stats[i][j],__ATOMIC_RELAXED);
    for(unsigned i=0;i<20;++i)for(unsigned j=0;j<4;++j)
        out->methods[i][j]=__atomic_load_n(&native_adreno_method_stats[i][j],__ATOMIC_RELAXED);
    for(unsigned i=0;i<4;++i)out->waits[i]=__atomic_load_n(&native_adreno_wait_outer[i],__ATOMIC_RELAXED);
    if(g.ring){
        out->submitted=g.ring->lastSubmitted();out->retired=g.ring->completedFence();
        out->poisoned=g.ring->poisoned();
    }
    IOLockUnlock(g.lock);
}
