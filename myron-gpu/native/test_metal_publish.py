#!/usr/bin/env python3
"""Run actual publication/client gating with failing IOKit peers, not a GPU."""
import argparse, subprocess, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cxx',default='c++');a=p.parse_args()
source='\n'.join(x for x in (HERE/'MyronMetalPublish.cpp').read_text().splitlines() if not x.startswith('#include'))
fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
using IOReturn=int;using kern_return_t=int;using task_t=void*;using UInt32=unsigned;
enum {kIOReturnSuccess=0,kIOReturnError=1,kIOReturnNoMemory=2,kIOReturnNotFound=3,
 kIOReturnNoResources=4,kIOReturnNotAttached=5,kIOReturnNotReady=6,kIOReturnExclusiveAccess=7,
 kIOReturnBadArgument=8,kIOReturnUnsupported=9};
static int scenario,loads,inits,posts,allocs,releases,attaches,detaches,starts,pubs,opens,properties;
static bool attached;static unsigned enabled=1;
struct kmod_info_t {const char *name;};
extern "C" {kmod_info_t g_kernel_kmod_info={"test"};volatile uint32_t myron_gpu_ready=1;}
struct OSSymbol {
 const char* name;static OSSymbol *withCString(const char*n){static OSSymbol s;s.name=n;return &s;}
};
#define OSSafeReleaseNULL(x) ((x)=nullptr)
struct OSMetaClass {
 unsigned getClassSize()const{return scenario==4?144:136;}
 static const OSMetaClass *getMetaClassWithName(const OSSymbol*);
 static void *preModLoad(const char*){return scenario==7?nullptr:(void*)1;}
 static int postModLoad(void*){++posts;return scenario==8?1:0;}
};
static OSMetaClass parent,foreign;
const OSMetaClass *OSMetaClass::getMetaClassWithName(const OSSymbol *s){
 if(!strcmp(s->name,"AGXAccelerator"))return scenario==6?&foreign:nullptr;
 return scenario==3?nullptr:scenario==5?&foreign:&parent;
}
struct OSDictionary{};struct IOUserClient{};
struct IOService {
 static IOService *getPlatform(){static IOService p;return scenario==13?nullptr:&p;}
 bool init(){return scenario!=10;}
 bool setProperty(const char *k,const char *v){
  ++properties;const char *keys[]={"MetalPluginName","MetalPluginClassName","NativeSandboxGrantProcess"};
  const char *values[]={"NativeAdrenoMetal","NativeAdrenoMetalDevice","backboardd,iconservicesagent,WidgetRenderer_Default,PosterBoard"};
  assert(properties<=3 && !strcmp(k,keys[properties-1]) && !strcmp(v,values[properties-1]));
  return !((scenario==11 && properties==1)||(scenario==12 && properties==2)||(scenario==17 && properties==3));
 }
 void release(){++releases;assert(!attached);}
 bool attach(IOService*){++attaches;if(scenario==14)return false;attached=true;return true;}
 void detach(IOService*){++detaches;assert(attached);attached=false;}
 bool start(IOService*){assert(attached);++starts;return scenario!=15;}
 void registerService(){assert(attached&&starts&&inits&&posts&&properties==3);++pubs;}
};
extern "C" bool PE_parse_boot_argn(const char*n,void*p,unsigned size){assert(!strcmp(n,"myron-gpu-metal")&&size==4);*(unsigned*)p=enabled;return true;}
extern "C" int OSKextLoadKextWithIdentifier(const char*n){assert(!strcmp(n,"com.apple.iokit.IOGPUFamily"));++loads;return scenario==2?1:0;}
extern "C" const OSMetaClass *myron_accelerator_parent(){return &parent;}
extern "C" IOService *myron_accelerator_candidate_allocate(){++allocs;static IOService s;return scenario==9?nullptr:&s;}
'''
candidate=(HERE/'MyronAcceleratorCandidate.cpp').read_text()
method=candidate[candidate.index('IOReturn AGXAccelerator::newUserClient'):candidate.index('extern "C" IOService *myron_accelerator_candidate_allocate')]
fixture+=source+r'''
extern "C" void myron_accelerator_init(){assert(loads==1 && !pubs);++inits;}
class AGXAccelerator: public IOService {public: IOReturn newUserClient(task_t,void*,UInt32,OSDictionary*,IOUserClient**);};
extern "C" int native_adreno_new_user_client(IOService*,task_t,void*,UInt32 type,OSDictionary*,IOUserClient**out,unsigned limit){
 assert(limit==40);if((type>>16)==0x4147)return kIOReturnUnsupported;assert(type==0x4147);++opens;*out=(IOUserClient*)1;return 0;
}
'''+method+r'''
int main(){
 for(scenario=0;scenario<=17;++scenario){
  loads=inits=posts=allocs=releases=attaches=detaches=starts=pubs=properties=0;
  attached=false;claimed=0;published=nullptr;myron_metal_stage=myron_metal_registered=0;myron_metal_status=0;
  enabled=scenario==0?0:1;myron_gpu_ready=scenario==1?0:1;
  myron_gpu_publish_metal();
  if(scenario<2)assert(!loads && !inits && !pubs);
  else if(scenario!=16){assert(!pubs && !myron_metal_registered && myron_metal_status);}
  else {assert(pubs==1 && myron_metal_registered==1 && myron_metal_stage==5 && !releases);}
  if((scenario>=10 && scenario<=15)||scenario==17)assert(releases==1);
  if(scenario==15)assert(detaches==1);
  const int before=pubs;myron_gpu_publish_metal();assert(pubs==before);
 }
 AGXAccelerator s;IOUserClient *out=(IOUserClient*)1;
 assert(s.newUserClient(nullptr,nullptr,0x4147,nullptr,nullptr)==kIOReturnBadArgument);
 myron_gpu_ready=0;assert(s.newUserClient(nullptr,nullptr,0x4147,nullptr,&out)==kIOReturnNotReady && !out && !opens);
 myron_gpu_ready=1;assert(s.newUserClient(nullptr,nullptr,1,nullptr,&out)==kIOReturnUnsupported && !out && !opens);
 assert(s.newUserClient(nullptr,nullptr,0x41476800,nullptr,&out)==kIOReturnUnsupported && !out && !opens);
 assert(!s.newUserClient(nullptr,nullptr,0x4147,nullptr,&out) && out && opens==1);
}
'''
with tempfile.TemporaryDirectory() as tmp:
 src=Path(tmp)/'test.cpp';exe=Path(tmp)/'test';src.write_text(fixture)
 subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined',src,'-o',exe],check=True)
 subprocess.run([exe],check=True)
print('PASS actual Metal publication: disabled/not-ready, 15 IOKit failures, cleanup, one-time registration and real client type gate; host peers only')
