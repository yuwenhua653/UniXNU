#!/usr/bin/env python3
"""Execute the resolved Mesa dynamic-state macros with allocation failures.

This is a host control-flow test, not a Vulkan or device execution test.
The macros come from the actual patched source; only the allocator/emitter
boundaries are substituted. In particular an unsuccessful reservation leaves
the stream invalid, so emission/end after OOM is an assertion failure.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def check(source, cxx):
    text = (source / 'src/freedreno/vulkan/tu_pipeline.cc').read_text()
    start = text.index('#define EMIT_STATE', text.index('tu_emit_draw_state(struct'))
    end = text.index('\n   DRAW_STATE_COND(vertex_input', start)
    macros = text[start:end]
    fixture = r'''
#include <cassert>
#include <cstdint>
using VkResult = int;
constexpr int VK_SUCCESS=0, VK_ERROR_OUT_OF_DEVICE_MEMORY=-2;
constexpr int TU_CMD_DIRTY_FDM=1, TU_CMD_DIRTY_PER_VIEW_VIEWPORT=2;
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
struct tu_cs { bool valid=false, writeable=false; };
struct tu_draw_state { int size=0; };
struct Dynamic { bool dirty=true; };
struct Vk { Dynamic dynamic_graphics_state; int record_result=0; };
struct State {
 unsigned dirty=0,pipeline_draw_states=0;
 bool has_fdm=false,per_layer_viewport=false;
 tu_draw_state dynamic_state[3];
};
struct tu_cmd_buffer { Vk vk; State state; tu_cs sub_cs; void *device=nullptr; };
static unsigned allocations,emissions,ends,words=7;
static bool fail;
static int tu_probe_state[]={0};
static bool emit_draw_state(Dynamic *d,const int *,unsigned){return d->dirty;}
[[maybe_unused]] static void vk_command_buffer_set_error(Vk *v,int e){if(!v->record_result)v->record_result=e;}
static int tu_cs_begin_sub_stream(tu_cs *,unsigned size,tu_cs *cs){
 ++allocations;cs->valid=false;assert(size);
 if(fail)return VK_ERROR_OUT_OF_DEVICE_MEMORY;
 cs->valid=true;return VK_SUCCESS;
}
static tu_draw_state tu_cs_end_draw_state(tu_cs *,tu_cs *cs){
 assert(cs->valid);++ends;return {int(words)};
}
static void tu_cs_set_writeable(tu_cs *cs,bool on){cs->writeable=on;}
template<int> static unsigned tu6_probe_size(void *,int){return words;}
template<int> static void tu6_emit_probe(tu_cs *cs,int){assert(cs->valid);++emissions;}
static int tu6_emit_probe_fdm(tu_cs *cs,tu_cmd_buffer *cmd,int){
 int rc=tu_cs_begin_sub_stream(&cmd->sub_cs,words,cs);
 if(rc)return rc;
 tu6_emit_probe<0>(cs,0);return VK_SUCCESS;
}
''' + macros + r'''
template<int CHIP> static uint32_t record(tu_cmd_buffer *cmd,bool fdm){
 tu_cs cs;uint32_t dirty_draw_states=0;
 if(fdm){DRAW_STATE_FDM(probe,0,0);}
 else {DRAW_STATE_COND(probe,0,false,0);}
 return dirty_draw_states;
}
static void reset(){allocations=emissions=ends=0;fail=false;words=7;}
int main(){
 for(bool fdm:{true,false}){
  reset();tu_cmd_buffer c;assert(record<0>(&c,fdm)==1);
  assert(allocations==1 && emissions==1 && ends==1 && c.state.dynamic_state[0].size==7);
  reset();c={};words=0;c.state.dynamic_state[0].size=55;
  assert(record<0>(&c,fdm)==1 && c.state.dynamic_state[0].size==0);
  assert(!allocations && !emissions && !ends);
  reset();c={};fail=true;c.state.dynamic_state[0].size=55;
  assert(record<0>(&c,fdm)==0 && c.vk.record_result==VK_ERROR_OUT_OF_DEVICE_MEMORY);
  assert(allocations==1 && !emissions && !ends && c.state.dynamic_state[0].size==55);
  reset();c={};c.vk.dynamic_graphics_state.dirty=false;
  assert(!record<0>(&c,fdm) && !allocations);
  reset();c={};c.state.pipeline_draw_states=1;
  assert(!record<0>(&c,fdm) && !allocations);
 }
 for(bool layer:{false,true})for(bool oom:{false,true}){
  reset();tu_cmd_buffer c;c.state.has_fdm=!layer;c.state.per_layer_viewport=layer;fail=oom;
  assert(record<0>(&c,true)==(oom?0u:1u));
  assert(allocations==1 && emissions==(oom?0u:1u) && ends==emissions);
  assert(!c.sub_cs.writeable && c.vk.record_result==(oom?-2:0));
 }
}
'''
    fixture = fixture.replace('#include <cassert>', '#include <cassert>\n#include <initializer_list>')
    with tempfile.TemporaryDirectory(prefix='turnip-dynamic-state-') as tmp:
        src, exe = Path(tmp)/'fixture.cc', Path(tmp)/'fixture'
        src.write_text(fixture)
        subprocess.run([cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', str(src), '-o', str(exe)], check=True)
        subprocess.run([exe], check=True)
    print('PASS: actual Turnip dynamic-state macros, 14 success/zero/OOM/skip/FDM cases')
    check_substream(source, cxx)


def check_substream(source, cxx):
    text=(source/'src/freedreno/vulkan/tu_cs.cc').read_text()
    start=text.index('VkResult\ntu_cs_begin_sub_stream_aligned(')
    end=text.index('\n}',start)+2
    body=text[start:end]
    fixture=r'''
#include <cassert>
#include <cstdint>
#include <initializer_list>
using VkResult=int;
constexpr int VK_SUCCESS=0,VK_ERROR_OUT_OF_DEVICE_MEMORY=-2;
constexpr int TU_CS_MODE_SUB_STREAM=1,TU_CS_MODE_EXTERNAL=2;
struct tu_cs {
 int mode=TU_CS_MODE_SUB_STREAM;uint32_t *base,*start,*cur,*end,*reserved_end;
 void *device=nullptr;bool writeable=false;
};
static uint32_t fresh[64];static bool fail;static unsigned calls;
static uint32_t tu_cs_get_space(tu_cs *cs){return cs->end-cs->cur;}
static uint32_t tu_cs_get_offset(tu_cs *cs){return cs->start-cs->base;}
static uint64_t tu_cs_get_cur_iova(tu_cs *cs){return 0x1000+(cs->cur-cs->base)*4;}
static int tu_cs_reserve_space(tu_cs *cs,uint32_t n){
 ++calls;
 if(cs->mode!=TU_CS_MODE_EXTERNAL && fail && tu_cs_get_space(cs)<n)return VK_ERROR_OUT_OF_DEVICE_MEMORY;
 if(tu_cs_get_space(cs)<n){assert(cs->mode!=TU_CS_MODE_EXTERNAL);cs->base=cs->start=cs->cur=fresh;cs->end=fresh+64;}
 cs->reserved_end=cs->cur+n;return VK_SUCCESS;
}
static void tu_cs_init_external(tu_cs *cs,void *device,uint32_t *start,uint32_t *end,uint64_t,bool writeable){
 *cs={TU_CS_MODE_EXTERNAL,start,start,start,end,end,device,writeable};
}
static void tu_cs_begin(tu_cs *){}
''' + body + r'''
int main(){
 uint32_t storage[64]={};
 for(unsigned available:{2u,9u,20u})for(bool oom:{false,true}){
  tu_cs parent={TU_CS_MODE_SUB_STREAM,storage,storage+1,storage+1,storage+1+available,storage+1};
  tu_cs sub={TU_CS_MODE_EXTERNAL,storage+40,storage+40,storage+40,storage+44,storage+44};
  fail=oom;calls=0;
  int result=tu_cs_begin_sub_stream_aligned(&parent,2,4,&sub);
  if(oom && available<11){
   assert(result==VK_ERROR_OUT_OF_DEVICE_MEMORY && calls==1);
   assert(parent.start==storage+1 && parent.cur==storage+1 && sub.start==storage+40);
  }else{
   assert(result==VK_SUCCESS && calls==2 && (parent.start-parent.base)%4==0);
   assert(sub.cur==parent.start && sub.reserved_end-sub.cur==8);
   assert(parent.start==(available<11?fresh:storage+4));
  }
 }
}
'''
    with tempfile.TemporaryDirectory(prefix='turnip-substream-') as tmp:
        src,exe=Path(tmp)/'fixture.cc',Path(tmp)/'fixture';src.write_text(fixture)
        subprocess.run([cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=undefined',
                        str(src),'-o',str(exe)],check=True)
        subprocess.run([exe],check=True)
    print('PASS: actual aligned substream function, 6 reservation/alignment success and OOM cases')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mesa', type=Path, required=True)
    p.add_argument('--cxx', default='c++')
    a = p.parse_args()
    check(a.mesa, a.cxx)
