#!/usr/bin/env python3
"""Execute the staged connection creation path with IOKit failure injection."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from prepare_sources import stage


def check(references, cxx):
    with tempfile.TemporaryDirectory(prefix='myron-publish-open-') as tmp:
        root=Path(tmp);stage(references,root/'source')
        source=(root/'source/NativeAdreno/NativeAdrenoPublish.cpp').read_text()
        start=source.index('    shiftName(native_adreno_metal_diag.opener);')
        end=source.index('extern "C" void native_adreno_note_property_read',start)
        creation=source[start:end]
        fields=source[source.index('    void setMailboxTask('):source.index('    void setHandoffOnly()')]
        free_task=source[source.index('    if(mailbox_task_) {task_deallocate'):source.index('    IOUserClient::free();')]
        fixture=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
using task_t=void*;using UInt32=unsigned;using IOReturn=int;using io_filter_policy_t=unsigned;
enum {kIOReturnSuccess=0,kIOReturnNotAttached=1,kIOReturnNoMemory=2,kIOReturnNoResources=3,
 kIOReturnUnsupported=4,kIOReturnBusy=5,NativeAdrenoPluginOpenType=0x4147,NativeAdrenoHandoffOpenType=0x4148};
void *kernel_task=(void*)1;void *kOSBooleanTrue=(void*)1;
int scenario,refs,allocs,releases,starts,stops,attaches,detaches,mounts,taskrefs;
struct IOService{};struct OSDictionary{};struct IOUserClient{};
struct {unsigned opened,closed;void*lock;}g;
void IOLockLock(void*){} void IOLockUnlock(void*){}
void task_reference(void*){++taskrefs;} void task_deallocate(void*){--taskrefs;}
void proc_selfname(char*p,size_t n){snprintf(p,n,"backboardd");}
void shiftName(char(*)[17]){}
void *kauth_cred_get(){return nullptr;}
int mac_iokit_check_open(void*,void*,unsigned){return 0;}
struct {IOReturn(*io_filter_resolver)(task_t,void*,unsigned,io_filter_policy_t*);
 void(*io_filter_release)(io_filter_policy_t);} *gIOUCFilterCallbacks=nullptr;
struct {char opener[3][17];unsigned bad,attach_status,chk_type,chk_macf,chk_res,foreign_opens,foreign_type,grants,busy,opens;}native_adreno_metal_diag;
struct NativeAdrenoOpenRecord {char name[20];unsigned type,macf,res,attach,foreign;}native_adreno_open_log[8];
unsigned native_adreno_open_log_count;
struct NativeAdrenoClientRecord {unsigned opens,refused,last_refusal;}record;
NativeAdrenoClientRecord *clientRecord(const char*){return &record;}
struct AGXDeviceUserClient:IOUserClient {
 task_t mailbox_task_=nullptr;bool attached=false,started=false;
 AGXDeviceUserClient(){++allocs;++refs;}
 TASK
 bool initWithTask(task_t,void*,unsigned,void*){return scenario!=1;}
 bool attach(IOService*){++attaches;if(scenario==3)return false;attached=true;return true;}
 bool start(IOService*){++starts;if(scenario==4)return false;started=true;return true;}
 void stop(IOService*){assert(started);started=false;++stops;}
 void detach(IOService*){assert(attached);attached=false;++detaches;}
 void release(){assert(!attached && !started);FREE_TASK ++releases;--refs;delete this;}
 bool mount(bool){++mounts;return scenario!=7;}
 bool setProperty(const char*,void*){return true;}
 void setHandoffOnly(){}
};
IOReturn create(IOService*provider,task_t owningTask,void*securityID,UInt32 type,
 OSDictionary*properties,IOUserClient**handler,unsigned limit){
 CREATION
int main(){
 for(scenario=0;scenario<9;++scenario){
  refs=allocs=releases=starts=stops=attaches=detaches=mounts=taskrefs=0;record={};
  if(scenario==6)record.opens=40;
  IOService provider;IOUserClient *out=nullptr;
  int status=create(scenario==2?nullptr:&provider,(void*)2,nullptr,scenario==5?1:0x4147,nullptr,&out,40);
  if(scenario==0 || scenario==8){
   assert(!status && out && refs==1 && taskrefs==1 && mounts==1 && !releases);
   auto *client=static_cast<AGXDeviceUserClient*>(out);client->stop(&provider);client->detach(&provider);client->release();
  }else{
   assert(status && !out && refs==0 && taskrefs==0 && allocs==releases);
   if(scenario<5)assert(!mounts);
   if(scenario>=5)assert(stops==1 && detaches==1);
   if(scenario==4)assert(detaches==1 && !stops);
  }
  assert(!refs && !taskrefs);
 }
 puts("PASS: production connection create, init/provider/attach/start/type/cap/mount failures and task reference cleanup");
}
'''.replace('FREE_TASK',free_task).replace('TASK',fields).replace('CREATION',creation)
        path=root/'open.cpp';path.write_text(fixture)
        subprocess.run([cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined',path,'-o',root/'open'],check=True)
        subprocess.run([root/'open'],check=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--references',type=Path,required=True);p.add_argument('--cxx',default='c++')
    a=p.parse_args();check(a.references.resolve(),a.cxx)
