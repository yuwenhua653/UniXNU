// SPDX-License-Identifier: BSD-2-Clause-Patent
// Included inside NativeAdrenoPublish.cpp: same lock as submissions.
extern "C" bool myron_gpu_query_fences(uint32_t *submitted,uint32_t *retired,uint32_t *detail)
{
    if(!submitted || !retired || !detail)return false;
    *submitted=0;*retired=0;detail[0]=detail[1]=0;detail[2]=1;
    if(!__atomic_load_n(&myron_gpu_ready,__ATOMIC_ACQUIRE))return false;
    if(!g.lock || !IOLockTryLock(g.lock)){detail[2]=2;return false;}
    bool known=false;
    if(g.published && g.ring && !g.ring->poisoned()) {
        *submitted=g.ring->lastSubmitted();
        // Qualification already submitted real work. Zero is not completion.
        if(*submitted) {
            const auto result=g.ring->observeFence(*submitted,&g.clock,0,retired);
            detail[0]=static_cast<uint32_t>(result);
            known=result==NativeAdrenoRingFenceComplete || result==NativeAdrenoRingFenceTimeout;
        }
    }
    detail[2]=known?0:3;
    IOLockUnlock(g.lock);
    return known;
}
