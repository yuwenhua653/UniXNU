#!/usr/bin/env python3
"""Apply selected upstream/OS/board patches and preserve original panic/IRQ logic."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
p=argparse.ArgumentParser()
p.add_argument('--device',type=Path,required=True)
p.add_argument('--upstream',type=Path,required=True)
p.add_argument('--xnu',type=Path,required=True)
a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',
           os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subjects=('osfmk/kern/debug.c','osfmk/arm64/sleh.c','osfmk/kern/boot_progress.h')
with tempfile.TemporaryDirectory() as tmp:
 work=Path(tmp)
 for name in subjects[:2]:
  dst=work/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.xnu/name,dst)
 before=None
 for scope in ('arch','os','device'):
  series=roots[scope]/'patches/xnu/series'
  for line in series.read_text().splitlines():
   line=line.strip()
   if not line or line.startswith('#'):continue
   prefix,sep,tail=line.partition(':')
   patch=(roots[prefix]/tail if sep else series.parent/line).resolve()
   text=patch.read_text()
   if not any('--- a/'+n in text or '+++ b/'+n in text for n in subjects):continue
   if patch.name=='myron-stall-evidence.patch':before={n:(work/n).read_text() for n in subjects[:2]}
   subprocess.run(['git','apply',*[f'--include={n}' for n in subjects],str(patch)],cwd=work,check=True)
 assert before
 debug=(work/subjects[0]).read_text()
 call='\tmyron_boot_progress_panic(panic_format_str, (uint64_t)panic_caller);\n'
 assert debug.count(call)==1
 assert debug.index(call)<debug.index('if (PE_kputc == NULL)',debug.index(call))<debug.index('ml_panic_trap_to_debugger(panic_format_str',debug.index(call))
 assert debug.removeprefix('#include <kern/boot_progress.h>\n').replace(call,'')==before[subjects[0]]
 sleh=(work/subjects[1]).read_text()
 call='\tif (ss_valid) {\n\t\tmyron_boot_progress_fault(msg, get_saved_state_pc(ss), state->lr, state->esr, state->far);\n\t}\n'
 assert sleh.count(call)==1 and sleh.count('myron_boot_progress_irq_return();')==1
 assert sleh.replace(call,'').replace('\tmyron_boot_progress_irq_return();\n','')==before[subjects[1]]
 header=(work/subjects[2]).read_text()
 for name in ('panic','fault','irq_return'):
  assert 'void myron_boot_progress_'+name+'(' in header
  assert '#define myron_boot_progress_'+name+'(...) ((void)0)' in header
print('PASS selected patch stack; early panic precedes platform handlers; original panic/IRQ code unchanged; board-off hooks are no-ops')
