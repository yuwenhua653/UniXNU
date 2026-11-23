#!/usr/bin/env python3
"""Verify actual cached-view draining against XNU's retained-map return contract."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from prepare_sources import stage


def check(references, cxx):
    with tempfile.TemporaryDirectory(prefix='myron-publish-views-') as tmp:
        root=Path(tmp);stage(references,root/'source')
        source=(root/'source/NativeAdreno/NativeAdrenoPublish.cpp').read_text()
        start=source.index('void AGXDeviceUserClient::dropViews(')
        code=source[start:source.index('IOReturn AGXDeviceUserClient::clientClose()',start)]
        fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <vector>
using IOReturn=int;
struct {void *lock;}g;
bool locked=false;
void IOLockLock(void*){assert(!locked);locked=true;}
void IOLockUnlock(void*){assert(locked);locked=false;}
struct {unsigned forced_unmaps=0;}native_adreno_metal_diag;
struct IOMemoryMap {
 bool mapped=true;int refs=1,error=0;unsigned unmaps=0,releases=0;
 int unmap(){assert(!locked);++unmaps;if(!error)mapped=false;return error;}
 void release(){assert(!locked && refs>0);--refs;++releases;}
};
struct IOMemoryDescriptor {
 unsigned releases=0;std::vector<IOMemoryMap*> maps;
 void release(){assert(!locked && maps.empty());++releases;}
};
class AGXDeviceUserClient {
public:
 struct View {uint32_t token;IOMemoryDescriptor *descriptor;};
 enum {MaxViews=4};View views_[MaxViews]{};IOReturn view_error_=0;
 IOMemoryMap *removeMappingForDescriptor(IOMemoryDescriptor *d){
  assert(!locked);
  if(d->maps.empty())return nullptr;
  auto *map=d->maps.back();d->maps.pop_back();
  // XNU retains then removes its collection reference: returned +1 stays live.
  return map;
 }
 void dropViews(uint32_t);
};
CODE
int main(){
 AGXDeviceUserClient c;IOMemoryDescriptor a,b;IOMemoryMap one,two,three;
 two.refs=2; // An independent holder must not keep a forced mapping usable.
 a.maps={&one,&two};b.maps={&three};c.views_[0]={3,&a};c.views_[1]={4,&b};
 c.dropViews(99);assert(!a.releases && !b.releases && one.mapped && two.mapped);
 c.dropViews(3);assert(!one.mapped && !two.mapped && three.mapped);
 assert(one.refs==0 && two.refs==1 && one.releases==1 && two.releases==1 && a.releases==1);
 assert(!c.views_[0].descriptor && c.views_[1].descriptor==&b && native_adreno_metal_diag.forced_unmaps==2);
 c.dropViews(3);assert(a.releases==1);c.dropViews(0);assert(!three.mapped && b.releases==1 && !three.refs);
 IOMemoryDescriptor bad;IOMemoryMap failed,later;failed.error=31;later.error=32;
 bad.maps={&later,&failed};c.views_[0]={5,&bad};c.dropViews(0);
 assert(c.view_error_==31 && failed.releases==1 && later.releases==1 && bad.releases==1);
 assert(native_adreno_metal_diag.forced_unmaps==3 && !locked);
 puts("PASS: actual view removal, retained-map references, explicit revocation with another holder, token isolation and unmap failure quarantine");
}
'''.replace('CODE',code)
        path=root/'views.cpp';path.write_text(fixture)
        subprocess.run([cxx,'-std=c++17','-Wall','-Wextra','-Werror','-Wno-address','-fsanitize=undefined',path,'-o',root/'views'],check=True)
        subprocess.run([root/'views'],check=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--references',type=Path,required=True);p.add_argument('--cxx',default='c++')
    a=p.parse_args();check(a.references.resolve(),a.cxx)
