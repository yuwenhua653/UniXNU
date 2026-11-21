// SPDX-License-Identifier: GPL-2.0-only
#include <IOKit/hid/IOHIDDevice.h>
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOWorkLoop.h>
#include <libkern/c++/OSString.h>
#include "MyronFT3683.h"
#include "MyronTouchBoard.h"

static_assert(sizeof(IOHIDDevice) == 0xd0, "Wrong iPhone HID superclass ABI");

class MyronDigitizer : public IOHIDDevice {
    OSDeclareDefaultStructors(MyronDigitizer);
    struct Pad {
        IOMemoryMap *map;
        volatile uint32_t *regs;
        uint32_t config, latch;
    };
    Pad pads[PIN_COUNT]{};
    myron_gpio_io io{};
    myron_touch sensor{};
    IOTimerEventSource *timer = nullptr;
    IOWorkLoop *loop = nullptr;
    bool configured = false;
    unsigned readFailures = 0;
    unsigned idlePolls = 0;
    bool ownsLoop = false;
    bool firstReport = true;

    static uint32_t readPin(void *ctx, myron_pin pin, unsigned offset) {
        auto self = static_cast<MyronDigitizer *>(ctx);
        return self->pads[pin].regs[offset/4];
    }
    static void writePin(void *ctx, myron_pin pin, unsigned offset, uint32_t v) {
        auto self = static_cast<MyronDigitizer *>(ctx);
        self->pads[pin].regs[offset/4] = v;
        __asm__ volatile("dsb sy" ::: "memory");
    }
    static void delay(void *, unsigned us) { IODelay(us); }
    void configure(myron_pin pin, uint32_t config) {
        uint32_t old = pads[pin].config;
        // Canoe TLMM's normal GPIO pinmux ownership bit, as in pinctrl-msm.
        uint32_t upper = old & ~(0x3ffU | (1u << 12));
        if (pin <= CS) upper |= 1u << 11;
        if (upper & (1u << 11)) upper |= 1u << 12;
        writePin(this, pin, 0, upper | config);
    }
    void shutdownPads() {
        if (configured) {
            writePin(this, CS, 4, 2);
            for (int i = PIN_COUNT-1; i >= 0; --i) {
                auto pin = static_cast<myron_pin>(i);
                writePin(this, pin, 4, pads[i].latch);
                writePin(this, pin, 0, pads[i].config);
            }
            configured = false;
        }
        for (auto &pad : pads) { OSSafeReleaseNULL(pad.map); pad.regs = nullptr; }
    }
    bool openSensor() {
        // Map and snapshot every required pad before changing any of them.
        for (unsigned i=0; i<PIN_COUNT; ++i) {
            auto mem = IODeviceMemory::withRange(MYRON_TLMM_PADS + myron_gpio[i]*MYRON_PAD_STRIDE, 8);
            if (!mem) return false;
            pads[i].map = mem->map(kIOMapAnywhere | kIOMapInhibitCache);
            mem->release();
            if (!pads[i].map) return false;
            pads[i].regs = reinterpret_cast<volatile uint32_t *>(pads[i].map->getVirtualAddress());
            pads[i].config = pads[i].regs[0];
            pads[i].latch = pads[i].regs[1] & 2;
        }
        configured = true;
        writePin(this, RESET, 4, 0); configure(RESET, 0x240);
        IODelay(2000);
        writePin(this, AVDD, 4, 2); configure(AVDD, 0x240);
        configure(ATTENTION, 3); configure(MISO, 0x80);
        writePin(this, CS, 4, 2); configure(CS, 0x283);
        writePin(this, SCLK, 4, 0); configure(SCLK, 0x240);
        writePin(this, MOSI, 4, 0); configure(MOSI, 0x280);
        IODelay(3000);
        writePin(this, RESET, 4, 2);
        IOSleep(200);
        io = {this, readPin, writePin, delay};
        sensor.bus = {&io, myron_spi_transfer, delay};
        int rc = 0;
        for (unsigned attempt=0; attempt<5; ++attempt) {
            rc = myron_touch_identify_and_start(&sensor);
            if (!rc) {
                IOLog("myron-touch: controller %04x, TIC mode verified\n", (unsigned)sensor.chip_id);
                return true;
            }
            if (attempt < 4) IOSleep(200);
        }
        IOLog("myron-touch: controller/TIC probe failed (%d), ID %04x\n", rc, (unsigned)sensor.chip_id);
        return false;
    }
    static int submit(void *ctx, const uint8_t *bytes, size_t count) {
        auto self = static_cast<MyronDigitizer *>(ctx);
        auto buffer = IOBufferMemoryDescriptor::withBytes(bytes, count, kIODirectionIn);
        if (!buffer) return kIOReturnNoMemory;
        auto rc = self->handleReport(buffer, kIOHIDReportTypeInput, 0);
        buffer->release();
        if (self->firstReport) {
            IOLog("myron-touch: first HID submission, status 0x%x, contacts %u\n",
                  (unsigned)rc, (unsigned)bytes[count-1]);
            self->firstReport = false;
        }
        return rc;
    }
    static void tick(OSObject *owner, IOTimerEventSource *source) {
        auto self = OSDynamicCast(MyronDigitizer, owner);
        if (!self || !self->configured) return;
        unsigned next = 5;
        if (!self->sensor.ready) {
            next = myron_touch_identify_and_start(&self->sensor) == 0 ? 5 : 500;
        } else if (!(readPin(self, ATTENTION, 4) & 1) || ++self->idlePolls >= 20) {
            self->idlePolls = 0;
            int rc = myron_touch_read_contacts(&self->sensor, submit, self);
            if (!rc) self->readFailures = 0;
            else if (++self->readFailures >= 3) {
                if (myron_touch_release(&self->sensor, submit, self) == 0) {
                    self->readFailures = 0; self->sensor.ready = 0;
                }
                next = 100;
            }
        }
        source->setTimeoutMS(next);
    }
    void cancelTimer() {
        if (timer) {
            timer->cancelTimeout();
            if (loop) loop->removeEventSource(timer);
            OSSafeReleaseNULL(timer);
        }
    }
public:
    IOWorkLoop *getWorkLoop() const override { return loop; }
    OSString *newTransportString() const override { return OSString::withCString("SPI"); }
    OSString *newProductString() const override { return OSString::withCString("Myron FT3683"); }
    IOReturn newReportDescriptor(IOMemoryDescriptor **out) const override {
        if (!out) return kIOReturnBadArgument;
        *out = IOBufferMemoryDescriptor::withBytes(myron_touch_descriptor, myron_touch_descriptor_bytes, kIODirectionNone);
        return *out ? kIOReturnSuccess : kIOReturnNoMemory;
    }
    IOReturn getReport(IOMemoryDescriptor *out, IOHIDReportType type, IOOptionBits options) override {
        if (type != kIOHIDReportTypeFeature || (options & 255) != 4)
            return kIOReturnUnsupported;
        uint8_t report[] = {4, MYRON_FINGERS};
        return out && out->writeBytes(0, report, sizeof(report)) == sizeof(report) ?
            kIOReturnSuccess : kIOReturnNoSpace;
    }
    bool prepare(IOService *provider) {
        // Only a nub matched explicitly to this board is allowed to touch its pads.
        if (!provider || strcmp(provider->getName(), "myron-ft3683")) return false;
        if (!openSensor()) { shutdownPads(); return false; }
        setProperty("Built-In", kOSBooleanTrue);
        setProperty("DisplayIntegrated", kOSBooleanTrue);
        setProperty("HIDDefaultBehavior", kOSBooleanTrue);
        setProperty("DigitizerCollectionDispatch", kOSBooleanTrue);
        loop = IOWorkLoop::workLoop();
        ownsLoop = loop != nullptr;
        timer = IOTimerEventSource::timerEventSource(this, tick);
        if (!loop || !timer || loop->addEventSource(timer) != kIOReturnSuccess) {
            OSSafeReleaseNULL(timer);
            OSSafeReleaseNULL(loop); ownsLoop = false; shutdownPads(); return false;
        }
        return true;
    }
    void arm() {
        // IOHIDDevice::start retained this work loop before publishing interfaces.
        ownsLoop = false;
        loop->release();
        timer->setTimeoutMS(1);
    }
    void handleStop(IOService *) override { closeBoard(); }
    void closeBoard() {
        cancelTimer();
        myron_touch_release(&sensor, submit, this);
        shutdownPads();
        if (ownsLoop) { OSSafeReleaseNULL(loop); ownsLoop = false; }
    }
};
OSDefineMetaClassAndStructors(MyronDigitizer, IOHIDDevice)

extern "C" bool myron_publish_digitizer()
{
    IOService *parent = IOService::getResourceService();
    if (!parent) return false;
    IOService *nub = nullptr;
    MyronDigitizer *touch = nullptr;
    bool nubAttached = false, nubStarted = false, attached = false;
    nub = new IOService;
    touch = new MyronDigitizer;
    if (!nub || !touch || !nub->init() || !touch->init()) goto done;
    nub->setName("myron-ft3683");
    nubAttached = nub->attach(parent);
    if (!nubAttached) goto done;
    nubStarted = nub->start(parent);
    if (!nubStarted) goto done;
    attached = touch->attach(nub);
    if (!attached || !touch->prepare(nub) || !touch->start(nub)) goto done;
    touch->arm();
    touch->release();
    nub->release();
    return true;
done:
    if (attached) { touch->closeBoard(); touch->detach(nub); }
    if (nubStarted) nub->stop(parent);
    if (nubAttached) nub->detach(parent);
    OSSafeReleaseNULL(touch);
    OSSafeReleaseNULL(nub);
    return false;
}
