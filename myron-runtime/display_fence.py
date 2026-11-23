"""Connect the real producer fence to every validated display surface path."""
from pathlib import Path
import shutil


def apply(board, replace):
    display=board/'display'
    shutil.copyfile(board/'gpu/MyronGpuFence.h',display/'MyronGpuFence.h')
    replace(display/'MyronDisplayTransport.h','#include <stdint.h>',
            '#include <stdint.h>\n#include "MyronGpuFence.h"')
    replace(display/'MyronDisplayProbe.cpp',
        'extern "C" bool native_legacy_has_gpu_fence_provider(void) {return false;}\n'
        'extern "C" bool native_adreno_fences(uint32_t *,uint32_t *) {return false;}\n'
        'extern "C" bool native_adreno_fences_detail(uint32_t *,uint32_t *,uint32_t *) {return false;}',
        '''static MyronGpuFenceQuery myronFenceProvider=nullptr;
extern "C" bool myron_display_register_gpu_fences(MyronGpuFenceQuery query) {
    if(!query)return false;
    MyronGpuFenceQuery empty=nullptr;
    return __atomic_compare_exchange_n(&myronFenceProvider,&empty,query,false,
                                      __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE) || empty==query;
}
extern "C" bool native_legacy_has_gpu_fence_provider(void) {
    return __atomic_load_n(&myronFenceProvider,__ATOMIC_ACQUIRE)!=nullptr;
}
extern "C" bool native_adreno_fences_detail(uint32_t *submitted,uint32_t *retired,uint32_t *detail) {
    auto query=__atomic_load_n(&myronFenceProvider,__ATOMIC_ACQUIRE);
    return query && query(submitted,retired,detail);
}
extern "C" bool native_adreno_fences(uint32_t *submitted,uint32_t *retired) {
    uint32_t detail[3]={};return native_adreno_fences_detail(submitted,retired,detail);
}''')
    replace(display/'MyronDisplayProbe.cpp',
            '// No GPU transport is registered on this device. Always refuse the offer.',
            '// GPU copy-to-scanout is not enabled; producer fences are independent.')
    # Keep the existing standalone arm64e import-closure test covering the new
    # board-owned provider, including the atomic function pointer storage.
    replace(display/'test_display_transport.py',
            'source.index(\'extern "C" bool native_legacy_has_gpu_fence_provider\')',
            "source.index('static MyronGpuFenceQuery myronFenceProvider')")
    file=display/'NativeLegacyDisplay.cpp'
    replace(file,'    void startDirect() {','''    bool startFenceTimer() {
        if(fenceTimer)return true;
        IOWorkLoop *loop=getWorkLoop();
        if(!loop)return false;
        IOTimerEventSource *timer=IOTimerEventSource::timerEventSource(this,&NativeLegacyDisplay::fenceFired);
        if(!timer)return false;
        if(loop->addEventSource(timer)!=kIOReturnSuccess){timer->release();return false;}
        fenceTimer=timer;return true;
    }
    void stopFenceTimer() {
        if(fenceTimer) {
            fenceTimer->disable();fenceTimer->cancelTimeout();
            if(IOWorkLoop *loop=getWorkLoop())loop->removeEventSource(fenceTimer);
            OSSafeReleaseNULL(fenceTimer);
        }
        fenceFor=nullptr;fenceCaptured=false;traceGpuComplete=false;
    }
    void startDirect() {''')
    replace(file,'''        fenceTimer=loop?IOTimerEventSource::timerEventSource(this,&NativeLegacyDisplay::fenceFired):nullptr;
        if(!mdpMap || !directPages || !latchTimer || !fenceTimer || loop->addEventSource(fenceTimer)!=kIOReturnSuccess || loop->addEventSource(latchTimer)!=kIOReturnSuccess) {
            OSSafeReleaseNULL(mdpMap);OSSafeReleaseNULL(latchTimer);OSSafeReleaseNULL(fenceTimer);''','''        if(!mdpMap || !directPages || !latchTimer || !startFenceTimer() || loop->addEventSource(latchTimer)!=kIOReturnSuccess) {
            OSSafeReleaseNULL(mdpMap);OSSafeReleaseNULL(latchTimer);''')
    replace(file,'        const bool known=native_adreno_fences_detail(&submitted,&retired,detail);',
            '        if(!startFenceTimer())return false; // No unbounded work-loop wait or false retirement.\n'
            '        const bool known=native_adreno_fences_detail(&submitted,&retired,detail);')
    replace(file,'    void fenceTick() {transferred=false;kickSwapQueue();}',
            '    void fenceTick() {if(!fenceFor)return;transferred=false;kickSwapQueue();}')
    replace(file,'firmwareScanoutReady=false;stopVsync();if(logicalPM)',
            'firmwareScanoutReady=false;stopVsync();stopFenceTimer();if(logicalPM)')
    replace(file,'        if(fenceTimer){fenceTimer->cancelTimeout();if(IOWorkLoop *loop=getWorkLoop())loop->removeEventSource(fenceTimer);OSSafeReleaseNULL(fenceTimer);}',
            '        stopFenceTimer();')
    replace(file,'        if(scaled) {','''        // Producer completion precedes all CPU reads, scaling and direct scanout.
        // The original request validation, queue head and retirement gates remain.
        if(!gpuWrote(request)) {transferred=true;return;}
        if(scaled) {''')
    replace(file,'            if(!gpuWrote(request)) {transferred=true;return;}\n','')
    replace(display/'test_display_transport.py',
            '    void stat(unsigned){++stats;}',
            '    bool startFenceTimer(){return fenceTimer!=nullptr;}\n    void stat(unsigned){++stats;}')
