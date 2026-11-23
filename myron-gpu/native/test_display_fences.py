#!/usr/bin/env python3
"""Execute real fence query, board registration and display gate with host peers."""
import argparse, importlib.util, platform, subprocess, sys, tempfile, unittest
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device',type=Path,required=True);p.add_argument('--cxx',default='c++')
    a=p.parse_args();display=a.device.resolve()/'display'
    probe=(display/'MyronDisplayProbe.cpp').read_text()
    registration=probe[probe.index('static MyronGpuFenceQuery myronFenceProvider'):probe.index('extern "C" uint32_t native_ufs_dpu_map')]
    provider=(Path(__file__).parent/'MyronGpuFenceProvider.h').read_text()
    fixture=r'''
#include <cassert>
#include <cstdint>
#include "MyronGpuFence.h"
static volatile uint32_t myron_gpu_ready=0;
enum {NativeAdrenoRingFenceComplete=0,NativeAdrenoRingFenceTimeout=1,NativeAdrenoRingFencePoisoned=2};
static bool locked=false,busy=false;static unsigned unlocks=0,observations=0;
bool IOLockTryLock(void*){if(busy)return false;assert(!locked);locked=true;return true;}
void IOLockUnlock(void*){assert(locked);locked=false;++unlocks;}
struct Clock{};
struct Ring {
 bool bad=false;uint32_t submitted=10,retired=9;unsigned result=NativeAdrenoRingFenceTimeout;
 bool poisoned(){assert(locked);return bad;}
 uint32_t lastSubmitted(){assert(locked);return submitted;}
 unsigned observeFence(uint32_t target,const Clock*,uint32_t timeout,uint32_t*out){
  assert(locked && target==submitted && timeout==0);++observations;*out=retired;return result;
 }
} ring;
struct {bool published=true;Ring *ring=&::ring;Clock clock;void *lock=&::ring;} g;
''' + provider+'\n'+registration+r'''
static bool other(uint32_t*,uint32_t*,uint32_t*){return false;}
int main(){
 uint32_t submitted=99,retired=99,detail[3]={};
 assert(!native_legacy_has_gpu_fence_provider());
 assert(!myron_display_register_gpu_fences(nullptr));
 assert(myron_display_register_gpu_fences(myron_gpu_query_fences));
 assert(myron_display_register_gpu_fences(myron_gpu_query_fences));
 assert(!myron_display_register_gpu_fences(other));
 assert(native_legacy_has_gpu_fence_provider());
 assert(!native_adreno_fences_detail(&submitted,&retired,detail));
 assert(!submitted && !retired && !unlocks && !observations);
 myron_gpu_ready=1;busy=true;
 assert(!native_adreno_fences_detail(&submitted,&retired,detail) && detail[2]==2 && !unlocks);
 busy=false;
 assert(native_adreno_fences_detail(&submitted,&retired,detail));
 assert(submitted==10 && retired==9 && unlocks==1 && observations==1 && !locked);
 ring.result=NativeAdrenoRingFenceComplete;ring.retired=10;
 assert(native_adreno_fences(&submitted,&retired) && retired==10);
 ring.bad=true;assert(!native_adreno_fences(&submitted,&retired));ring.bad=false;
 ring.result=NativeAdrenoRingFencePoisoned;assert(!native_adreno_fences(&submitted,&retired));
 ring.submitted=0;assert(!native_adreno_fences(&submitted,&retired));
 g.published=false;assert(!native_adreno_fences(&submitted,&retired));g.published=true;
 assert(!native_adreno_fences(nullptr,&retired));
 myron_gpu_ready=0;
 assert(native_legacy_has_gpu_fence_provider()); // Never turn a failed GPU into CPU-only completion.
 assert(!native_adreno_fences(&submitted,&retired) && !locked);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        src=Path(tmp)/'provider.cpp';exe=Path(tmp)/'provider';src.write_text(fixture)
        subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',display,src,'-o',exe],check=True)
        subprocess.run([exe],check=True)
    sys.path[:0]=[str(display),str(a.device.resolve())]
    spec=importlib.util.spec_from_file_location('display_transport',display/'test_display_transport.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.CC=a.cxx
    names=['test_actual_fence_method_cpu_unknown_pending_complete_and_new_request']
    if platform.system()=='Darwin':names+=['test_real_arm64e_board_bindings_resolve_without_weak_thunks']
    suite=unittest.TestSuite(mod.TransportTests(name) for name in names)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():raise SystemExit(1)
    # Placement is material: no surface read, scaling, direct scanout or offer
    # may precede the common gate; blank frames need no producer surface.
    source=(display/'NativeLegacyDisplay.cpp').read_text()
    kick=source[source.index('    void kickOnce()'):source.index('    void finishTransfer(')]
    gate=kick.index('if(!gpuWrote(request))')
    for operation in ('if(scaled)', 'noteSurface(surface,memory)', 'directSlot(surface,memory)', 'native_legacy_gpu_offer(this,memory'):
        assert gate<kick.index(operation),operation
    assert source.count('if(!gpuWrote(request))')==1
    print('PASS: real producer query and common display gate; host peers only')

if __name__=='__main__':main()
