#!/usr/bin/env python3
"""Run selected real OSObject factory methods with allocation/init fault injection."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
p=argparse.ArgumentParser(description=__doc__)
for n in ('device','upstream','xnu'):p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--cc',default='clang++')
a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',
           os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
items=[('OSDictionary','withCapacity(unsigned int capacity)','capacity','initWithCapacity(unsigned int capacity)',1,'0'),
       ('OSArray','withCapacity(unsigned int capacity)','capacity','initWithCapacity(unsigned int capacity)',2,'0'),
       ('OSString','withCString(const char *cString, size_t length)','length','initWithStringOfLength(const char *cString, size_t length)',3,'nullptr, 23'),
       ('OSData','withBytes(const void *bytes, unsigned int inLength)','inLength','initWithBytes(const void *bytes, unsigned int inLength)',4,'nullptr, 4096'),
       ('OSNumber','withNumber(unsigned long long value,\n    unsigned int newNumberOfBits)','newNumberOfBits','init(unsigned long long value, unsigned int newNumberOfBits)',5,'123, 64')]
subjects=[f'libkern/c++/{i[0]}.cpp' for i in items]
subjects+=['osfmk/kern/boot_progress.h']
with tempfile.TemporaryDirectory() as tmp:
 w=Path(tmp)
 for n in subjects[:-1]:
  f=w/n;f.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.xnu/n,f)
 original={n:(w/n).read_text() for n in subjects[:-1]}
 for scope in ('arch','os','device'):
  series=roots[scope]/'patches/xnu/series'
  for line in series.read_text().splitlines():
   line=line.strip()
   if not line or line.startswith('#'):continue
   prefix,sep,tail=line.partition(':');patch=roots[prefix]/tail if sep else series.parent/line
   if not any('+++ b/'+n in patch.read_text() for n in subjects):continue
   subprocess.run(['git','apply',*[f'--include={n}' for n in subjects],str(patch)],cwd=w,check=True)
 # Actual patched header compiles in C++ and board-off invocation has no side effects.
 (w/'kern').mkdir();shutil.copyfile(w/subjects[-1],w/'kern/boot_progress.h')
 common=r'''
#include <cassert>
#include <memory>
#include <cstdint>
#include <cstddef>
extern "C" {
#include <kern/boot_progress.h>
}
static int mode,live,calls,inits;
static unsigned got_kind,got_stage;
static uint64_t got_requested;
extern "C" void myron_boot_object_failure(unsigned kind,unsigned stage,uint64_t n,uint64_t caller) {
 ++calls;got_kind=kind;got_stage=stage;got_requested=n;assert(caller);
}
#define __builtin_ptrauth_strip(p,k) (p)
template<class T> using OSSharedPtr=std::shared_ptr<T>;
template<class T> OSSharedPtr<T> OSMakeShared(){return mode==1 ? nullptr : std::make_shared<T>();}
'''
 methods=[];checks=[]
 for cls,sig,arg,init,kind,params in items:
  text=(w/f'libkern/c++/{cls}.cpp').read_text()
  start=text.index(cls+'::'+sig);end=text.index('\n}',start)+2
  method=text[start:end]
  # Strip diagnostic statements to prove the remaining factory is byte-identical.
  import re
  cleaned=re.sub(r'\tif \(!me\) \{\n\t\tmyron_boot_object_failure\([^\n]+\n\t}\n','',method)
  cleaned=re.sub(r'\t\tmyron_boot_object_failure\([^\n]+\n','',cleaned)
  before=original[f'libkern/c++/{cls}.cpp'];old_start=before.index(cls+'::'+sig);old_end=before.index('\n}',old_start)+2
  assert cleaned==before[old_start:old_end],cls+' changed factory behavior'
  unused='(void)cString;' if cls=='OSString' else '(void)bytes;' if cls=='OSData' else '(void)value;' if cls=='OSNumber' else ''
  common+=f'''struct {cls} {{
 {cls}(){{++live;}} ~{cls}(){{--live;}}
 bool {init}{{{unused}(void){arg};++inits;return mode!=2;}}
 static OSSharedPtr<{cls}> {sig};
}};\n'''
  methods.append('OSSharedPtr<'+cls+'>\n'+method)
  requested={1:0,2:0,3:23,4:4096,5:64}[kind]
  checks.append(f'''for(mode=0;mode<3;++mode){{
 calls=inits=0;{{auto value={cls}::{sig.split('(')[0]}({params});
 assert(bool(value)==(mode==0));assert(calls==(mode!=0));assert(inits==(mode!=1));
 if(mode)assert(got_kind=={kind} && got_stage==(unsigned)mode && got_requested=={requested});
 }}assert(!live);
 }}''')
 (w/'test.cpp').write_text(common+'\n'.join(methods)+'\nint main(){'+'\n'.join(checks)+'}\n')
 subprocess.run([a.cc,'-x','c++','-std=c++17','-Wall','-Wextra','-Werror','-DMYRON_EARLY_PROGRESS=1',
  '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(w),str(w/'test.cpp'),'-o',str(w/'test')],check=True)
 subprocess.run([str(w/'test')],check=True,timeout=20,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
 (w/'off.cpp').write_text('#include <cassert>\n#include <stdint.h>\n#include <kern/boot_progress.h>\nint main(){int n=0;myron_boot_object_failure(++n,++n,++n,++n);myron_boot_progress_panic_formatted(++n,++n,++n);assert(n==0);}\n')
 subprocess.run([a.cc,'-x','c++','-std=c++17','-Wall','-Wextra','-Werror','-I',str(w),str(w/'off.cpp'),'-o',str(w/'off')],check=True)
 subprocess.run([str(w/'off')],check=True,timeout=20)
print('PASS selected patch stack; five original factory methods preserve success/allocation/init results and shared ownership; exact failure type/stage/size; board-off hooks do not evaluate arguments')
