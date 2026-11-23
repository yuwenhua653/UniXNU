#!/usr/bin/env python3
"""Run the production button reader against bounded fake MMIO, not a phone."""
import argparse
from pathlib import Path
import os
import subprocess
import tempfile
p=argparse.ArgumentParser();p.add_argument('--cxx',default='c++');a=p.parse_args()
here=Path(__file__).resolve().parent;touch=here.parent/'myron-touch'
with tempfile.TemporaryDirectory() as tmp:
 t=Path(tmp);source=(touch/'MyronPowerHardware.h').read_text()
 for op in ('dsb sy','dsb osh','dmb oshld','dmb oshst'):
  source=source.replace('__asm__ volatile("'+op+'":::"memory")','__asm__ volatile("":::"memory")')
 (t/'hardware.h').write_text(source)
 (t/'test.cpp').write_text(r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
static uint32_t core[1024],maps[8192],owners[8192],observer[65536],pad[1024];
static unsigned live;
static constexpr unsigned apid=7,off=32*apid/4;
static constexpr unsigned kIOMapAnywhere=1,kIOMapInhibitCache=2;
static void IODelay(unsigned){}
#define IOLog(...) ((void)0)
struct IOMemoryMap {
 uint32_t *p;
 explicit IOMemoryMap(uint32_t *v):p(v){++live;}
 uintptr_t getVirtualAddress(){return reinterpret_cast<uintptr_t>(p);}
 void release(){--live;delete this;}
};
struct IODeviceMemory {
 uint32_t *p;
 static IODeviceMemory *withRange(uint64_t address,unsigned bytes){
  uint32_t *p=nullptr;
  if(address==0xc400000){assert(bytes==0x1000);p=core;}
  if(address==0xc403000){assert(bytes==0x8000);p=maps;}
  if(address==0xc42a000){assert(bytes==0x8000);p=owners;}
  if(address==0xc4c0000){assert(bytes==0x40000);p=observer;}
  if(address==0xf165000){assert(bytes==0x1000);p=pad;}
  assert(p);return new IODeviceMemory{p};
 }
 IOMemoryMap *map(unsigned flags){assert(flags==3);return new IOMemoryMap(p);}
 void release(){delete this;}
};
#define OSSafeReleaseNULL(x) do{if(x){(x)->release();(x)=nullptr;}}while(0)
#include "hardware.h"
int main(){
 core[0]=0x80000000;core[1]=8;maps[apid]=0x13;observer[off+2]=1;
 for(unsigned config: {0u,4u,512u}){
  pad[0]=config;pad[1]=1;observer[off+6]=0;MyronPowerHardware key;
  assert(key.open());assert(key.volumeAvailable()==(config==0));
  assert(pad[0]==(config==0?3u:config));key.poll();key.poll();
  pad[1]=0;observer[off+6]=0xc0;key.poll();key.poll();
  assert(key.report()==(config==0?7:5));assert(key.pending());key.accepted();assert(!key.pending());
  assert(key.volumeDownPresses==1);assert(key.volumeUpPresses==(config==0?1u:0u));
  observer[off+2]=2;key.poll();key.poll();assert(key.errors==2);assert(!key.state.stable&&!key.down.stable);
  observer[off+2]=1;observer[off+6]=0;pad[1]=1;key.poll();key.poll();key.accepted();
  observer[off+6]=0x40;key.poll();key.poll();assert(key.report()==4&&key.pending());
  assert(key.volumeDownPresses==2);key.close();assert(pad[0]==config && live==0);
 }
 puts("PASS: actual key MMIO reader, GPIO ownership/pull restoration, up/down combinations and SPMI timeout recovery");
}
'''.replace('#include <cstdio>','#include <cstdio>\n#include <initializer_list>'))
 subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(t),'-I',str(touch),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
