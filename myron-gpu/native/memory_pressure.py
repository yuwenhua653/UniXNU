"""Allow a bounded, reclaimable overflow after the early BO pool fills."""
def patch(text, replace):
    text = replace(text, '#include "NativeAdrenoMemory.h"',
        '#include "NativeAdrenoMemory.h"\n#include "MyronGpuPolicy.h"')
    text = replace(text, 'extern "C" {volatile uint32_t native_adreno_pool_stats[8];}',
        'extern "C" {volatile uint32_t native_adreno_pool_stats[8];\n'
        'volatile uint32_t myron_gpu_overflow_stats[4];} // bytes, peak bytes, grants, refusals')
    text = replace(text, '    IOOptionBits options=static_cast<IOOptionBits>(kIODirectionInOut)', '''    // All callers serialize allocation/release under the resource gate. Keep
    // the early pool, but allow a finite amount of ordinary wired backing when
    // it fills. Unlike the pool, overflow pages return to VM on BO release.
    // Charge after descriptor creation and before prepare, so failed cleanup
    // and quarantined DMA memory continue to consume the budget.
    if(pooled && (bytes>MYRON_GPU_OVERFLOW_BYTES ||
        myron_gpu_overflow_stats[0]>MYRON_GPU_OVERFLOW_BYTES-bytes)) {
        ++myron_gpu_overflow_stats[3];return kIOReturnNoResources;
    }
    IOOptionBits options=static_cast<IOOptionBits>(kIODirectionInOut)''')
    text = replace(text, '    if(!descriptor_)return kIOReturnNoMemory;\n    status=descriptor_->prepare();', '''    if(!descriptor_)return kIOReturnNoMemory;
    if(pooled) {
        overflow_bytes_=bytes;
        myron_gpu_overflow_stats[0]+=(uint32_t)bytes;
        if(myron_gpu_overflow_stats[0]>myron_gpu_overflow_stats[1])
            myron_gpu_overflow_stats[1]=myron_gpu_overflow_stats[0];
        ++myron_gpu_overflow_stats[2];
    }
    status=descriptor_->prepare();''')
    text = replace(text, '    if(status!=kIOReturnSuccess) {descriptor_->release();descriptor_=nullptr;return status;}', '''    if(status!=kIOReturnSuccess) {
        descriptor_->release();descriptor_=nullptr;
        myron_gpu_overflow_stats[0]-=(uint32_t)overflow_bytes_;overflow_bytes_=0;
        return status;
    }''')
    text = replace(text, '        descriptor_->release();descriptor_=nullptr;\n        native_adreno_trace_stage=34;', '''        descriptor_->release();descriptor_=nullptr;
        myron_gpu_overflow_stats[0]-=(uint32_t)overflow_bytes_;overflow_bytes_=0;
        native_adreno_trace_stage=34;''')
    return text
