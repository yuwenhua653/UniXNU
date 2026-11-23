// SPDX-License-Identifier: BSD-2-Clause-Patent
// iPhone12,1 / 24A446 declaration: 136 bytes, 168 IOService slots,
// no additional operational base overrides. Compiled and audited separately;
// do not link or publish until the target bindings and Metal addon qualify.
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
class IOAcceleratorES : public IOService {
    OSDeclareAbstractStructors(IOAcceleratorES)
};
static_assert(sizeof(IOService)==136 && sizeof(IOAcceleratorES)==136,
              "iPhone 24A446 accelerator base extent");
extern "C" IOReturn native_adreno_new_user_client(IOService *,task_t,void *,UInt32,
    OSDictionary *,IOUserClient **,unsigned);
extern "C" volatile uint32_t myron_gpu_ready;

class AGXAccelerator : public IOAcceleratorES {
    OSDeclareDefaultStructors(AGXAccelerator)
public:
    IOReturn newUserClient(task_t,void *,UInt32,OSDictionary *,IOUserClient **) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(AGXAccelerator,IOAcceleratorES)
IOReturn AGXAccelerator::newUserClient(task_t task,void *security,UInt32 type,
    OSDictionary *properties,IOUserClient **handler)
{
    if(!handler)return kIOReturnBadArgument;
    *handler=nullptr;
    if(!__atomic_load_n(&myron_gpu_ready,__ATOMIC_ACQUIRE))return kIOReturnNotReady;
    // The original AGX type-1 protocol is not this driver's wire ABI.
    // The separate display handoff remains disabled.
    if(type!=0x4147)return kIOReturnUnsupported;
    return native_adreno_new_user_client(this,task,security,type,properties,handler,40);
}
extern "C" IOService *myron_accelerator_candidate_allocate(void) {return new AGXAccelerator;}
