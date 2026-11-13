#!/usr/bin/env python3
"""Compile/execute the actual pinned BDS implementation with host UEFI stubs."""
import argparse, hashlib, json, pathlib, re, subprocess, tempfile
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--device',type=pathlib.Path,required=True)
p.add_argument('--cc',default='cc')
a=p.parse_args()
import sys
sys.path.insert(0,str(a.device.resolve()))
from prepare_firmware_source import snapshot
files=snapshot()['files']
name='Platforms/Xiaomi/myronPkg/Library/MyronBootManagerLib/MyronBootManagerLib.c'
source=files[name]['content']
with tempfile.TemporaryDirectory() as temp:
 out=pathlib.Path(temp)
 # The host harness supplies ABI-compatible declarations for only the used calls.
 source=re.sub(r'^#include[^\n]*\n','',source,flags=re.M)
 (out/'bds-under-test.c').write_text(source)
 # Verify the builder accepts the new BDS without dropping the reviewed
 # memory publishers; reject any unrelated BDS source modification.
 from firmware_memory_contract import reviewed_sources, check_source
 board=out/'board'
 for path,row in files.items():
  prefix='Platforms/Xiaomi/myronPkg/'
  if path.startswith(prefix):
   dest=board/path[len(prefix):];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(row['content'])
 prepared=reviewed_sources(board)
 for path,raw in prepared.items():(board/path).write_bytes(raw)
 check_source(board)
 target=board/'Library/MyronBootManagerLib/MyronBootManagerLib.c'
 target.write_text(target.read_text()+'\n// unexpected change\n')
 try:reviewed_sources(board)
 except ValueError:pass
 else:raise AssertionError('Unreviewed BDS source accepted')
 exe=out/'bds-test' 
 subprocess.run([a.cc,'-std=c11','-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                 '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(out),
                 str(pathlib.Path(__file__).with_name('myron_bds_host.c')),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
 print('Snapshot BDS source SHA256:',files[name]['sha256'])
