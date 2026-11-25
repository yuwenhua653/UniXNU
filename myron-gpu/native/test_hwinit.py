#!/usr/bin/env python3
"""Run the actual mode7 sequence; model the documented gen8.2 register readback.

No GPU execution. Reproduce both the legacy UBWC6 write and the real myron
busy-mask readback failure. Corrected register contracts still check full words.
"""
import argparse, subprocess, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cxx',default='c++');a=p.parse_args()
s=(HERE/'MyronGpuService.cpp').read_text()
state=s[s.index('struct Mode7 {'):s.index('// Mode 8 (command processor).')]
code=s[s.index('uint32_t gpuRd('):s.index('// Mode 8. The command processor')]
prereq=s[s.index('    if (!gM7.ran ||'):s.index('    m.ran = 1;',s.index('bool cpPrepare()'))]
fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <map>
#include "MyronA840HwInit.h"
#include "MyronA840RenderConfig.h"
enum {MGM_WIN_GPU=2,MGM_WIN_CXMISC=3};
STATE
Mode7 gM7{};struct {unsigned step=9,pwr_after=0;}gM6;
struct {uintptr_t va=1;}gSmmu;
std::map<uint64_t,uint32_t> regs;
unsigned selected=0,writeCount=0;
uint32_t badReg=0,flipBit=0,ioFail=0;
int gwr(void*,unsigned win,uint32_t off,uint32_t val){
 assert(win==MGM_WIN_GPU);++writeCount;
 if(ioFail && off==ioFail*4)return -1;
 if(off==A840_CP_APERTURE_CNTL_HOST*4){selected=val>>12;return 0;}
 regs[(uint64_t(selected)<<32)|off]=val;return 0;
}
int grd(void*,unsigned win,uint32_t off,uint32_t*out){
 if(win==MGM_WIN_CXMISC){*out=off==A840_CX_MISC_SLICE_ENABLE_FINAL*4?7:0;return 0;}
 *out=regs[(uint64_t(selected)<<32)|off];
 // Same-SoC successful GPU record: RB_CMP bits 1-2 do not read back as 1.
 // KGSL UBWC6 initializes both corresponding feature fields to zero.
 if(selected==A840_PIPE_BR && off==A840_RB_CMP_NC_MODE_CNTL*4)*out&=~6u;
 // myron register peer: the all-ones write reads back only ten bits.
 if(selected==A840_PIPE_NONE && off==A840_RBBM_PERFCTR_GPU_BUSY_MASKED*4)*out&=0x3ffu;
 if(off==badReg*4)*out^=flipBit;
 return 0;
}
CODE
bool cpPrerequisite(){PREREQ return true;}
void reset(){gM7={};gM6={9,0};gSmmu.va=1;regs.clear();selected=writeCount=badReg=flipBit=0;ioFail=0;}
int main(){
 reset();mode7();
#if LEGACY == 2
 assert(gM7.ran && !gM7.io_errors && !cpPrerequisite());
 assert(gM7.checked==118 && gM7.matched==117);
 assert(gM7.bad_reg==A840_RBBM_PERFCTR_GPU_BUSY_MASKED);
 assert(gM7.bad_got==0x3ff && gM7.bad_want==0xffffffffu);
 puts("PASS negative: real myron 0x19e readback reproduces pre-CP refusal");
#elif LEGACY == 1
 assert(gM7.ran && !gM7.io_errors && !cpPrerequisite());
 assert(gM7.checked==118 && gM7.matched==117);
 assert(gM7.bad_reg==((A840_PIPE_BR<<20)|A840_RB_CMP_NC_MODE_CNTL));
 assert(gM7.bad_want==0x28046 && gM7.bad_got==0x28040);
 puts("PASS negative: old UBWC6 write reproduces pre-CP refusal (117/118 readbacks)");
#else
 assert(cpPrerequisite() && gM7.checked==118 && gM7.matched==118);
 assert(regs[(uint64_t(A840_PIPE_BR)<<32)|A840_RB_CMP_NC_MODE_CNTL*4]==0x28040);
 assert(regs[A840_RBBM_PERFCTR_GPU_BUSY_MASKED*4]==0xffffffffu);
 for(unsigned i=0;i<20;++i)assert(regs[(MYRON_A840_BICUBIC_BASE+i)*4]==MyronA840Bicubic[i]);
 const uint32_t checkedRegs[]={A840_RB_CMP_NC_MODE_CNTL,A840_CP_PROTECT_GLOBAL(0),A840_RBBM_INT_0_MASK,
                   A840_UCHE_TRAP_BASE,A840_RBBM_PERFCTR_GPU_BUSY_MASKED};
 for(uint32_t reg:checkedRegs) {
  for(unsigned bit=0;bit<32;++bit){
   reset();badReg=reg;flipBit=1u<<bit;mode7();
   assert(!cpPrerequisite() && gM7.matched<gM7.checked);
  }
 }
 reset();ioFail=A840_RBBM_INT_0_MASK;mode7();assert(gM7.io_errors && !cpPrerequisite());
 reset();ioFail=MYRON_A840_BICUBIC_BASE+1;mode7();assert(gM7.io_errors && !cpPrerequisite());
 reset();gM6.step=8;mode7();assert(!gM7.ran && !writeCount && !cpPrerequisite());
 reset();gM6.pwr_after=1;mode7();assert(!gM7.ran && !writeCount && !cpPrerequisite());
 reset();mode7();gSmmu.va=0;assert(!cpPrerequisite());
 puts("PASS: actual hw_init, UBWC6 and busy-mask readback; 160 bit corruptions and IO/power/SMMU faults still refuse CP");
#endif
}
'''.replace('STATE',state).replace('PREREQ',prereq)
with tempfile.TemporaryDirectory() as tmp:
 for legacy in (0,1,2):
  body=code
  if legacy==1:body=body.replace('MYRON_A840_RB_CMP_UBWC6','A840_UBWC_RB_CMP_NC_MODE_CNTL')
  if legacy==2:body=body.replace('MYRON_A840_GPU_BUSY_READBACK','0xffffffffu')
  src=Path(tmp)/'test.cpp';out=Path(tmp)/'test';src.write_text(fixture.replace('CODE',body))
  subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined',f'-DLEGACY={legacy}','-I',HERE,src,'-o',out],check=True)
  subprocess.run([out],check=True)
