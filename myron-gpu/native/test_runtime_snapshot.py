#!/usr/bin/env python3
"""Compile the live provider with the pinned backend's real diagnostic fields."""
import argparse
from pathlib import Path
import subprocess
import tempfile
p=argparse.ArgumentParser();p.add_argument('--references',type=Path,required=True);p.add_argument('--cxx',default='c++');a=p.parse_args()
here=Path(__file__).resolve().parent
source=(a.references/'NativeAdreno/NativeAdrenoPublish.cpp').read_text()
start=source.index('struct NativeAdrenoMetalDiag {')
diag=source[start:source.index('} native_adreno_metal_diag;',start)+len('} native_adreno_metal_diag;')]
fixture='''#include <cstdint>
#include <cassert>
bool busy=false,locked=false;
struct Ring {uint32_t lastSubmitted(){assert(locked);return 9;} uint32_t completedFence(){assert(locked);return 8;} bool poisoned(){return true;}} ring;
struct {void *lock=(void*)1;Ring *ring=&::ring;} g;
bool IOLockTryLock(void*){if(busy)return false;locked=true;return true;}
void IOLockUnlock(void*){assert(locked);locked=false;}
'''+diag+'''
#include "MyronGpuRuntimeProvider.h"
int main(){
 MyronGpuRuntime out{};myron_gpu_runtime(nullptr);
 native_adreno_metal_diag.opens=7;native_adreno_metal_diag.calls=99;
 myron_gpu_runtime(&out);assert(out.available&&out.opens==7&&out.calls==99&&out.submitted==9&&out.retired==8&&out.poisoned&&!locked);
 busy=true;myron_gpu_runtime(&out);assert(!out.available&&!out.opens&&!out.submitted&&!locked);
 busy=false;g.ring=nullptr;myron_gpu_runtime(&out);assert(out.available&&!out.submitted&&!locked);
 g.lock=nullptr;myron_gpu_runtime(&out);assert(!out.available);
}
'''
with tempfile.TemporaryDirectory() as tmp:
 src=Path(tmp)/'test.cpp';exe=Path(tmp)/'test';src.write_text(fixture)
 subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',here,src,'-o',exe],check=True)
 subprocess.run([exe],check=True)
print('PASS live GPU provider: pinned fields, busy/null refusal, ring counters under lock, no MMIO')
