#!/usr/bin/env python3
"""Exercise the actual pinned service and board registration before a full build.

Host doubles cover lifecycle and selector semantics, not real kernel registration.
The unchanged upstream test independently checks the software blob format.
"""
import argparse, ast, hashlib, json, os, runpy, subprocess, tempfile, unittest
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--device',type=Path,required=True)
p.add_argument('--cc',default='clang++')
p.add_argument('--sanitize',action='store_true')
p.add_argument('--source-only',action='store_true')
a=p.parse_args();d=a.device.resolve();source=d/'display/AppleKeyStoreState'
pin=json.loads((source/'source.json').read_text())
assert pin['revision']=='6ff4f11d8fdf853351f8d98e1bbe1373fb8da2e6'
for name,want in pin['source_sha256'].items():
    assert hashlib.sha256((source/name).read_bytes()).hexdigest()==want,name
boot=(d/'MyronStorageBoot.cpp').read_text()
assert boot.index('    int result = IOKitBSDInit();')<boot.index('            myron_keystore_start();')<boot.index('            myron_display_start();')<boot.rindex('    return result;')
assert "'myron27-keystore=1'" in (d/'boot_assets.py').read_text()
builder=ast.parse((d/'display/display_build.py').read_text())
constants={n.value for n in ast.walk(builder) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
assert 'AppleKeyStoreState/NativeKeyStoreEvents' in constants and 'MyronKeyStoreProbe' in constants
for cls in ('AppleKeyStore','AppleKeyStoreUserClient'):
    assert '__ZTV'+str(len(cls))+cls in constants
assert '_myron_keystore_start' in constants and '_myron_keystore_snapshot' in constants
if a.source_only:
    print('PASS: pinned component, boot ordering, required argument and final symbol contracts')
    raise SystemExit(0)
flags=['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if a.sanitize else []
# Run the unmodified upstream test, substituting only compiler and sanitizer flags.
original_run=subprocess.run
def upstream_run(cmd,**kw):
    if cmd[0]=='c++':cmd=[a.cc,'-include','cstdint',*flags,*cmd[1:]]
    return original_run(cmd,**kw)
subprocess.run=upstream_run
try:
    runpy.run_path(str(source/'test_closed_boundary.py'),run_name='__main__')
    # Reuse the existing full-root startup-order fixture without extracting a
    # firmware image just to run this one independent control-flow test.
    tree=ast.parse((d/'tests/test_root_runtime.py').read_text())
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='test_root_mode_call_order_and_failures')
    scope=dict(HERE=d,Path=Path,json=json,subprocess=subprocess)
    exec(compile(ast.Module(body=[method],type_ignores=[]),'<existing root startup test>','exec'),scope)
    with tempfile.TemporaryDirectory() as tmp:
        case=unittest.TestCase();case.work=Path(tmp)
        scope[method.name](case)
    print('PASS: existing root-mode startup fixture; service before display; nine success/failure/reentry cases')
finally:subprocess.run=original_run

header=r'''
#pragma once
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <cassert>
using IOReturn=int;
constexpr int kIOReturnNotReady=-1,kIOReturnNotPermitted=-2,kIOReturnBadArgument=-3,
    kIOReturnExclusiveAccess=-4,kIOReturnNoDevice=-5,kIOReturnNoMemory=-6,kIOReturnError=-7;
static int scenario, registrations, initCalls, allocations, detachments, releases;
static bool classExists, wantIdentity=true;
extern "C" bool native_aks_state_enabled(void);
class OSObject {public:virtual ~OSObject()=default;void release(){++releases;}};
class OSData:public OSObject {
public:unsigned getLength(){return scenario==3?7:scenario==4?33:8;}
const void *getBytesNoCopy(){static uint8_t good[8]={1,2,3,4,5,6,7,8},zero[8]={};return scenario==5?zero:good;}
};
class OSSymbol:public OSObject {public:static const OSSymbol *withCString(const char *){static OSSymbol x;return &x;}void release()const{++releases;}};
class OSMetaClass {public:
static void *getMetaClassWithName(const OSSymbol *){return classExists?(void *)1:nullptr;}
static void *preModLoad(const char *){return scenario==8?nullptr:(void *)1;}
static int postModLoad(void *){return scenario==9?-99:0;}
};
static const char *gIODTPlane="IODeviceTree";
class IORegistryEntry:public OSObject {public:
static IORegistryEntry *fromPath(const char *path,const char *plane){assert(!strcmp(path,"/chosen")&&plane==gIODTPlane);static IORegistryEntry e;return scenario==2?nullptr:&e;}
OSObject *getProperty(const char *name){assert(!strcmp(name,"unique-chip-id"));static OSData d;return wantIdentity?&d:nullptr;}
};
class IOService:public IORegistryEntry {public:
static IOService *getResourceService(){static IOService s;return scenario==7?nullptr:&s;}
bool init(){return scenario!=11;}
bool attach(IOService *){return scenario!=12;}
void detach(IOService *){++detachments;}
bool start(IOService *){assert(native_aks_state_enabled());if(scenario==13)return false;++registrations;return true;}
};
struct kmod_info_t {char name[64];};
extern "C" kmod_info_t g_kernel_kmod_info;
static bool PE_parse_boot_argn(const char *name,void *out,int size){assert(size==4);auto n=(unsigned *)out;
 if(!strcmp(name,"myron27-keystore")){*n=scenario==0?0:1;return true;}
 if(!strcmp(name,"offline-keystore")){*n=scenario==1?1:0;return true;}return false;}
static void IOLog(const char *,...){ }
#define OSDynamicCast(T,x) dynamic_cast<T *>(x)
#define OSSafeReleaseNULL(x) do{if(x){(x)->release();(x)=nullptr;}}while(0)
'''
harness=r'''
#include "fixture.h"
extern "C" {
kmod_info_t g_kernel_kmod_info={"kernel"};
void boot_progress_stage(const char *){}
IOService *native_keyevents_allocate(){++allocations;static IOService s;return scenario==10?nullptr:&s;}
}
#include "MyronKeyStoreProbe.cpp"
extern "C" void native_keyevents_static_init(){++initCalls;classExists=true;}
int main(int argc,char **argv) {
 assert(argc==2);scenario=std::atoi(argv[1]);classExists=scenario==6;
 myron_keystore_start();myron_keystore_start();
 assert(registrations==(scenario==14?1:0));
 assert(initCalls==((scenario>=9)?1:0));
 assert(allocations==((scenario>=10)?1:0));
 assert(detachments==(scenario==13?1:0));
 assert(native_aks_state_enabled()==(scenario==14));
 const unsigned expected[]={0,11,12,12,12,12,13,14,15,16,17,17,17,17,3};
 assert(stage==expected[scenario]);
 if(scenario==14){
  assert(native_aks_lock_state()==3);
  uint8_t id[32];assert(native_aks_device_id(nullptr,32)==0 && native_aks_device_id(id,7)==0);
  assert(native_aks_device_id(id,sizeof id)==8 && id[0]==1 && id[7]==8);
  wantIdentity=false;assert(native_aks_device_id(id,sizeof id)==0);wantIdentity=true;
  native_aks_opened();native_keyevents_open_refused();native_aks_call(7,0);native_aks_call(999,-90);native_aks_call(160,-91);
  assert(opens==1 && refused==1 && calls==3 && errors==2 && firstErrorSelector==999 && firstErrorStatus==-90);
  char text[1024];size_t n=myron_keystore_snapshot(text,sizeof text);assert(n==strlen(text));
  assert(strstr(text,"registered=1") && strstr(text,"aks_selector=160 count=1") && strstr(text,"first_error_selector=999"));
  assert(myron_keystore_snapshot(nullptr,10)==0 && myron_keystore_snapshot(text,0)==0);
  for(size_t cap=1;cap<1024;++cap){memset(text,0x55,sizeof text);size_t used=myron_keystore_snapshot(text,cap);assert(used<cap && text[used]==0 && text[cap]==0x55);}
 }
}
'''
with tempfile.TemporaryDirectory() as tmp:
    t=Path(tmp);(t/'fixture.h').write_text(header+'\n#include <cstdlib>\n')
    for inc in ['IOKit/IOService.h','IOKit/IODeviceTreeSupport.h','IOKit/IOLib.h','libkern/c++/OSData.h','libkern/c++/OSSymbol.h','pexpert/pexpert.h','mach/kmod.h']:
        f=t/inc;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('#include "fixture.h"\n')
    (t/'main.cpp').write_text(harness)
    exe=t/'probe'
    subprocess.run([a.cc,'-std=c++17','-Wall','-Wextra','-Werror',*flags,'-I',str(t),'-I',str(d/'display'),str(t/'main.cpp'),'-o',str(exe)],check=True)
    for case in range(15):subprocess.run([str(exe),str(case)],check=True)
print('PASS: actual board probe; 15 lifecycle cases; one-time registration; identity refusal; bounded persistent selector evidence')
subprocess.run([os.sys.executable,str(Path(__file__).with_name('test_myron_log_worker.py')),
    '--device',str(d),'--cc',a.cc],check=True)
