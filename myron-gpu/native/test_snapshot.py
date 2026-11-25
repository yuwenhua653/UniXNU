#!/usr/bin/env python3
"""Compile the actual GPU diagnostic formatter and check all output bounds."""
import argparse
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser();p.add_argument('--cxx',default='c++');a=p.parse_args()
here=Path(__file__).resolve().parent
source=(here/'MyronGpuService.cpp').read_text()
start=source.index('extern "C" size_t myron_gpu_snapshot(')
body=source[start:source.index('extern "C" void myron_gpu_run',start)]
mode7=source[source.index('struct Mode7 {'):source.index('// Mode 8 (command processor).')]
fixture=r'''
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <cassert>
#include "MyronGpuBoard.h"
MODE7
Mode7 gM7{};
struct {uintptr_t va;} gSmmu{1};
struct {uint32_t ctx_status,buf_status,sqe_alloc,sqe_map;}gM8{};
struct {int64_t auth;}gM9{};
struct {uint32_t ring_attach,cp_init,init_seen,init_fence,timer,publish;
 int init_wait,write_wait,secure_wait,nop_wait;}gM10{};
uint32_t myron_gpu_complete=1,myron_gpu_stage=1,myron_gpu_ready=0,myron_metal_registered=0;
uint32_t myron_metal_stage=0,myron_metal_status=0,gpuResult[11]={};
BODY
int main(){
 gM7.ran=1;gM7.slices=7;gM7.checked=gM7.matched=118;
 gM8.ctx_status=0xe00002d8u;gM10.init_wait=-1;gM10.init_fence=4294967295u;gM9.auth=-22;
 char text[1025];
 assert(myron_gpu_snapshot(nullptr,100)==0);
 for(size_t cap=0;cap<=1024;cap++){
  memset(text,0x55,sizeof text);size_t n=myron_gpu_snapshot(text,cap);
  assert(text[cap]==0x55);
  if(cap)assert(n<cap&&text[n]==0);else assert(n==0);
 }
 size_t n=myron_gpu_snapshot(text,768);assert(n<767);
 assert(strstr(text,"ctx=e00002d8")&&strstr(text,"wait=-1")&&strstr(text,"zap_auth=-22"));
 myron_gpu_complete=0;myron_gpu_snapshot(text,sizeof text);assert(!strstr(text,"gpu_cp"));
 puts("PASS actual GPU snapshot: all capacities 0..1024, complete-only details, 768-byte log budget");
}
'''.replace('MODE7',mode7).replace('BODY',body)
with tempfile.TemporaryDirectory() as tmp:
 src=Path(tmp)/'snapshot.cpp';exe=Path(tmp)/'snapshot';src.write_text(fixture)
 subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',here.parent,src,'-o',exe],check=True)
 subprocess.run([exe],check=True)
