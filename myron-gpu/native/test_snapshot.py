#!/usr/bin/env python3
"""Compile the actual GPU diagnostic formatter and check all output bounds."""
import argparse
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser();p.add_argument('--cxx',default='c++');a=p.parse_args()
here=Path(__file__).resolve().parent
# The source tree keeps board headers above native/; the build stages both
# the board header and this test together in device/myron27/gpu/.
board_headers=here if (here/'MyronGpuBoard.h').is_file() else here.parent
if not (board_headers/'MyronGpuBoard.h').is_file():
 raise FileNotFoundError('Missing real MyronGpuBoard.h in source or staged GPU directory')
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
#include "MyronGpuRuntime.h"
#include "MyronGpuPolicy.h"
extern "C" void myron_gpu_runtime(MyronGpuRuntime *p){
 *p={};p->available=1;p->opens=2;p->calls=30;p->selector=4;p->mailbox=15;p->submitted=19;p->retired=18;
 for(auto &v:p->pool)v=UINT32_MAX;
 for(auto &c:p->clients)for(auto &v:c)v=UINT32_MAX;
 for(auto &m:p->methods)for(auto &v:m)v=UINT32_MAX;
 for(auto &v:p->waits)v=UINT64_MAX;
 memset(p->owners,0xff,sizeof p->owners);memset(p->failures,0xff,sizeof p->failures);
 for(auto &v:p->overflow)v=UINT32_MAX;
}
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
 char text[6145];
 assert(myron_gpu_snapshot(nullptr,100)==0);
 for(size_t cap=0;cap<=6144;cap++){
  memset(text,0x55,sizeof text);size_t n=myron_gpu_snapshot(text,cap);
  assert(text[cap]==0x55);
  if(cap)assert(n<cap&&text[n]==0);else assert(n==0);
 }
 size_t n=myron_gpu_snapshot(text,6144);assert(n<6143);
 assert(strstr(text,"gpu_live valid=1 opens=2 calls=30")&&strstr(text,"submitted=19 retired=18"));
 assert(strstr(text,"gpu_method id=19")&&strstr(text,"gpu_client slot=4")&&strstr(text,"max_us=18446744073709551615"));
 assert(strstr(text,"gpu_overflow")&&strstr(text,"gpu_owner")&&strstr(text,"gpu_failure"));
 assert(strstr(text,"ctx=e00002d8")&&strstr(text,"wait=-1")&&strstr(text,"zap_auth=-22"));
 myron_gpu_complete=0;myron_gpu_snapshot(text,sizeof text);assert(!strstr(text,"gpu_cp"));
 puts("PASS actual GPU snapshot: all capacities 0..6144, complete-only details and live counters");
}
'''.replace('MODE7',mode7).replace('BODY',body)
with tempfile.TemporaryDirectory() as tmp:
 src=Path(tmp)/'snapshot.cpp';exe=Path(tmp)/'snapshot';src.write_text(fixture)
 subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',board_headers,'-I',here,src,'-o',exe],check=True)
 subprocess.run([exe],check=True)
