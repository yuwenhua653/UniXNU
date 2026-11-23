// SPDX-License-Identifier: BSD-2-Clause-Patent
// Original iPhone Metal discovery; no Apple AGX type-1 protocol emulation.
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSSymbol.h>
#include <mach/kmod.h>
#include <pexpert/pexpert.h>
extern "C" {
extern kmod_info_t g_kernel_kmod_info;
extern volatile uint32_t myron_gpu_ready;
volatile uint32_t myron_metal_stage, myron_metal_registered;
volatile int32_t myron_metal_status;
kern_return_t OSKextLoadKextWithIdentifier(const char *);
void myron_accelerator_init(void) __asm__("__GLOBAL__sub_I_MyronAcceleratorCandidate.cpp");
IOService *myron_accelerator_candidate_allocate(void);
const OSMetaClass *myron_accelerator_parent(void);
}
static unsigned claimed;
static uint32_t addonReady;
static IOService *published;
extern "C" void myron_gpu_publish_metal(void)
{
    unsigned enabled=0;
    // Packaging must opt in only with its matching trusted/installed addon.
    // A completed MMIO sequence alone cannot publish a usable Metal device.
    if(!__atomic_load_n(&myron_gpu_ready,__ATOMIC_ACQUIRE) ||
       !__atomic_load_n(&addonReady,__ATOMIC_ACQUIRE) ||
       !PE_parse_boot_argn("myron-gpu-metal",&enabled,sizeof enabled) || enabled!=1)return;
    if(__atomic_exchange_n(&claimed,1,__ATOMIC_ACQ_REL))return;
    myron_metal_stage=1;
    myron_metal_status=OSKextLoadKextWithIdentifier("com.apple.iokit.IOGPUFamily");
    if(myron_metal_status)return;
    const OSSymbol *name=OSSymbol::withCString("IOAcceleratorES");
    const OSMetaClass *parent=name?OSMetaClass::getMetaClassWithName(name):nullptr;
    OSSafeReleaseNULL(name);
    if(!parent || parent!=myron_accelerator_parent() || parent->getClassSize()!=136) {
        myron_metal_status=kIOReturnNotFound;return;
    }
    // Do not collide with an already registered Apple/other AGX implementation.
    name=OSSymbol::withCString("AGXAccelerator");
    const bool exists=name && OSMetaClass::getMetaClassWithName(name);
    const bool haveName=name!=nullptr;
    OSSafeReleaseNULL(name);
    if(!haveName || exists){myron_metal_status=kIOReturnExclusiveAccess;return;}
    myron_metal_stage=2;
    void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if(!handle){myron_metal_status=kIOReturnNoResources;return;}
    myron_accelerator_init();
    myron_metal_status=OSMetaClass::postModLoad(handle);
    if(myron_metal_status)return;
    myron_metal_stage=3;
    IOService *provider=IOService::getPlatform();
    IOService *service=myron_accelerator_candidate_allocate();
    if(!service){myron_metal_status=kIOReturnNoMemory;return;}
    if(!service->init()) {service->release();myron_metal_status=kIOReturnError;return;}
    if(!service->setProperty("MetalPluginName","NativeAdrenoMetal") ||
       !service->setProperty("MetalPluginClassName","NativeAdrenoMetalDevice") ||
       // Existing UniXNU service-scoped access facility, already in this kernel.
       // Only these render clients gain access to this device; no global grant.
       !service->setProperty("NativeSandboxGrantProcess",
           "backboardd,iconservicesagent,WidgetRenderer_Default,PosterBoard")) {
        service->release();myron_metal_status=kIOReturnNoMemory;return;
    }
    if(!provider || !service->attach(provider)) {
        service->release();myron_metal_status=kIOReturnNotAttached;return;
    }
    if(!service->start(provider)) {
        service->detach(provider);service->release();myron_metal_status=kIOReturnNotReady;return;
    }
    myron_metal_stage=4;
    // Keep ownership for the boot lifetime; GPU teardown is not qualified.
    published=service;
    service->registerService();
    myron_metal_status=kIOReturnSuccess;
    myron_metal_stage=5;
    __atomic_store_n(&myron_metal_registered,1,__ATOMIC_RELEASE);
}

// Either side may finish first. The once guard above arbitrates concurrent calls.
extern "C" void myron_gpu_addon_available(void)
{
    __atomic_store_n(&addonReady,1,__ATOMIC_RELEASE);
    myron_gpu_publish_metal();
}
