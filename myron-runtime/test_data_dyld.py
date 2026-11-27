#!/usr/bin/env python3
"""Exercise the generated post-mount dyld gate at both Data capacities.

Reuse the complete existing mount/UUID/hash/cache fixture, not a replacement
of the gate. The baseline control reinstates only the former size condition.
"""
import argparse
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile

p=argparse.ArgumentParser()
p.add_argument('--device',type=Path,required=True)
p.add_argument('--cc',default='cc')
a=p.parse_args();d=a.device.resolve()
sys.path.insert(0,str(d))
from root_runtime import startup_source

def once(text,old,new):
    assert text.count(old)==1,old
    return text.replace(old,new)

tree=ast.parse((d/'tests/test_root_runtime.py').read_text())
method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and
            n.name=='test_dyld_startup_production_gate_and_failures')
fixture=next(n.value for n in ast.walk(method) if isinstance(n,ast.Constant) and
             isinstance(n.value,str) and '/* PRODUCTION_GATE */' in n.value and '#include' in n.value)
fixture=once(fixture,'#define MYRON_DATA_SEED_BYTES 16384',
             '#define MYRON_DATA_SEED_BYTES UINT64_C(1073741824)')
fixture=once(fixture,'int fault,lookups,refs,seed_calls,updates,auth_calls,arg_mode=1,arg_present=1;',
             '''int fault,lookups,refs,seed_calls,updates,auth_calls,arg_mode=1,arg_present=1;
uint64_t selected_capacity;
int growth_authorized=1;''')
fixture=once(fixture,'int myron_data_capacity_valid(uint64_t bytes){(void)bytes;return 0;}',
             '''int myron_data_capacity_valid(uint64_t bytes){
 return growth_authorized && bytes==(UINT64_C(16)<<30);
}''')
fixture=once(fixture,'*bytes=fault==26?8192:16384;',
             '*bytes=fault==26?8192:selected_capacity;')
begin=fixture.index('int main(void){')
fixture=fixture[:begin]+r'''
int main(void){
 const uint64_t capacities[]={UINT64_C(1)<<30,UINT64_C(16)<<30};
 for(unsigned c=0;c<2;++c){
  selected_capacity=capacities[c];growth_authorized=1;
  for(int f=0;f<=141;++f){
   if(f==28||f==29)continue;
   reset(f);uint64_t initial=dyld_flags;
   int ok=f==0 && (c==0 || EXPECT_GROWN);
   int rc=myron_dyld_startup_prepare();
   assert((rc==0)==ok && refs==0);
   assert(myron_dyld_startup_status==rc && myron_dyld_startup_state==(ok?2U:3U));
   assert(updates==ok && dyld_flags==(ok?40:initial) && commpage==dyld_flags);
   assert(myron_dyld_startup_flags==(ok?40:0));
   if(!EXPECT_GROWN && c==1 && f==0)assert(rc==EAUTH && !lookups && !updates);
   assert(myron_dyld_startup_prepare()==EALREADY && updates==ok);
  }
 }
 // Even the correct grown size needs live committed-store authorization.
 reset(0);selected_capacity=UINT64_C(16)<<30;growth_authorized=0;
 assert(myron_dyld_startup_prepare()==EAUTH && !updates && !lookups && !refs);
 growth_authorized=1;
 const uint64_t refused[]={0,UINT64_C(4)<<30,UINT64_C(32)<<30,(UINT64_C(16)<<30)-4096};
 for(unsigned i=0;i<sizeof(refused)/sizeof(refused[0]);++i){
  reset(0);selected_capacity=refused[i];
  assert(myron_dyld_startup_prepare()==EAUTH && !updates && !lookups && !refs);
 }
 reset(0);arg_present=0;assert(!myron_dyld_startup_prepare());
 assert(!seed_calls&&!lookups&&!updates&&!myron_dyld_startup_state&&dyld_flags==32);
 reset(0);arg_mode=0;assert(!myron_dyld_startup_prepare());
 assert(!seed_calls&&!lookups&&!updates&&!myron_dyld_startup_state&&dyld_flags==32);
}
'''
block=startup_source()
expanded='''(bytes != MYRON_DATA_SEED_BYTES && !(MYRON_DATA_SEED_BYTES == UINT64_C(1073741824) &&
          myron_data_capacity_valid(bytes)))'''
assert expanded in block
baseline=once(block,expanded,'bytes != MYRON_DATA_SEED_BYTES')
with tempfile.TemporaryDirectory(prefix='myron-data-dyld-') as tmp:
    for name,body,expected in [('old-size-gate',baseline,0),('committed-capacity',block,1)]:
        src=Path(tmp)/(name+'.c');out=Path(tmp)/name
        src.write_text(fixture.replace('/* PRODUCTION_GATE */',body))
        subprocess.run([a.cc,'-x','c','-std=c11','-Wall','-Wextra','-Werror',
            '-Wno-misleading-indentation','-fsanitize=address,undefined',
            '-fno-omit-frame-pointer',f'-DEXPECT_GROWN={expected}',str(src),'-o',str(out)],check=True)
        result=subprocess.run([str(out)],capture_output=True,text=True,env=dict(os.environ,
            ASAN_OPTIONS='detect_leaks=0:abort_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
        if result.returncode:raise RuntimeError(name+' failed:\n'+result.stdout+result.stderr)
print('PASS: baseline reproduces 16 GiB EAUTH before dyld; fixed gate accepts authorized 1/16 GiB')
print('PASS: 280 full startup scenarios plus unauthorized/malformed capacities; UUID/hash/root/cache checks retained')
