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
