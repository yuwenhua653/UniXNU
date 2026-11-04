#!/usr/bin/env python3
"""Reconstruct reviewed source inputs and build the myron iPhone target on macOS."""
import concurrent.futures,hashlib,json,os,subprocess,sys
import argparse
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
mode=parser.add_mutually_exclusive_group()
mode.add_argument('--source-only',action='store_true',help='Reconstruct reviewed sources without fetching tools or compiling the kernel')
mode.add_argument('--desktop',action='store_true',help='Use this job\'s prepared tree for UFS/LTO/fileset integration')
options=parser.parse_args()
here=Path(__file__).resolve().parent;root=Path(os.environ['RUNNER_TEMP'])/'myron-iphone27';root.mkdir(parents=True,exist_ok=True)
if options.desktop:
 work=root/'out/myron/ios-27.0.1-24A446-iphone12-1/myron27'
 subprocess.run([sys.executable,str(root/'device/myron27/prepare_desktop.py'),'--upstream',str(root/'upstream'),
                 '--work',str(work),'--out',str(root/'desktop')],check=True)
 raise SystemExit(0)
snapshot_bytes=(here/'myron27-inputs.json').read_bytes()
snapshot=json.loads(snapshot_bytes)
# This small overlay contains source changes only. Keep the public base
# snapshot unchanged instead of uploading historical verification records.
delta=json.loads((here/'myron27-storage-delta.json').read_text())
if hashlib.sha256(snapshot_bytes).hexdigest()!=delta['base_snapshot_sha256']:
 raise SystemExit('Storage source delta requires the reviewed base snapshot')
allowed={
 'device/myron27/MyronStorageBoot.cpp',
 'device/myron27/MyronStorageRegistration.cpp',
 'device/myron27/audit_ufs_storage_abi.py',
 'device/myron27/build_firmware.py',
 'device/myron27/build_loader.py',
 'device/myron27/build_ufs_dormant.py',
 'device/myron27/fixtures/storage-24A446-iphone12-1.json',
 'device/myron27/loader/Handoff.S',
 'device/myron27/loader/Handoff.h',
 'device/myron27/loader/KernelStream.h',
 'device/myron27/loader/Myron27Loader.dsc',
 'device/myron27/loader/MyronMemory.h',
 'device/myron27/loader/README.md',
 'device/myron27/patches/xnuprelink/zzz-original-storage-adapters.patch',
 'device/myron27/prepare_desktop.py',
 'device/myron27/prepare_loader.py',
 'device/myron27/replay_prelink.py',
 'device/myron27/storage_boot_hook.py',
 'device/myron27/tests/handoff_qemu_start.S',
 'device/myron27/tests/kernel_stream_host.c',
 'device/myron27/tests/loader_boot_host.c',
 'device/myron27/tests/test_handoff_qemu.py',
 'device/myron27/tests/test_kernel_stream.py',
 'device/myron27/tests/test_loader_boot.py',
 'device/myron27/tests/test_storage_boot.py',
 'device/myron27/tests/test_ufs_storage_abi.py',
 'device/myron27/tests/verify_firmware.py',
}
if set(delta['files'])!=allowed:raise SystemExit('Unexpected storage source delta paths')
snapshot['files'].update(delta['files'])
for name,item in snapshot['files'].items():
 relative=Path(name)
 if relative.is_absolute() or '..' in relative.parts:raise SystemExit('Invalid source path')
 data=item['content'].encode()
 if hashlib.sha256(data).hexdigest()!=item['sha256']:raise SystemExit('Source input digest mismatch')
 target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
if options.source_only:
 print('Reconstructed reviewed source inputs:',root/'device',flush=True)
 raise SystemExit(0)
def run(args):subprocess.run(list(map(str,args)),check=True)
def fetch(item):
 path=root/item['path'];path.mkdir(parents=True,exist_ok=True)
 run(['git','init','-q',path]);run(['git','-C',path,'fetch','-q','--depth','1',item['url'],item['commit']]);run(['git','-C',path,'checkout','-q','--detach','FETCH_HEAD'])
 actual=subprocess.check_output(['git','-C',path,'rev-parse','HEAD'],text=True).strip()
 if actual!=item['commit']:raise SystemExit('Wrong source revision')
 return item['path']
# Fetch the parent first, then only the selected components; no unrelated GPU submodules.
fetch(snapshot['upstream'])
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for path in pool.map(fetch,snapshot['sources']):print('Pinned source:',path,flush=True)
d=root/'device/myron27';u=root/'upstream';out=root/'out'
run([sys.executable,d/'install_upstream.py',u])
run([sys.executable,d/'check_compiler.py','--out',root/'reports'])
run([sys.executable,d/'build_native.py','--upstream',u,'--references',root/'references','--xnu',root/'references/xnu','--out',out,'-j','3'])
