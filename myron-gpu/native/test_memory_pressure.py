#!/usr/bin/env python3
"""Exercise actual staged BO allocation/release against IOKit failure peers."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from prepare_sources import stage

p=argparse.ArgumentParser();p.add_argument('--references',type=Path,required=True);p.add_argument('--cxx',default='c++');a=p.parse_args()
here=Path(__file__).resolve().parent
fixture=(a.references/'NativeAdreno/tests').resolve()
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);stage(a.references,root/'src');driver=root/'src/NativeAdreno'
    for name in ('IOKit/IOTypes.h','IOKit/IOLib.h','IOKit/IOBufferMemoryDescriptor.h','kern/task.h'):
        path=root/'include'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('#include "XnuMemoryFixture.h"\n')
    (root/'include/HostTypes.h').write_text('#pragma once\nusing IODirection=unsigned;\nconstexpr unsigned kIOMemoryPersistent=0x10000;\n')
    # Host has no ARM cache barrier; the only substitution is this architecture
    # primitive. Actual allocator, cleanup, counters and budget run unchanged.
    memory=(driver/'NativeAdrenoMemory.cpp').read_text()
    assert memory.count('__asm__ volatile("dsb sy":::"memory")')==1
    (driver/'NativeAdrenoMemory.cpp').write_text(memory.replace('__asm__ volatile("dsb sy":::"memory")','((void)0)'))
    baseline=(fixture/'test_memory.cpp').read_text().replace('int main()','int baseline_main()')
    test=root/'test.cpp'
    test.write_text(baseline+'''
#include "MyronGpuPolicy.h"
extern "C" volatile uint32_t myron_gpu_overflow_stats[4];
int main(){
 constexpr size_t half=MYRON_GPU_OVERFLOW_BYTES/2;
 // No reserved pool: exercise the same fallback the exhausted pool takes.
 NativeAdrenoMemory a,b,c;
 CHECK(a.allocate(half,40,false,half,true)==0);
 CHECK(b.allocate(half,40,false,half,true)==0);
 CHECK(myron_gpu_overflow_stats[0]==MYRON_GPU_OVERFLOW_BYTES);
 auto made=fixture.created;
 CHECK(c.allocate(4096,40,false,4096,true)==kIOReturnNoResources);
 CHECK(fixture.created==made);
 CHECK(a.holdForDevice()==0 && a.release()==kIOReturnBusy);
 CHECK(myron_gpu_overflow_stats[0]==MYRON_GPU_OVERFLOW_BYTES);
 CHECK(a.retireAfterQuiescence()==0 && a.release()==0);
 CHECK(c.allocate(4096,40,false,4096,true)==0);
 CHECK(b.release()==0 && c.release()==0 && !myron_gpu_overflow_stats[0]);
 CHECK(c.release()==0 && !myron_gpu_overflow_stats[0]);
 // Allocation/prepare/metadata/cache failures must roll back the charge.
 for(unsigned failure=0;failure<4;++failure){
  reset();NativeAdrenoMemory m;
  fixture.allocation_fail=failure==0;fixture.prepare_fail=failure==1;
  fixture.metadata_fail=failure==2;fixture.cache_fail_call=failure==3?1:0;
  CHECK(m.allocate(16384,40,false,16384,true)!=0);
  CHECK(!myron_gpu_overflow_stats[0] && fixture.live.empty());
 }
 reset();NativeAdrenoMemory m;
 CHECK(m.allocate(16384,40,false,16384,true)==0);
 fixture.complete_fail=true;CHECK(m.release()!=0 && m.quarantined());
 CHECK(myron_gpu_overflow_stats[0]==16384);
 // Quarantined pages remain charged; never recycle DMA-unsafe memory.
 CHECK(m.release()==kIOReturnBusy && myron_gpu_overflow_stats[0]==16384);
 discardFixtureAfterQuarantine();myron_gpu_overflow_stats[0]=0;
 puts("PASS bounded BO overflow: cap, reuse, failures, DMA holds, quarantine");
 return 0;
}
''')
    exe=root/'test'
    subprocess.run([a.cxx,'-std=c++17','-Wno-return-type','-fsanitize=address,undefined','-g','-O1','-include',root/'include/HostTypes.h',
        '-I',root/'include','-I',fixture,'-I',driver,'-I',here,test,driver/'NativeAdrenoMemory.cpp','-o',exe],check=True)
    subprocess.run([exe],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
