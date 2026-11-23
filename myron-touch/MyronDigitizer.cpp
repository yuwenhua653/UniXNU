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
#include "MyronTouchPower.h"
#include "MyronSE19Bus.h"
#include "MyronPowerHardware.h"

/* The periodic boot snapshot outlives the early kernel message ring. */
static uint32_t rscId, rscConfig, touchChip, hidReports;
static int railResult = -1, probeResult = -1, busResult = -1;
static uint64_t keyObservedUs, keyAcceptedUs, keyMaxPollGapUs;
static uint32_t keyReports, keyErrors, keyStable;
static uint32_t keyPon, keyVolumeLevel=1, keyVolumeConfig, keyVolumeAvailable;
static uint32_t keyVolumeUpPresses, keyVolumeDownPresses;
static int keyStatus;

extern "C" size_t myron_touch_snapshot(char *out, size_t cap) {
    if (!out || !cap) return 0;
    int n = snprintf(out, cap, "[myron touch] se=%d rail=%d rsc_id=%08x config=%08x probe=%d chip=%04x hid_reports=%u\n[myron key] bits=%u reports=%u errors=%u status=%d observed_us=%llu accepted_us=%llu max_poll_gap_us=%llu pon=%02x vol_up_ready=%u cfg=%08x level=%u up_presses=%u down_presses=%u\n",
        __atomic_load_n(&busResult,__ATOMIC_RELAXED), __atomic_load_n(&railResult,__ATOMIC_RELAXED),
        __atomic_load_n(&rscId,__ATOMIC_RELAXED), __atomic_load_n(&rscConfig,__ATOMIC_RELAXED),
        __atomic_load_n(&probeResult,__ATOMIC_RELAXED), __atomic_load_n(&touchChip,__ATOMIC_RELAXED),
        __atomic_load_n(&hidReports,__ATOMIC_RELAXED),
        __atomic_load_n(&keyStable,__ATOMIC_RELAXED), __atomic_load_n(&keyReports,__ATOMIC_RELAXED),
        __atomic_load_n(&keyErrors,__ATOMIC_RELAXED), __atomic_load_n(&keyStatus,__ATOMIC_RELAXED),
        (unsigned long long)__atomic_load_n(&keyObservedUs,__ATOMIC_RELAXED),
        (unsigned long long)__atomic_load_n(&keyAcceptedUs,__ATOMIC_RELAXED),
        (unsigned long long)__atomic_load_n(&keyMaxPollGapUs,__ATOMIC_RELAXED),
        __atomic_load_n(&keyPon,__ATOMIC_RELAXED), __atomic_load_n(&keyVolumeAvailable,__ATOMIC_RELAXED),
        __atomic_load_n(&keyVolumeConfig,__ATOMIC_RELAXED), __atomic_load_n(&keyVolumeLevel,__ATOMIC_RELAXED),
        __atomic_load_n(&keyVolumeUpPresses,__ATOMIC_RELAXED), __atomic_load_n(&keyVolumeDownPresses,__ATOMIC_RELAXED));
    return n < 0 ? 0 : ((size_t)n < cap ? (size_t)n : cap-1);
}

static_assert(sizeof(IOHIDDevice) == 0xd0, "Wrong iPhone HID superclass ABI");

class MyronDigitizer : public IOHIDDevice {
    OSDeclareDefaultStructors(MyronDigitizer);
    bool keysOnly = false;
    MyronPowerHardware power;
    IOBufferMemoryDescriptor *keyBuffer = nullptr;
    uint64_t lastKeyPollUs = 0;
    static uint64_t nowUs() {
        uint64_t ticks, frequency;
        __asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(ticks) :: "memory");
        __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
        return frequency ? ticks / frequency * 1000000 + ticks % frequency * 1000000 / frequency : 0;
    }
    struct Pad {
        IOMemoryMap *map;
        volatile uint32_t *regs;
        uint32_t config, latch;
    };
    Pad pads[PIN_COUNT]{};
    MyronSE19Bus se;
    bool useFifo = false;
    uint32_t halfTicks = 1;
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
    static uint64_t counter() {
        uint64_t value;
        __asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(value) :: "memory");
        return value;
    }
    static void waitEdge(void *ctx) {
        uint64_t start = counter();
        uint32_t ticks = static_cast<MyronDigitizer *>(ctx)->halfTicks;
        while (counter() - start < ticks) {}
    }
    void setGpioRate(unsigned hz) {
        uint64_t frequency;
        __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
        halfTicks = (uint32_t)((frequency + 2*hz - 1) / (2*hz));
    }
    static IOMemoryMap *mapBoardRange(uint64_t address, unsigned size) {
        IODeviceMemory *memory = IODeviceMemory::withRange(address, size);
        if (!memory) return nullptr;
        IOMemoryMap *mapping = memory->map(kIOMapAnywhere | kIOMapInhibitCache);
        memory->release();
        return mapping;
    }
    static uint32_t readRsc(void *ctx, unsigned off) {
        return static_cast<volatile uint32_t *>(ctx)[off/4];
    }
    static void writeRsc(void *ctx, unsigned off, uint32_t value) {
        static_cast<volatile uint32_t *>(ctx)[off/4] = value;
        __asm__ volatile("dsb sy" ::: "memory");
    }
    static int powerIoRail() {
        auto db = mapBoardRange(MYRON_CMD_DB, MYRON_CMD_DB_BYTES);
        if (!db) return MYRON_POWER_DB;
        uint32_t addr = myron_l4i_address(
            reinterpret_cast<const volatile uint32_t *>(db->getVirtualAddress()), MYRON_CMD_DB_BYTES);
        db->release();
        if (!addr) return MYRON_POWER_DB;
        auto rsc = mapBoardRange(MYRON_APPS_DRV2, MYRON_APPS_DRV_BYTES);
        if (!rsc) return MYRON_POWER_MAP;
        myron_rsc_io bus = {reinterpret_cast<void *>(rsc->getVirtualAddress()), readRsc, writeRsc, delay};
        __atomic_store_n(&rscId,readRsc(bus.context,0),__ATOMIC_RELAXED);
        __atomic_store_n(&rscConfig,readRsc(bus.context,0x0c),__ATOMIC_RELAXED);
        int rc = MYRON_POWER_BUSY;
        for (unsigned i = 0; i < 5 && rc == MYRON_POWER_BUSY; ++i) {
            if (i) IOSleep(20);
            rc = myron_vote_l4i(&bus, addr);
        }
        rsc->release();
        return rc;
    }
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
        se.close();
        for (auto &pad : pads) { OSSafeReleaseNULL(pad.map); pad.regs = nullptr; }
    }
    bool openSensor() {
        // Map and snapshot every required pad before changing any of them.
        for (unsigned i=0; i<PIN_COUNT; ++i) {
            pads[i].map = mapBoardRange(MYRON_TLMM_PADS + myron_gpio[i]*MYRON_PAD_STRIDE, 8);
            if (!pads[i].map) return false;
            pads[i].regs = reinterpret_cast<volatile uint32_t *>(pads[i].map->getVirtualAddress());
            pads[i].config = pads[i].regs[0];
            pads[i].latch = pads[i].regs[1] & 2;
        }
        int busStatus = se.open(mapBoardRange);
        __atomic_store_n(&busResult,busStatus,__ATOMIC_RELAXED);
        if (busStatus != 0 && busStatus != GENI_ERR_NOTSUP) {
            IOLog("myron-touch: QUP4 SE0 unavailable (%d)\n", busStatus);
            return false;
        }
        useFifo = busStatus == 0;
        if (!useFifo) se.close();
        configured = true;
        writePin(this, RESET, 4, 0); configure(RESET, 0x2c3);
        IODelay(2000);
        writePin(this, AVDD, 4, 2); configure(AVDD, 0x240);
        int rail = powerIoRail();
        __atomic_store_n(&railResult,rail,__ATOMIC_RELAXED);
        IOLog("myron-touch: L4I_E0 active vote status %d\n", rail);
        if (rail != MYRON_POWER_OK) return false;
        configure(ATTENTION, 0xc3);
        if (useFifo) {
            configure(MISO, 0x84); configure(MOSI, 0x84);
            configure(SCLK, 0x44); configure(CS, 0x87);
            sensor.bus = {&se, MyronSE19Bus::transfer, delay};
        } else {
            configure(MISO, 0x80);
            writePin(this, CS, 4, 2); configure(CS, 0x283);
            writePin(this, SCLK, 4, 0); configure(SCLK, 0x240);
            writePin(this, MOSI, 4, 0); configure(MOSI, 0x280);
            setGpioRate(9600000);
            io = {this, readPin, writePin, delay, waitEdge};
            sensor.bus = {&io, myron_spi_transfer, delay};
        }
        IODelay(3000);
        writePin(this, RESET, 4, 2);
        IOSleep(200);
        int rc = 0;
        for (unsigned attempt=0; attempt<5; ++attempt) {
            if (!useFifo && attempt == 3) setGpioRate(500000);
            rc = myron_touch_identify_and_start(&sensor);
            __atomic_store_n(&probeResult,rc,__ATOMIC_RELAXED);
            __atomic_store_n(&touchChip,(uint32_t)sensor.chip_id,__ATOMIC_RELAXED);
            if (!rc) {
                IOLog("myron-touch: controller %04x, TIC mode verified via %s\n", (unsigned)sensor.chip_id, useFifo ? "SE19 FIFO" : "GPIO");
                return true;
            }
            if (attempt < 4) IOSleep(200);
        }
        if (sensor.tx[1] == 0xa0 && (sensor.tx[0] == 0xa3 || sensor.tx[0] == 0x9f))
            IOLog("myron-touch: L4I_E0 vote complete, %s ID reg %02x status %02x data %02x crc %02x %02x\n",
                  useFifo ? "SE19 FIFO" : "GPIO", sensor.tx[0], sensor.rx[3], sensor.rx[7], sensor.rx[8], sensor.rx[9]);
        IOLog("myron-touch: controller/TIC probe failed (%d), ID %04x\n", rc, (unsigned)sensor.chip_id);
        return false;
    }
    static int submit(void *ctx, const uint8_t *bytes, size_t count) {
        auto self = static_cast<MyronDigitizer *>(ctx);
        IOBufferMemoryDescriptor *buffer = IOBufferMemoryDescriptor::withBytes(bytes, count, kIODirectionIn);
        if (!buffer) return kIOReturnNoMemory;
        auto rc = self->handleReport(buffer, kIOHIDReportTypeInput, 0);
        buffer->release();
        if (!rc) __atomic_fetch_add(&hidReports,1u,__ATOMIC_RELAXED);
        if (self->firstReport) {
            IOLog("myron-touch: first HID submission, status 0x%x, contacts %u\n",
                  (unsigned)rc, (unsigned)bytes[count-1]);
            self->firstReport = false;
        }
        return rc;
    }
    static void tick(OSObject *owner, IOTimerEventSource *source) {
        auto self = OSDynamicCast(MyronDigitizer, owner);
        if (!self) return;
        if (self->keysOnly) {
            const uint64_t now=nowUs();
            if(self->lastKeyPollUs && now>=self->lastKeyPollUs) {
                const uint64_t gap=now-self->lastKeyPollUs;
                if(gap>__atomic_load_n(&keyMaxPollGapUs,__ATOMIC_RELAXED))
                    __atomic_store_n(&keyMaxPollGapUs,gap,__ATOMIC_RELAXED);
            }
            self->lastKeyPollUs=now;
            const uint8_t before=self->power.report();
            self->power.poll();
            __atomic_store_n(&keyPon,self->power.rawPon,__ATOMIC_RELAXED);
            __atomic_store_n(&keyVolumeLevel,self->power.rawVolume,__ATOMIC_RELAXED);
            __atomic_store_n(&keyVolumeUpPresses,self->power.volumeUpPresses,__ATOMIC_RELAXED);
            __atomic_store_n(&keyVolumeDownPresses,self->power.volumeDownPresses,__ATOMIC_RELAXED);
            if(before!=self->power.report()) {
                __atomic_store_n(&keyObservedUs,now,__ATOMIC_RELAXED);
                __atomic_store_n(&keyStable,(uint32_t)self->power.report(),__ATOMIC_RELAXED);
            }
            __atomic_store_n(&keyErrors,self->power.errors,__ATOMIC_RELAXED);
            if (self->power.pending()) {
                uint8_t report[]={5,self->power.report()};
                // The workloop owns this preallocated descriptor until stop.
                // Do not allocate from the kernel heap on a physical key edge.
                IOReturn status=kIOReturnNoMemory;
                if(self->keyBuffer && self->keyBuffer->writeBytes(0,report,sizeof report)==sizeof report)
                    status=self->handleReport(self->keyBuffer,kIOHIDReportTypeInput,0);
                __atomic_store_n(&keyStatus,(int)status,__ATOMIC_RELAXED);
                if(status==kIOReturnSuccess){
                    self->power.accepted();++self->power.reports;
                    __atomic_store_n(&keyReports,self->power.reports,__ATOMIC_RELAXED);
                    __atomic_store_n(&keyAcceptedUs,nowUs(),__ATOMIC_RELAXED);
                }
            }
            source->setTimeoutMS(20);return;
        }
        if (!self->configured) return;
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
    OSString *newTransportString() const override { return OSString::withCString(keysOnly ? "SPMI" : "SPI"); }
    OSString *newProductString() const override { return OSString::withCString(keysOnly ? "Myron Physical Buttons" : "Myron FT3683"); }
    IOReturn newReportDescriptor(IOMemoryDescriptor **out) const override {
        if (!out) return kIOReturnBadArgument;
        *out = IOBufferMemoryDescriptor::withBytes(keysOnly ? myron_power_descriptor : myron_touch_descriptor,
            keysOnly ? sizeof(myron_power_descriptor) : myron_touch_descriptor_bytes, kIODirectionNone);
        return *out ? kIOReturnSuccess : kIOReturnNoMemory;
    }
    IOReturn getReport(IOMemoryDescriptor *out, IOHIDReportType type, IOOptionBits options) override {
        if (type != kIOHIDReportTypeFeature || (options & 255) != 4)
            return kIOReturnUnsupported;
        uint8_t report[] = {4, MYRON_FINGERS};
        return out && out->writeBytes(0, report, sizeof(report)) == sizeof(report) ?
            kIOReturnSuccess : kIOReturnNoSpace;
    }
    bool prepareKeys(IOService *provider) {
        if(!provider || strcmp(provider->getName(),"myron-power-key"))return false;
        keysOnly=true;
        if(!power.open())return false;
        __atomic_store_n(&keyVolumeAvailable,(uint32_t)power.volumeAvailable(),__ATOMIC_RELAXED);
        __atomic_store_n(&keyVolumeConfig,power.originalVolumeConfig(),__ATOMIC_RELAXED);
        const uint8_t initial[]={5,0};
        keyBuffer=IOBufferMemoryDescriptor::withBytes(initial,sizeof initial,kIODirectionIn);
        if(!keyBuffer){power.close();return false;}
        setProperty("Built-In",kOSBooleanTrue);
        setProperty("HIDDefaultBehavior",kOSBooleanTrue);
        loop=IOWorkLoop::workLoop();ownsLoop=loop!=nullptr;
        timer=IOTimerEventSource::timerEventSource(this,tick);
        if(!loop || !timer || loop->addEventSource(timer)!=kIOReturnSuccess){
            OSSafeReleaseNULL(timer);OSSafeReleaseNULL(loop);ownsLoop=false;power.close();return false;
        }
        return true;
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
        if(!keysOnly)myron_touch_release(&sensor, submit, this);
        power.close();
        OSSafeReleaseNULL(keyBuffer);
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

// Reuse the same retained 207-slot IOHIDDevice ABI with a separate consumer
// collection/service; PMIC errors never block the FT3683 digitizer work loop.
extern "C" bool myron_publish_power_key()
{
    auto parent=IOService::getResourceService();
    if(!parent)return false;
    auto nub=new IOService;
    auto key=new MyronDigitizer;
    bool attached=false,started=false,keyAttached=false;
    if(!nub || !key || !nub->init() || !key->init())goto fail;
    nub->setName("myron-power-key");
    attached=nub->attach(parent);if(!attached)goto fail;
    started=nub->start(parent);if(!started)goto fail;
    keyAttached=key->attach(nub);
    if(!keyAttached || !key->prepareKeys(nub) || !key->start(nub))goto fail;
    key->arm();key->release();nub->release();return true;
fail:
    if(keyAttached){key->closeBoard();key->detach(nub);}
    if(started)nub->stop(parent);
    if(attached)nub->detach(parent);
    OSSafeReleaseNULL(key);OSSafeReleaseNULL(nub);return false;
}
