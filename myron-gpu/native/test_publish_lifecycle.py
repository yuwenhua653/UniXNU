#!/usr/bin/env python3
"""Execute the staged IOKit dispatch/close and real lease validation over host peers."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from prepare_sources import stage

HERE = Path(__file__).resolve().parent


def body(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


def check(references, cxx):
    with tempfile.TemporaryDirectory(prefix='myron-publish-life-') as tmp:
        root = Path(tmp)
        stage(references, root/'source')
        pub = (root/'source/NativeAdreno/NativeAdrenoPublish.cpp').read_text()
        core = (root/'source/NativeAdreno/NativeAdrenoUserClient.cpp').read_text()
        unmap = body(core, 'IOReturn NativeAdrenoUserClient::cpuUnmap(', 'IOReturn NativeAdrenoUserClient::createQueue(')
        methods = body(pub, 'IOReturn AGXDeviceUserClient::run(', 'IOReturn AGXDeviceUserClient::action(')
        dispatch = body(pub, 'static IOReturn runCore(AGXDeviceUserClient *connection,', 'IOReturn AGXDeviceUserClient::run(')
        close = body(pub, 'IOReturn AGXDeviceUserClient::clientClose()', 'void AGXDeviceUserClient::free()')
        guards = body(pub, '    void lockCore() {', '    bool handoffOnly_=false;')
        fixture = r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <condition_variable>
#include <thread>
#include <atomic>
#include <functional>
#include "NativeAdrenoABI.h"
using IOReturn=int;using task_t=void*;
enum {kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnNotReady=2,kIOReturnBusy=3,
 kIOReturnTimeout=4,kIOReturnUnsupported=5,THREAD_UNINT=1};
struct Lock {std::mutex mutex;std::condition_variable cv;} lock;
thread_local bool holding=false;
void IOLockLock(Lock *l){l->mutex.lock();assert(!holding);holding=true;}
void IOLockUnlock(Lock *l){assert(holding);holding=false;l->mutex.unlock();}
std::atomic<unsigned> sleepers{0};
void IOLockSleep(Lock *l,void*,int){
 assert(holding);++sleepers;
 std::unique_lock<std::mutex> guard(l->mutex,std::adopt_lock);l->cv.wait(guard);guard.release();
}
void IOLockWakeup(Lock *l,void*,bool){assert(holding);l->cv.notify_all();}
void *current_task(){return (void*)0x2222;}
void proc_selfname(char *p,size_t n){snprintf(p,n,"backboardd");}
struct Clock {void*cookie=nullptr;uint64_t(*now_us)(void*)=nullptr;int(*idle)(void*)=nullptr;};
struct {Lock*lock=&::lock;Clock clock;bool kernel_client=true;bool slots[4]={};unsigned closed=0;} g;
struct NativeAdrenoClientRecord {unsigned closes=0,slot=0,peak_mib=0;} record;
NativeAdrenoClientRecord *clientRecord(const char*){assert(holding);return &record;}
struct {
 char pbf[64],report2[64],report[64];unsigned reports=0,inflight=0,inflight_since_calls=0,calls=0,
  last_selector=0,last_status=0,closes=0;
} native_adreno_metal_diag;
uint64_t native_adreno_wait_outer[4];uint32_t native_adreno_view_kept=0,native_adreno_export_stats[4];
enum {NativeAdrenoHandoffBase=0x7000,NativeAdrenoHandoffLast=0x7003,NativeAdrenoExportMethod=0x7100,
 NativeAdrenoExportMaxPiece=3968,NativeAdrenoMaxClients=4};
int native_gop_handoff_call(uint32_t,void*,const void*,size_t,void*,size_t){return kIOReturnUnsupported;}
int boot_log_export_put(uint32_t,uint32_t,uint32_t,const void*,uint32_t){return -1;}
class NativeAdrenoUserClient {
public:
 struct Entry {uint64_t handle=17;unsigned token=3,mapping_leases=1;bool unreleasable=false;} entry;
 bool open_=true;unsigned dispatches=0,imports=0,frees=0;int closeError=0;void *task=nullptr;
 Entry *find(uint64_t h){return h==entry.handle?&entry:nullptr;}
 IOReturn cpuUnmap(const NativeAdrenoAbiBoCpuUnmap*);
 unsigned mappingLeases(unsigned t){assert(holding);return t==entry.token?entry.mapping_leases:0;}
 IOReturn importBo(const NativeAdrenoAbiBoImport*,void*t,NativeAdrenoAbiBoAllocReply *r){
  assert(holding);++imports;task=t;r->handle=23;return 0;
 }
 IOReturn dispatch(unsigned m,const void*,size_t,void*,size_t,const Clock*){
  assert(holding);++dispatches;if(m==NativeAdrenoMethodBoFree)++frees;return 0;
 }
 uint64_t windowPeak(){return 4096;}
 IOReturn releaseAll(const Clock*,uint32_t){assert(holding);if(!closeError)entry.mapping_leases=0;return closeError;}
};
CORE_UNMAP
struct AGXDeviceUserClient {
 bool live_=true,view_teardown_=false;IOReturn view_error_=0,dropError=0;
 NativeAdrenoUserClient storage,*core_=&storage;
 bool kernel_=true;unsigned slot_=0;char name_[20]="kernel";int refs=1,terminates=0;
 unsigned drops=0;std::function<void()> dropping;
 GUARDS
 void dropViews(uint32_t){assert(!holding && view_teardown_);++drops;if(dropping)dropping();if(dropError)view_error_=dropError;}
 void release(){--refs;}
 void terminate(){++terminates;}
 IOReturn clientClose();
 IOReturn run(uint32_t,const void*,size_t,void*,size_t,task_t=nullptr);
};
AGXDeviceUserClient *gMailboxOwner=nullptr;
DISPATCH
METHODS
CLOSE
int main(){
 AGXDeviceUserClient c;
 NativeAdrenoAbiBoCpuUnmap u{17,3,0};
 auto release=[&](size_t is=sizeof u,size_t os=0){return c.run(NativeAdrenoMethodBoCpuUnmap,&u,is,nullptr,os);};
 // Wrong handle, stale token, reserved bits and malformed records have no view side effects.
 for(unsigned which=0;which<6;++which){
  u={17,3,0};if(which==0)u.handle=99;if(which==1)u.token=4;if(which==2)u.reserved=1;
  if(which==5)c.storage.entry.mapping_leases=0;
  assert(release(which==3?sizeof u-1:sizeof u,which==4?1:0)!=0);
  assert(!c.drops && !c.view_teardown_);
 }
 c.storage.entry.mapping_leases=2;u={17,3,0};
 assert(!release() && c.storage.entry.mapping_leases==1 && !c.drops && native_adreno_view_kept==1);
 // Force another thread into BO free while IOKit is removing the last view.
 // It must sleep without retaining g.lock, then run only after removal.
 std::thread worker;std::atomic<bool> returned{false};
 c.dropping=[&]{
  unsigned before=sleepers.load();
  worker=std::thread([&]{assert(!c.run(NativeAdrenoMethodBoFree,nullptr,0,nullptr,0));returned=true;});
  while(sleepers.load()==before)std::this_thread::yield();
  assert(!returned && !c.storage.frees);
 };
 assert(!release());worker.join();assert(returned && c.storage.frees==1 && c.drops==1 && !c.view_teardown_);
 c.dropping={};
 assert(release()!=0 && c.drops==1); // Repeated last lease cannot destroy another view.
 NativeAdrenoAbiBoImport in{0x4000,0x4000};NativeAdrenoAbiBoAllocReply out{};
 assert(!c.run(NativeAdrenoMethodBoImport,&in,sizeof in,&out,sizeof out) && c.storage.task==current_task());
 assert(!c.run(NativeAdrenoMethodBoImport,&in,sizeof in,&out,sizeof out,(void*)0x7777));
 assert(c.storage.task==(void*)0x7777 && out.handle==23); // mailbox owner's address space
 unsigned imports=c.storage.imports;
 assert(c.run(NativeAdrenoMethodBoImport,&in,sizeof in-1,&out,sizeof out)!=0 && c.storage.imports==imports);
 // Close uses the same drain gate; a concurrent import resumes to NotReady,
 // instead of operating after the BOs were released.
 returned=false;c.dropping=[&]{
  unsigned before=sleepers.load();
  worker=std::thread([&]{assert(c.run(NativeAdrenoMethodBoImport,&in,sizeof in,&out,sizeof out)==kIOReturnNotReady);returned=true;});
  while(sleepers.load()==before)std::this_thread::yield();
  assert(!returned);
 };
 assert(!c.clientClose());worker.join();assert(!c.live_ && !c.view_teardown_ && c.terminates==1);
 assert(c.storage.imports==imports);c.dropping={};
 AGXDeviceUserClient failed;failed.storage.closeError=kIOReturnBusy;
 assert(failed.clientClose()==kIOReturnBusy && failed.live_ && !failed.terminates && !failed.view_teardown_);
 failed.storage.closeError=0;assert(!failed.clientClose() && !failed.live_ && failed.terminates==1);
 AGXDeviceUserClient broken;broken.dropError=77;u={17,3,0};
 assert(broken.run(NativeAdrenoMethodBoCpuUnmap,&u,sizeof u,nullptr,0)==77);
 assert(broken.run(NativeAdrenoMethodBoFree,nullptr,0,nullptr,0)==77 && !broken.storage.frees);
 assert(broken.run(NativeAdrenoMethodBoImport,&in,sizeof in,&out,sizeof out)==77 && !broken.storage.imports);
 assert(broken.clientClose()==77 && broken.live_ && !broken.terminates);
 puts("PASS: production dispatch/close, real lease validation, final-view/free and close/import races, task identity and failed-close retry");
}
'''
        fixture = fixture.replace('CORE_UNMAP', unmap).replace('GUARDS', guards).replace('DISPATCH', dispatch).replace('METHODS', methods).replace('CLOSE', close)
        path=root/'lifecycle.cpp';path.write_text(fixture)
        subprocess.run([cxx,'-std=c++17','-Wall','-Wextra','-Werror','-pthread','-fsanitize=undefined',
                        '-I',root/'source/NativeAdreno',path,'-o',root/'lifecycle'],check=True)
        subprocess.run([root/'lifecycle'],check=True,timeout=15)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--references',type=Path,required=True);p.add_argument('--cxx',default='c++')
    a=p.parse_args();check(a.references.resolve(),a.cxx)
