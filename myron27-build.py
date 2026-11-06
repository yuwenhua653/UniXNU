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
def root_qualification_identity(fixture):
 return {name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in {
  'source_overlay':here/'myron27-storage-delta.json','build_entry':Path(__file__).resolve(),
  'root_bundle':fixture/'bundle/root-bundle.json',
  'data_seed_contract':fixture/'bundle/data-seed.json'}.items()}
def qualify_root_inputs():
 d=root/'device/myron27';u=root/'upstream';qualification=root/'qualification'
 qualification.mkdir(exist_ok=True)
 (qualification/'host-checks.json').unlink(missing_ok=True)
 subprocess.run(['brew','install','openssl@3'],check=True)
 openssl=Path(subprocess.check_output(['brew','--prefix','openssl@3'],text=True).strip())
 if not (openssl/'include/openssl/evp.h').is_file():
  raise SystemExit('Root qualification requires installed openssl@3 host headers')
 policy=u/'drivers/VirtioMmioBlock/VerifiedBlockPolicy.h';verified=u/'kits/VerifiedRoot'
 fixture=qualification/'root-inputs'
 try:
  checks=[('root-input-tests.log',[sys.executable,str(d/'tests/check_root_bundle.py'),
   '--verified-root',str(verified),'--policy-header',str(policy),'--out',str(fixture),
   '--cc','clang','--cxx','clang++','--openssl-prefix',str(openssl)]),
   ('ram-data-tests.log',[sys.executable,str(d/'tests/test_ram_data.py'),
   '--source',str(u/'drivers/RamBlock'),'-v']),
   ('data-seed-tests.log',[sys.executable,str(d/'tests/test_data_seed.py'),'-v']),
   ('root-runtime-tests.log',[sys.executable,str(d/'tests/test_root_runtime.py'),
   '--xnu-source',str(root/'references/xnu/bsd/kern/bsd_init.c'),'--upstream',str(u),
   '--verified-root',str(verified),'--policy-header',str(policy),
   '--root-bundle',str(fixture/'bundle'),'-v'])]
  for name,command in checks:
   with (qualification/name).open('w') as log:
    status=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT).returncode
   if status:
    print((qualification/name).read_text(),flush=True)
    raise SystemExit('Host qualification failed before native build: '+name)
  (qualification/'host-checks.json').write_text(json.dumps(root_qualification_identity(fixture),indent=2)+'\n')
 finally:
  import shutil
  (root/'reports').mkdir(exist_ok=True)
  for log in qualification.glob('*.log'):shutil.copyfile(log,root/'reports'/log.name)
  if (fixture/'report.json').is_file():shutil.copyfile(fixture/'report.json',root/'reports/root-inputs.json')
  if (qualification/'host-checks.json').is_file():
   shutil.copyfile(qualification/'host-checks.json',root/'reports/host-checks.json')
 print('PASS root host qualification before native build',flush=True)
if options.desktop:
 work=root/'out/myron/ios-27.0.1-24A446-iphone12-1/myron27'
 d=root/'device/myron27';u=root/'upstream';fixture=root/'qualification/root-inputs'
 marker=root/'qualification/host-checks.json'
 if not marker.is_file() or json.loads(marker.read_text())!=root_qualification_identity(fixture):
  raise SystemExit('Require successful host checks for these exact sources before desktop integration')
 subprocess.run([sys.executable,str(d/'prepare_desktop.py'),'--upstream',str(u),
                 '--work',str(work),'--out',str(root/'desktop'),
                 '--root-bundle',str(fixture/'bundle'),'--verified-root',str(u/'kits/VerifiedRoot'),
                 '--policy-header',str(u/'drivers/VirtioMmioBlock/VerifiedBlockPolicy.h')],check=True)
 raise SystemExit(0)
snapshot_bytes=(here/'myron27-inputs.json').read_bytes()
snapshot=json.loads(snapshot_bytes)
# This small overlay contains source changes only. Keep the public base
# snapshot unchanged instead of uploading historical verification records.
delta=json.loads((here/'myron27-storage-delta.json').read_text())
if hashlib.sha256(snapshot_bytes).hexdigest()!=delta['base_snapshot_sha256']:
 raise SystemExit('Storage source delta requires the reviewed base snapshot')
allowed={
 'device/myron27/data_seed.py',
 'device/myron27/tests/test_data_seed.py',
 'device/myron27/records/data-mount-20261106.md',
 'device/myron27/ram_data.py',
 'device/myron27/MyronRamData.h',
 'device/myron27/tests/test_ram_data.py',
 'device/myron27/records/ram-data-20261105.md',
 'device/myron27/root_runtime.py',
 'device/myron27/tests/test_root_runtime.py',
 'device/myron27/records/root-runtime-20261105.md',
 'device/myron27/prepare_root_bundle.py',
 'device/myron27/tests/check_root_bundle.py',
 'device/myron27/tests/MyronPolicyBundle.cpp',
 'device/myron27/records/root-inputs-20261105.md',
 'device/sm8850/drivers/NativeUfs/MyronPolicyCarrier.h',
 'device/sm8850/drivers/NativeUfs/MyronUfsProbe.cpp',
 'device/sm8850/drivers/NativeUfs/MyronRootBoot.h',
 'device/myron27/build_ufs_source.py',
 'device/myron27/prepare_ufs_transport.py',
 'device/myron27/tests/MyronDmaQuarantine.cpp',
 'device/myron27/tests/check_ufs_transport.py',
 'device/myron27/records/ufs-transport-20261105.md',
 'device/myron27/MyronStorageBoot.cpp',
 'device/myron27/MyronStorageRegistration.cpp',
 'device/myron27/audit_ufs_storage_abi.py',
 'device/myron27/board.toml',
 'device/myron27/build_boot_shim.py',
 'device/myron27/build_firmware.py',
 'device/myron27/build_loader.py',
 'device/myron27/build_payload.py',
 'device/myron27/build_ufs_dormant.py',
 'device/myron27/fixtures/storage-24A446-iphone12-1.json',
 'device/myron27/firmware_memory_contract.py',
 'device/myron27/loader/BootShim.S',
 'device/myron27/loader/Handoff.S',
 'device/myron27/loader/Handoff.h',
 'device/myron27/loader/KernelStream.h',
 'device/myron27/loader/Myron27Loader.dsc',
 'device/myron27/loader/MyronMemory.h',
 'device/myron27/loader/README.md',
 'device/myron27/package_entry_probe.py',
 'device/myron27/patches/xnuprelink/zzz-original-storage-adapters.patch',
 'device/myron27/payload_adt.py',
 'device/myron27/prepare_desktop.py',
 'device/myron27/prepare_loader.py',
 'device/myron27/replay_prelink.py',
 'device/myron27/storage_boot_hook.py',
 'device/myron27/tests/replay_kernel_qemu.py',
 'device/myron27/upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1/profile.toml',
 'device/myron27/tests/handoff_qemu_start.S',
 'device/myron27/tests/kernel_stream_host.c',
 'device/myron27/tests/loader_boot_host.c',
 'device/myron27/tests/test_boot_shim.py',
 'device/myron27/tests/test_boot_shim_qemu.py',
 'device/myron27/tests/test_handoff_qemu.py',
 'device/myron27/tests/test_kernel_stream.py',
 'device/myron27/tests/test_loader_boot.py',
 'device/myron27/tests/test_payload_transport.py',
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
root_sources=[
 {'path':'upstream/drivers/RamBlock','url':'https://github.com/UniXNU/RamBlock.git','commit':'4be2d7eb05ef5a98126c91e0302c149140c0e3e1'},
 {'path':'upstream/kits/VerifiedRoot','url':'https://github.com/UniXNU/VerifiedRoot.git','commit':'974f043d0c71ba2e60331483a41c6c6d35274ee3'},
 {'path':'upstream/drivers/VirtioMmioBlock','url':'https://github.com/UniXNU/VirtioMmioBlock.git','commit':'4e1013eb8c45077b57f8d38d61b389fe899ea1c3'},
]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for path in pool.map(fetch,snapshot['sources']+root_sources):print('Pinned source:',path,flush=True)
d=root/'device/myron27';u=root/'upstream';out=root/'out'
run([sys.executable,d/'install_upstream.py',u])
qualify_root_inputs()
run([sys.executable,d/'check_compiler.py','--out',root/'reports'])
run([sys.executable,d/'build_native.py','--upstream',u,'--references',root/'references','--xnu',root/'references/xnu','--out',out,'-j','3'])

