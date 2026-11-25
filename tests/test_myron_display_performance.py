#!/usr/bin/env python3
"""Exercise the generated GOP map fallback, timing formatter and output bounds."""
import argparse
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument('--device',type=Path,required=True)
p.add_argument('--cxx',default='c++')
a=p.parse_args()
display=a.device/'display'
source=(display/'NativeLegacyDisplay.cpp').read_text()
probe=(display/'MyronDisplayProbe.cpp').read_text()
begin=source.index('        unsigned scanoutMode=')
mapping=source[begin:source.index('        bool valid=',begin)]
begin=probe.index('volatile uint32_t myron_display_stage')
globals=probe[begin:probe.index('\n}\nstatic IOService',begin)].replace('static uint32_t openCompletions;','')
begin=probe.index('extern "C" size_t myron_display_snapshot(')
formatter=probe[begin:probe.index('// Functional hand-off:',begin)]
begin=probe.index('extern "C" void myron_display_mapping_observed(')
callbacks=probe[begin:probe.index('extern "C" void native_legacy_vsync_observed(',begin)]
callbacks=callbacks.replace('uint64_t hz;__asm__ volatile("mrs %0, cntfrq_el0":"=r"(hz));','uint64_t hz=19200000;')
assert '__asm__' not in callbacks
assert 'mdpMap=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;' in source
assert source.count('native_legacy_copy_timing_observed(copyEnd-copyStart,')==4
fixture=r'''
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <cassert>
using IOReturn=int;using task_t=void*;
GLOBALS
volatile uint32_t native_legacy_swapstat[16];
CALLBACKS
FORMATTER
enum {kIOMapWriteCombineCache=0x400,kIOMapInhibitCache=0x100};
struct IOMemoryMap {} mapped;
struct Provider {
 bool wc=true,device=true;unsigned calls=0,flags[2]{};
 IOMemoryMap *mapDeviceMemoryWithIndex(unsigned index,unsigned mode){
  assert(index==0&&calls<2);flags[calls++]=mode;
  return (mode==kIOMapWriteCombineCache?wc:device)?&mapped:nullptr;
 }
};
bool requestMap(Provider *provider){MAPPING return true;}
int main(){
 Provider p;
 assert(requestMap(&p)&&p.calls==1&&p.flags[0]==kIOMapWriteCombineCache&&scanoutMapRequest==kIOMapWriteCombineCache);
 p=Provider{};p.wc=false;
 assert(requestMap(&p)&&p.calls==2&&p.flags[1]==kIOMapInhibitCache&&scanoutMapRequest==kIOMapInhibitCache);
 p=Provider{};p.wc=p.device=false;
 assert(!requestMap(&p)&&p.calls==2&&!scanoutMapRequest);
 native_legacy_copy_timing_observed(19200,12518400);
 native_legacy_copy_timing_observed(9600,12);
 assert(copySamples==2&&copyLastTicks==9600&&copyMaxTicks==19200&&copyTotalTicks==28800&&copyCounterHz==19200000);
 assert(copyTotalBytes==12518412);
 for(unsigned i=0;i<5;++i)myron_display_copy_path_observed(i);
 for(unsigned i=0;i<4;++i)assert(copyPaths[i]==1);
 for(auto &row:firstOpens){row={UINT32_MAX,INT32_MAX,-1,1};}
 copyTotalBytes=copyTotalTicks=copyMaxTicks=copyLastTicks=UINT64_MAX;
 char text[1537];
 assert(myron_display_snapshot(nullptr,10)==0);
 for(size_t cap=0;cap<=1536;++cap){
  memset(text,0x55,sizeof text);size_t n=myron_display_snapshot(text,cap);
  assert(text[cap]==0x55);if(cap)assert(n<cap&&text[n]==0);else assert(!n);
 }
 size_t n=myron_display_snapshot(text,1536);assert(n<1535);
 assert(strstr(text,"display_copy map_request=")&&strstr(text,"display_open[7]"));
 puts("PASS generated GOP mapping fallback, original MMIO mapping, four copy paths, timing and snapshot bounds");
}
'''.replace('GLOBALS',globals).replace('CALLBACKS',callbacks).replace('FORMATTER',formatter).replace('MAPPING',mapping)
with tempfile.TemporaryDirectory() as tmp:
    src=Path(tmp)/'test.cpp';exe=Path(tmp)/'test';src.write_text(fixture)
    subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined',src,'-o',exe],check=True)
    subprocess.run([exe],check=True)
