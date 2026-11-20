#!/usr/bin/env python3
"""Execute the actual GOP startup, validation and kick readiness decisions.

IOKit services and IOSurface storage are test doubles. Production method bodies
are extracted unchanged; this verifies the board lifecycle, not real hardware.
"""
import argparse,json,subprocess,tempfile
from pathlib import Path

def method(text,signature):
    begin=text.index(signature);brace=text.index('{',begin);depth=1;end=brace+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[begin:end].replace(' override','')

def fixture(source,abi):
    methods='\n'.join(method(source,s) for s in (
        'bool canPresent()','bool announcePoweredByFirmware()',
        'bool startDisplay(','bool validateSwap('))
    # Run the actual kick entry gates, stopping before any IOSurface mapping.
    kick=method(source,'void kickOnce()')
    kick=kick[:kick.index('        const OriginalLegacySwapRequest *request=')]+'        ++passedKick;\n    }'
    formats=source[source.index('static inline bool nativeBgra('):source.index('// One byte per positive half')]
    request=abi['request']
    constants='\n'.join('static constexpr unsigned '+name+'='+str(request[key])+';' for name,key in (
        ('kRequestRect0','rect0'),('kRequestRect1','rect1'),('kRequestMasks','masks'),
        ('kRequestOptions','options'),('kRequestDims','dims'),('kRequestSurfaces','surfaces')))
    return r'''
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#define assert(c) do {if(!(c)){fprintf(stderr,"assertion failed: %s\n",#c);exit(1);}} while(0)
#include "NativeLegacyRequest.h"
using IOReturn=int;
static constexpr int kIOReturnSuccess=0,kIOReturnNotReady=-1;
struct IOService {void joinPMtree(void*){}};
struct IOPMPowerState {unsigned version=0,capabilityFlags=0;};
static constexpr unsigned kIOPMDeviceUsable=1;
static bool baseStart=true;static unsigned pm=0,phase=4,validate=1,transfer=1;
static int powerResult=0;static unsigned pmCalls=0,powerCalls=0;
static unsigned reportedPower=0,lastReason=0;
static bool PE_parse_boot_argn(const char*n,unsigned*out,size_t){
 if(!strcmp(n,"offline-legacy-pm"))*out=pm;
 else if(!strcmp(n,"offline-legacy-phase"))*out=phase;
 else if(!strcmp(n,"offline-legacy-validate"))*out=validate;
 else if(!strcmp(n,"offline-legacy-transfer"))*out=transfer;
 else assert(false);return true;
}
static uint64_t ringStorage[1][2];
static volatile uint64_t (*native_legacy_ring)[2]=ringStorage;
static uint32_t native_legacy_ring_cap;
static void *IOMallocZero(size_t){return nullptr;}
struct OriginalLegacyStateRequest {
 uint32_t skipRequested,requested,skipPowered,powered;uint8_t changed,pad[11];
};
static void native_legacy_pm_observed(unsigned event,int,unsigned long value){if(event==5)reportedPower=value;}
struct IOMobileFramebufferLegacy {
 bool initialized=false;
 bool start(IOService*){return baseStart;}
 void stop(IOService*){}
 int applyStateRequest(OriginalLegacyStateRequest*r,bool gate){
  ++powerCalls;assert(!gate && r->skipRequested==1 && !r->requested);
  assert(!r->skipPowered && r->powered==1 && r->changed==1);return powerResult;
 }
 void PMinit(){++pmCalls;initialized=true;}
 void PMstop(){}
 int registerPowerDriver(void*,IOPMPowerState*,unsigned){return 0;}
 int changePowerStateToPriv(unsigned){return 0;}
};
struct OSObject {
 const char *kind;
 bool metaCast(const char *name){return !strcmp(name,kind);}
};
struct IOMemoryDescriptor:OSObject {
 uint64_t length=32;IOMemoryDescriptor(){kind="IOMemoryDescriptor";}
 uint64_t getLength(){return length;}
};
struct Surface:OSObject {
 uint64_t width=4,height=2,stride=16,allocation=32;uint32_t format=0x42475241,planes=0;
 IOMemoryDescriptor memory;Surface(){kind="IOSurface";}
};
static IOMemoryDescriptor *native_legacy_surface_descriptor(OSObject*s){return &static_cast<Surface*>(s)->memory;}
#define ACCESSOR(name,field,type) static type native_legacy_surface_##name(OSObject*s){return static_cast<Surface*>(s)->field;}
ACCESSOR(width,width,uint64_t) ACCESSOR(height,height,uint64_t) ACCESSOR(stride,stride,uint64_t)
ACCESSOR(allocation,allocation,uint64_t) ACCESSOR(format,format,uint32_t) ACCESSOR(planes,planes,uint32_t)
static void native_legacy_surface_rejected(uint64_t,uint64_t,uint32_t,uint32_t,uint64_t,uint64_t,uint64_t){}
static void native_legacy_swap_validation_observed(bool,unsigned r,const void*,const void*){lastReason=r;}
static void countFormat(unsigned){}
static uint32_t native_legacy_formats[10];
CONSTANTS
FORMATS
struct OriginalLegacySwapRequest {alignas(8) unsigned char bytes[kRequestSurfaces+4*sizeof(void*)];};
struct Display:IOMobileFramebufferLegacy {
 bool logicalPM=false,firmwareScanoutReady=false,primary=true,transferred=false;
 void *bootMapping=this;
 unsigned passedKick=0,stats[16]={};
 const OriginalLegacySwapRequest *pending=nullptr;
 void stat(unsigned n){++stats[n];}
 void note(unsigned,int,const void*){}
 unsigned validatedCount(){return pending?1:0;}
 void addValidated(const OriginalLegacySwapRequest*r){pending=r;}
 void removeValidated(const OriginalLegacySwapRequest*r){if(pending==r)pending=nullptr;}
 void getDisplayDimensions(uint32_t*w,uint32_t*h){*w=4;*h=2;}
METHODS
KICK
};
static uint32_t native_legacy_swapstat[16];
static void word(OriginalLegacySwapRequest &r,unsigned offset,uint32_t v){memcpy(r.bytes+offset,&v,4);}
int main(){
 IOService provider;Display d;
 assert(!d.canPresent());assert(d.startDisplay(&provider));
 // This is the shipping configuration: optional PM remains completely off.
 assert(!d.logicalPM && !pmCalls && d.canPresent() && powerCalls==1 && reportedPower==1);
 Surface s;OSObject *surface=&s;OriginalLegacySwapRequest r={};
 memcpy(r.bytes+kRequestSurfaces,&surface,sizeof surface);
 const unsigned rects[]={kRequestRect0,kRequestRect1};
 for(unsigned rect:rects){word(r,rect+8,4);word(r,rect+12,2);}
 word(r,kRequestMasks,1);word(r,kRequestDims,4);word(r,kRequestDims+4,2);
 assert(d.validateSwap(&r) && d.pending==&r && lastReason==0);
 d.kickOnce();assert(d.passedKick==1 && !d.stats[3]);
 // Geometry/format/descriptor checks still reject unsupported surfaces.
 s.format=0x12345678;assert(!d.validateSwap(&r));s.format=0x42475241;
 s.memory.length=31;assert(!d.validateSwap(&r));s.memory.length=32;
 word(r,kRequestRect0,1);assert(!d.validateSwap(&r));word(r,kRequestRect0,0);
 assert(d.validateSwap(&r));
 // Optional gates, missing mapping, nonprimary displays and failed state
 // publication cannot authorize a copy, even if PM says it is initialized.
 validate=0;assert(!d.validateSwap(&r));validate=1;
 transfer=0;d.kickOnce();assert(d.passedKick==1);transfer=1;
 d.logicalPM=true;d.firmwareScanoutReady=false;
 assert(!d.validateSwap(&r));d.kickOnce();assert(d.passedKick==1);
 d.firmwareScanoutReady=true;d.bootMapping=nullptr;
 assert(!d.validateSwap(&r));d.kickOnce();assert(d.passedKick==1);
 d.bootMapping=&d;d.primary=false;
 assert(!d.validateSwap(&r));d.kickOnce();assert(d.passedKick==1);
 d.primary=true;assert(!d.validateSwap(nullptr));
 powerResult=-1;Display failed;assert(!failed.startDisplay(&provider));assert(!failed.canPresent());
 powerResult=0;baseStart=false;Display missing;assert(!missing.startDisplay(&provider));assert(!missing.canPresent());
 return 0;
}
'''.replace('CONSTANTS',constants).replace('FORMATS',formats).replace('METHODS',methods).replace('KICK',kick).replace(
    'struct Display:IOMobileFramebufferLegacy {','static uint32_t native_legacy_swapstat[16];\nstruct Display:IOMobileFramebufferLegacy {').replace(
    '};\nstatic uint32_t native_legacy_swapstat[16];\nstatic void word','};\nstatic void word')

def check_publication(source, compiler, flags, output):
    methods = '\n'.join(method(source, signature) for signature in
                        ('bool start(IOService', 'bool publishOneLayer()', 'void registerService(', 'bool publishDisplay('))
    fixture = r'''
#include <cassert>
#include <cstring>
#include <cstddef>
using IOOptionBits = unsigned;
static int failure, allocated, publications, observed;
static void IOLog(const char *) {}
struct OSNumber {
    unsigned value;
    static OSNumber *withNumber(unsigned value, unsigned bits) {
        assert(bits == 32);
        if (failure == 2) return nullptr;
        ++allocated;
        return new OSNumber{value};
    }
    void release() { --allocated; delete this; }
};
struct OSDictionary {
    unsigned layers = 0;
    static OSDictionary *withCapacity(unsigned capacity) {
        assert(capacity == 1);
        if (failure == 1) return nullptr;
        ++allocated;
        return new OSDictionary;
    }
    bool setObject(const char *key, OSNumber *count) {
        assert(!strcmp(key, "MaxNumLayers"));
        layers = count->value;
        return failure != 3;
    }
    void release() { --allocated; delete this; }
};
#define OSSafeReleaseNULL(obj) do { if (obj) (obj)->release(); (obj) = nullptr; } while (0)
static void PE_parse_boot_argn(const char *name, unsigned *value, size_t) {
    assert(!strcmp(name, "offline-legacy-register"));
    *value = 1;
}
static void native_legacy_backend_guard(unsigned, void *, void *) { assert(false); }
static unsigned cadence=60, refreshPublications;
static unsigned native_legacy_refresh_hz() { return cadence; }
static void native_legacy_set_refresh_properties(void *) { ++refreshPublications; }
static void native_legacy_registration_observed(void *) { ++observed; }
struct IOService {
    unsigned clientLayers = 0;
    bool powered = false, timerStarted = false;
    bool setProperty(const char *key, OSDictionary *dictionary) {
        assert(!strcmp(key, "IOMFBNumLayers"));
        if (failure == 4) return false;
        clientLayers = dictionary->layers;
        return true;
    }
    virtual void registerService(IOOptionBits options) {
        // A matching client can read the property immediately.
        assert(options == 4 && powered && timerStarted && clientLayers == 1 && refreshPublications==1);
        ++publications;
    }
};
struct Display : IOService {
    bool primary = true;
    bool deferPublication = false, requestedPublication = false, stopped = false;
    IOOptionBits startupOptions = 0;
    bool startDisplay(IOService *) {
        if (failure != 6) registerService(4);
        if (failure == 5) return false;
        powered = true;
        return true;
    }
    void stop(IOService *) { stopped = true; }
    void startVsync() { timerStarted = true; }
    void startDirect() {}
    METHODS
};
int main() {
    for (failure = 0; failure <= 6; ++failure) {
        Display display;
        refreshPublications = publications = observed = 0;
        assert(display.start(nullptr) == (failure == 0));
        assert(display.stopped == (failure != 0 && failure != 5));
        assert(publications == (failure == 0));
        assert(publications == observed && allocated == 0);
    }
}
'''.replace('METHODS', methods)
    path = output / 'publication.cpp'
    exe = output / 'publication.exe'
    path.write_text(fixture)
    subprocess.run([*compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', *flags,
                    str(path), '-o', str(exe)], check=True)
    subprocess.run([str(exe.resolve())], check=True)
    print('PASS: first matching client sees powered scanout, refresh and one layer; six startup failures publish nothing')


def check_refresh(source, compiler, output):
    methods='\n'.join(method(source, signature) for signature in ('void armVsync()', 'void vsyncTick()'))
    program=r'''
#include <cassert>
#include <cstdint>
static uint64_t now=100;
static unsigned sent=0, idle=0;
static uint64_t mach_absolute_time(){return now;}
static uint64_t mach_continuous_time(){return now+10;}
static void native_legacy_vsync_observed(unsigned event,unsigned hz){assert(hz==60);if(event==2)++idle;}
static void native_legacy_vsync_notify(void *,uint64_t ts,uint64_t continuous,uint64_t interval){
    assert(ts==now && continuous==now+10 && interval==16); ++sent;
}
static constexpr int kIOReturnSuccess=0;
struct Timer {
    int err=0;
    uint64_t deadline=0;
    int wakeAtTime(uint64_t when){deadline=when;return err;}
    int setTimeoutMS(unsigned ms){assert(ms==250);deadline=now+ms;return err;}
};
struct Display {
    Timer *vsyncTimer; bool vsyncArmed=false,subscribed=false;
    uint64_t vsyncInterval=16,vsyncNext=0; unsigned vsyncHz=60;
    bool vsyncWanted() const {return subscribed;}
    METHODS
};
int main(){
    Timer timer;Display display{&timer};
    display.armVsync();assert(timer.deadline==116);
    now=116;display.vsyncTick();assert(sent==0 && idle==1 && timer.deadline==366);
    display.subscribed=true;now=366;display.vsyncTick();assert(sent==1 && timer.deadline==382);
    now=382;display.vsyncTick();assert(sent==2 && timer.deadline==398);
    display.subscribed=false;now=398;display.vsyncTick();assert(sent==2 && idle==2);
    display.subscribed=true;now=648;display.vsyncTick();assert(sent==3 && timer.deadline==664);
    now=750;display.vsyncTick();assert(sent==4 && timer.deadline==766);
    timer.err=1;now=766;display.subscribed=false;display.vsyncTick();assert(!display.vsyncArmed);
    timer.err=0;display.armVsync();assert(display.vsyncArmed);
    display.vsyncTimer=nullptr;display.vsyncTick();assert(sent==4 && !display.vsyncArmed);
}
'''.replace('METHODS',methods)
    cpp=output/'refresh.cpp';exe=output/'refresh'
    cpp.write_text(program)
    subprocess.run([*compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe.resolve())],check=True)
    print('PASS: late refresh subscription without a swap, unsubscribe/resubscribe, late tick and stop')


def main():
    p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True)
    p.add_argument('--cc',default='clang++');p.add_argument('--cc-arg',action='append',default=[])
    p.add_argument('--sanitize',action='store_true');p.add_argument('--out',type=Path)
    a=p.parse_args();display=a.device/'display'
    source=(display/'NativeLegacyDisplay.cpp').read_text()
    abi=json.loads((display/'legacy-display-24A446-iphone12-1.json').read_text())
    for name in ('void stop(','void free('):
        assert 'firmwareScanoutReady=false;' in method(source,name),'stop/free must revoke scanout readiness'
    probe=(display/'MyronDisplayProbe.cpp').read_text()
    assert '"offline-legacy-pm"' in probe,'test must retain the board PM restriction'
    code=fixture(source,abi)
    with tempfile.TemporaryDirectory() as tmp:
        out=a.out or Path(tmp);out.mkdir(parents=True,exist_ok=True)
        check_refresh(source,[a.cc,*a.cc_arg,*(['-fsanitize=address,undefined'] if a.sanitize else [])],out)
        check_publication(source,[a.cc,*a.cc_arg],['-fsanitize=address,undefined'] if a.sanitize else [],out)
        for name,body in [('fixed',code),
            ('old-validation-gate',code.replace('enabled==1 && canPresent() && request','enabled==1 && logicalPM && primary && bootMapping && request')),
            ('old-copy-gate',code.replace('enabled!=1 || !canPresent()','enabled!=1 || !logicalPM || !bootMapping || !primary'))]:
            assert name=='fixed' or body!=code,'negative control did not alter a production decision'
            cpp=out/(name+'.cpp');exe=out/(name+'.exe');cpp.write_text(body)
            flags=['-fsanitize=address,undefined'] if a.sanitize else []
            subprocess.run([a.cc,*a.cc_arg,'-std=c++17','-O1','-Wall','-Wextra','-Werror',
                *flags,'-I',str(display),str(cpp),'-o',str(exe)],check=True)
            r=subprocess.run([str(exe.resolve())],capture_output=True,text=True)
            if name=='fixed':
                if r.returncode:raise RuntimeError(r.stdout+r.stderr)
            elif r.returncode==0:raise AssertionError('old PM gate unexpectedly passed: '+name)
            elif 'assert' not in r.stderr.lower():raise AssertionError('negative control did not fail an assertion: '+r.stderr)
            print('PASS',name,flush=True)
    print('PASS: firmware GOP startup and actual frame-validation/kick gates; no PM registration required')
if __name__=='__main__':main()
