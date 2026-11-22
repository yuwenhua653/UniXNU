// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>

// The existing display remains responsible for real surface retirement.
// This backend has not implemented the reference GPU scanout tunnel. Never
// acknowledge a frame, expose framebuffer memory, or manufacture a fence.
extern "C" IOReturn native_gop_handoff_call(uint32_t, task_t, const void *, size_t, void *, size_t)
{
    return kIOReturnUnsupported;
}
extern "C" IOMemoryDescriptor *native_gop_handoff_memory(void)
{
    return nullptr;
}
