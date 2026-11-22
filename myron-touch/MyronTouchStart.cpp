// SPDX-License-Identifier: GPL-2.0-only
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <mach/kmod.h>
#include <libkern/c++/OSMetaClass.h>

extern "C" {
extern kmod_info_t g_kernel_kmod_info;
kern_return_t OSKextLoadKextWithIdentifier(const char *);
void myron_digitizer_static_init() __asm__("__GLOBAL__sub_I_MyronDigitizer.cpp");
}

extern "C" bool myron_publish_digitizer();
extern "C" bool myron_publish_power_key();
static void startTouch(void *, wait_result_t)
{
    bool published = false;
    if (OSKextLoadKextWithIdentifier("com.apple.iokit.IOHIDFamily") == KERN_SUCCESS) {
        void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
        if (handle) {
            myron_digitizer_static_init();
            if (OSMetaClass::postModLoad(handle) == KERN_SUCCESS) {
                published = myron_publish_digitizer();
                IOLog("myron-power: %s\n",myron_publish_power_key()?"HID power button published":"PMIC key unavailable");
            }
        }
    }
    IOLog("myron-touch: %s\n", published ? "FT3683 identified, digitizer started" : "digitizer startup failed");
    thread_terminate(current_thread());
}
extern "C" void myron_touch_start()
{
    thread_t worker;
    if (kernel_thread_start(startTouch, nullptr, &worker) == KERN_SUCCESS)
        thread_deallocate(worker);
}
