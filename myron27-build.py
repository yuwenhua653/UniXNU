#!/usr/bin/env python3
"""Reconstruct reviewed source inputs and build the myron iPhone target on macOS."""
import concurrent.futures,hashlib,json,os,subprocess,sys
import argparse
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
mode=parser.add_mutually_exclusive_group()
mode.add_argument('--source-only',action='store_true',help='Reconstruct reviewed sources without fetching tools or compiling the kernel')
mode.add_argument('--desktop',action='store_true',help='Use this job\'s prepared tree for UFS/LTO/fileset integration')
mode.add_argument('--userland',action='store_true',help='Qualify original iPhone userland without rebuilding the kernel')
parser.add_argument('--original-root',action='store_true',help='Use this job\'s actual original root/Data for offline desktop integration')
for name in ('device-capture','device-history','owner-private-key','owner-public-key','owner-anchor','owner-policies','reference-boot'):
 parser.add_argument('--'+name,type=Path,help='Private local original-root inputs; never workflow secrets or public artifacts')
options=parser.parse_args()
if options.device_capture is not None and options.device_history is not None:
 parser.error('Select --device-capture or --device-history, never both')
if options.owner_policies is not None and (options.owner_private_key is not None or options.owner_public_key is not None):
 parser.error('Use signed policies or signing keys, never both')
owner_values=[options.device_capture or options.device_history,(options.owner_policies or options.owner_private_key),(options.owner_policies or options.owner_public_key),options.owner_anchor]
if any(v is not None for v in owner_values) != (options.reference_boot is not None):
 parser.error('Device root inputs require --reference-boot; lab mode must not use retained identity')
if any(v is not None for v in owner_values):
 if not (options.desktop and options.original_root and all(v is not None for v in owner_values)):
  parser.error('Device inputs require --desktop --original-root and one capture/history input plus all key/anchor options')
if options.original_root and not options.desktop:parser.error('--original-root requires --desktop')
here=Path(__file__).resolve().parent;root=Path(os.environ['RUNNER_TEMP'])/'myron-iphone27';root.mkdir(parents=True,exist_ok=True)
TOUCH_SOURCES = ('board.patch', 'touch_build.py', 'MyronDigitizer.cpp', 'MyronTouchStart.cpp', 'MyronTouchBoard.h', 'MyronTouchPower.h',
                 'MyronPowerKey.h', 'MyronPowerHardware.h', 'MyronSE19Bus.h', 'MyronFirmwareTouch.h', 'MyronFT3683.c', 'MyronFT3683.h', 'fts_myron_frame.h',
                 'iphone12-1-hid-24A446.json', 'test_touch.c')
def root_qualification_identity(fixture):
 return {'gpu_mode':hashlib.sha256(os.environ.get('MYRON_GPU_NATIVE','0').encode()).hexdigest(),
  **{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in {
  **{'gpu/'+str(p.relative_to(here/'myron-gpu')):p
     for p in (here/'myron-gpu').rglob('*') if p.is_file() and p.suffix in ('.py','.cpp','.c','.h','.json','.patch')},
  'source_overlay':here/'myron27-storage-delta.json','reboot_overlay':here/'myron27-reboot-delta.json',
  'build_entry':Path(__file__).resolve(),'display_overlay':here/'myron27-display-delta.json',
  **{'touch/'+name:here/'myron-touch'/name for name in TOUCH_SOURCES},
  **{'runtime/'+p.name:p for p in (here/'myron-runtime').iterdir() if p.is_file()},
  'ufs_medium_source':here/'myron-ufs-medium.patch',
  'setup_worker_source':here/'myron-setup-worker.patch',
  'setup_data_source':here/'myron-setup-data.patch',
  'skip_setup_source':here/'myron-skip-setup.patch',
  'graphical_source':here/'myron-graphical/device.patch',
  'graphical_firmware':here/'myron-graphical/board.patch',
  'boot_artwork':here/'myron-graphical/MyronBootLogo.h',
  'root_bundle':fixture/'bundle/root-bundle.json',
  'data_seed_contract':fixture/'bundle/data-seed.json',
  'data_volume_proof':fixture.parent/'data-volume/report.json'}.items()}}
def qualify_root_inputs():
 d=root/'device/myron27';u=root/'upstream';qualification=root/'qualification'
 qualification.mkdir(exist_ok=True)
 touch=d/'touch'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(touch/'MyronFT3683.c'),
                 str(touch/'test_touch.c'),'-o',str(qualification/'touch-host-test')],check=True)
 subprocess.run([str(qualification/'touch-host-test')],check=True)
 if os.environ.get('MYRON_GPU_NATIVE') == '1':
  subprocess.run([sys.executable,str(here/'myron-gpu/check_host.py'),'--cc','clang',
   '--firmware',os.environ['MYRON_GPU_FIRMWARE'],'--output',str(qualification/'gpu-portable.json')],check=True)
  subprocess.run([sys.executable,str(d/'gpu/check_native_host.py'),'--references',str(root/'references/myron-gpu'),
   '--cc','clang','--cxx','clang++','--output',str(qualification/'gpu-native-host.json')],check=True)
 (qualification/'host-checks.json').unlink(missing_ok=True)
 subprocess.run(['brew','install','openssl@3','mtools'],check=True)
 openssl=Path(subprocess.check_output(['brew','--prefix','openssl@3'],text=True).strip())
 if not (openssl/'include/openssl/evp.h').is_file():
  raise SystemExit('Root qualification requires installed openssl@3 host headers')
 policy=u/'drivers/VirtioMmioBlock/VerifiedBlockPolicy.h';verified=u/'kits/VerifiedRoot'
 fixture=qualification/'root-inputs'
 try:
  sys.path.insert(0,str(d))
  from prepare_loader import prepare
  prepare(u/'drivers/DarwinBoot',qualification/'loader-source')
  checks=[('keystore-preflight.log',[sys.executable,str(here/'tests/test_myron_keystore.py'),
   '--device',str(d),'--cc','clang++','--sanitize']),
   ('display-lifecycle-preflight.log',[sys.executable,str(here/'tests/test_myron_display_lifecycle.py'),
   '--device',str(d),'--cc','clang++','--sanitize']),
   ('display-header-preflight.log',[sys.executable,str(d/'display/test_display_abi.py'),'--cc','clang','-v']),
   ('systemos-libraries-preflight.log',[sys.executable,str(here/'tests/test_myron_systemos_libraries.py'),
   '--device',str(d)]),
   ('persistent-log-preflight.log',[sys.executable,str(here/'tests/test_myron_persistent_log.py'),'--device',str(d),'--cc','clang++']),
   ('log-worker-preflight.log',[sys.executable,str(here/'tests/test_myron_log_worker.py'),'--device',str(d),'--cc','clang++']),
   ('console-route-preflight.log',[sys.executable,str(here/'tests/test_myron_console_route.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu'),'--cc','clang']),
   ('reboot-evidence-preflight.log',[sys.executable,str(here/'tests/test_myron_reboot_patch.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu'),'--cc','clang']),
   ('amfi-stack-preflight.log',[sys.executable,str(here/'tests/test_myron_amfi_stack.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu'),'--cc','clang']),
   ('user-va-geometry-preflight.log',[sys.executable,str(here/'tests/test_myron_user_va_geometry.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu'),'--cc','clang']),
   ('user-va-native-verifier-preflight.log',[sys.executable,str(here/'tests/test_myron_user_va_native.py'),
   '--device',str(d)]),
   ('native-pac-preflight.log',[sys.executable,str(here/'tests/test_myron_native_pac.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu')]),
   ('user-pac-preflight.log',[sys.executable,str(here/'tests/test_myron_user_pac.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu')]),
   ('user-abort-preflight.log',[sys.executable,str(here/'tests/test_myron_user_abort.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu')]),
   ('user-abort-native-preflight.log',[sys.executable,str(here/'tests/test_myron_fault_native.py'),
   '--device',str(d)]),
   ('object-evidence-preflight.log',[sys.executable,str(here/'tests/test_myron_object_evidence.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu'),'--cc','clang++']),
   ('lockdown-state-preflight.log',[sys.executable,str(here/'tests/test_myron_lockdown_state.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu'),'--cc','clang']),
   ('exit-trace-preflight.log',[sys.executable,str(here/'tests/test_myron_exit_trace.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu'),'--cc','clang']),
   ('exit-reason-preflight.log',[sys.executable,str(here/'tests/test_myron_exit_reason.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu')]),
   ('shared-cache-carrier-preflight.log',[sys.executable,str(d/'tests/test_shared_cache_carrier.py'),
   '--xnu-source',str(root/'references/xnu/bsd/vm/vm_unix.c'),'--upstream',str(u)]),
   ('buffer-patch-preflight.log',[sys.executable,str(here/'tests/test_myron_buffer_patch.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu')]),
   ('stall-patch-preflight.log',[sys.executable,str(here/'tests/test_myron_stall_patch.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu')]),
   ('mount-patch-preflight.log',[sys.executable,str(here/'tests/test_myron_mount_patch.py'),
   '--device',str(d),'--upstream',str(u),'--xnu',str(root/'references/xnu')]),
   ('loader-host-memory.log',[sys.executable,str(d/'tests/test_loader_boot.py'),
   '--edk2',str(root/'references/loader-basecore'),'--upstream',str(u),
   '--staged',str(qualification/'loader-source'),'--out',str(qualification/'loader-host-compile'),
   '--cc','clang','--memory-preflight']),
   ('device-deployment-tests.log',[sys.executable,str(d/'tests/test_device_deployment.py'),'-v']),
   ('owner-request-tests.log',[sys.executable,str(d/'tests/test_owner_request.py'),'-v']),
   ('root-image-tests.log',[sys.executable,str(d/'tests/test_root_image.py'),'-v']),
   ('root-firmware-tests.log',[sys.executable,str(d/'tests/test_root_firmware.py'),'-v']),
   ('boot-reference-tests.log',[sys.executable,str(d/'tests/test_boot_reference.py'),'-v']),
   ('device-layout-tests.log',[sys.executable,str(d/'tests/test_device_layout.py'),'-v']),
   ('original-root-tests.log',[sys.executable,str(d/'tests/test_original_root.py'),
   '--verified-root',str(verified),'--openssl-prefix',str(openssl),'-v']),
   ('boot-assets-tests.log',[sys.executable,str(d/'tests/test_boot_assets.py'),
   '--darwinboot',str(u/'drivers/DarwinBoot'),'-v']),
   ('data-volume-tests.log',[sys.executable,str(d/'tests/test_data_volume.py'),
   '--ram-source',str(u/'drivers/RamBlock'),'-v']),
   ('data-volume-apfs.log',['sudo','-n',sys.executable,str(d/'tests/check_data_volume.py'),
   '--out',str(qualification/'data-volume')]),
   ('root-input-tests.log',[sys.executable,str(d/'tests/check_root_bundle.py'),
   '--verified-root',str(verified),'--policy-header',str(policy),'--out',str(fixture),
   '--cc','clang','--cxx','clang++','--openssl-prefix',str(openssl),
   '--data-volume-report',str(qualification/'data-volume/report.json')]),
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
  if (qualification/'data-volume/report.json').is_file():
   shutil.copyfile(qualification/'data-volume/report.json',root/'reports/data-volume.json')
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
 selected_bundle=fixture/'bundle'
 if options.reference_boot is not None:
  sys.path.insert(0,str(d))
  from boot_reference import recover,require_device_reference
  require_device_reference(options.device_capture is not None or options.device_history is not None,options.reference_boot)
  recover(options.reference_boot)
 if options.original_root:
  apps=json.loads((d/'myron-apps-plan.json').read_text())
  if apps.get('build')!='24A446' or not apps.get('selected') or not 0<apps.get('allocation_bytes',0)<=384*1024*1024:
   raise SystemExit('Require the reviewed bounded original system-app plan before native packaging')
  openssl=Path(subprocess.check_output(['brew','--prefix','openssl@3'],text=True).strip())
  original=root/'qualification/original-root'
  owner_args=[]
  for name in ('device_capture','device_history','owner_private_key','owner_public_key','owner_anchor','owner_policies'):
   value=getattr(options,name)
   if value is not None:owner_args+=['--'+name.replace('_','-'),str(value.resolve())]
  subprocess.run(['sudo','-n',sys.executable,str(d/'qualify_original_root.py'),
                  '--report',str(root/'reports/original-userland.json'),
                  '--root-image',str(root/'private-userland/root-media/root-container.raw'),
                  '--verified-root',str(u/'kits/VerifiedRoot'),'--out',str(original),
                  '--openssl-prefix',str(openssl)]+owner_args,check=True)
  subprocess.run(['sudo','-n','chown','-R',f'{os.getuid()}:{os.getgid()}',str(original)],check=True)
  sys.path.insert(0,str(d))
  from qualify_original_root import check_prepared
  selected_bundle=check_prepared(root/'reports/original-userland.json',original,options.device_capture,options.owner_anchor,options.device_history)
  import shutil
  shutil.copyfile(original/'qualification.json',root/'reports/original-root.json')
 subprocess.run([sys.executable,str(d/'prepare_desktop.py'),'--upstream',str(u),
                 '--work',str(work),'--out',str(root/'desktop'),
                 '--root-bundle',str(selected_bundle),'--verified-root',str(u/'kits/VerifiedRoot'),
                 '--loader-headers',str(root/'references/loader-basecore'),
                 '--firmware-tools',str(root/'qualification/firmware-tools/report.json'),
                 '--policy-header',str(u/'drivers/VirtioMmioBlock/VerifiedBlockPolicy.h')]+
                (['--root-qualification',str(root/'reports/original-root.json')] if options.original_root else [])+
                (['--reference-boot',str(options.reference_boot.resolve())] if options.reference_boot is not None else []),check=True)
 raise SystemExit(0)
snapshot_bytes=(here/'myron27-inputs.json').read_bytes()
snapshot=json.loads(snapshot_bytes)
# This small overlay contains source changes only. Keep the public base
# snapshot unchanged instead of uploading historical verification records.
storage_bytes=(here/'myron27-storage-delta.json').read_bytes()
delta=json.loads(storage_bytes)
reboot=json.loads((here/'myron27-reboot-delta.json').read_text())
if hashlib.sha256(storage_bytes).hexdigest()!=reboot['base_storage_sha256']:
 raise SystemExit('Reboot source delta requires the reviewed storage snapshot')
reboot_paths={'device/myron27/patches/xnu/myron-reboot-evidence.patch', 'device/sm8850/drivers/NativeUfs/MyronBootLog.h', 'device/myron27/boot_assets.py', 'device/myron27/READ-IOS27-LOG.cmd', 'device/sm8850/drivers/NativeUfs/MyronBootLogCore.h', 'device/myron27/package/MyronRebootEvidence.h', 'device/myron27/myron_read_log.py', 'device/myron27/tests/test_boot_assets.py', 'device/myron27/LOG-CAPTURE.md', 'device/myron27/verify_native_artifact.py', 'device/myron27/package/MyronLogSnapshot.h', 'device/sm8850/drivers/NativeUfs/MyronRootBoot.h', 'device/myron27/patches/xnu/myron-console-route.patch', 'device/myron27/patches/xnu/series', 'device/myron27/package/MyronBootProgress.c', 'device/sm8850/drivers/NativeUfs/MyronUfsProbe.cpp', 'device/myron27/scripts/build-myron-progress.py'}
reboot_paths |= {'device/myron27/package/MyronSystemOSLibraries.h', 'device/myron27/root_runtime.py'}
if set(reboot['files'])!=reboot_paths:raise SystemExit('Unexpected reboot source delta paths')
delta['files'].update(reboot['files'])
if hashlib.sha256(snapshot_bytes).hexdigest()!=delta['base_snapshot_sha256']:
 raise SystemExit('Storage source delta requires the reviewed base snapshot')
allowed={
 'device/myron27/patches/xnu/myron-console-route.patch',
 'device/myron27/audit_amfi_stack.py',
 'device/myron27/patches/xnu/myron-amfi-stack-alignment.patch',
 'device/myron27/fixtures/fileset-24A446-iphone12-1-symbols.json',
 'device/myron27/audit_vnode_bindings.py',
 'device/myron27/verify_reviewed_fixture.py',
 'device/myron27/configs/myron27_defconfig',
 'device/myron27/verify_native_artifact.py',
 'device/myron27/scripts/build-myron-progress.py',
 'device/myron27/patches/xnu/series',
 'device/myron27/patches/xnu/myron-early-progress.patch',
 'device/myron27/patches/xnu/myron-root-mount-progress.patch',
 'device/myron27/patches/xnu/myron-stall-evidence.patch',
 'device/myron27/patches/xnu/myron-buffer-ownership.patch',
 'device/myron27/patches/xnu/myron-native-pac-user-abi.patch',
 'device/myron27/patches/xnu/myron-user-pac-va43.patch',
 'device/myron27/patches/xnu/myron-sigabrt-exit-trace.patch',
 'device/myron27/patches/xnu/myron-lockdown-public-state.patch',
 'device/myron27/patches/xnu/myron-panic-object-evidence.patch',
 'device/myron27/package/MyronBootProgress.c',
 'device/myron27/package/MyronRebootEvidence.h',
 'device/myron27/patches/xnu/myron-reboot-evidence.patch',
 'device/myron27/upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1/patches/xnu/boot-progress.patch',
 'device/myron27/package/BootProgressCore.h',
 'device/myron27/package/BootProgressDisplay.h',
 'device/myron27/package/Font.h',
 'device/myron27/device_inputs.py',
 'device/myron27/prepare_root_deployment.py',
 'device/myron27/owner_request.py',
 'device/myron27/tests/test_device_deployment.py',
 'device/myron27/tests/test_owner_request.py',
 'device/myron27/package_root_image.py',
 'device/myron27/tests/test_root_image.py',
 'device/myron27/prepare_firmware_source.py',
 'device/myron27/prepare_firmware_tools.py',
 'device/myron27/build_root_firmware.py',
 'device/myron27/tests/test_root_firmware.py',
 'device/myron27/fixtures/firmware-source.json',
 'device/myron27/tests/check_root_handoff.py',
 'device/myron27/boot_reference.py',
 'device/myron27/tests/test_boot_reference.py',
 'device/myron27/dyld_flow.py',
 'device/myron27/tests/test_dyld_flow.py',
 'device/myron27/qualify_original_root.py',
 'device/myron27/device_layout.py',
 'device/myron27/capture_device_layout.cmd',
 'device/myron27/tests/test_device_layout.py',
 'device/myron27/tests/test_original_root.py',
 'device/myron27/prepare_root_media.py',
 'device/myron27/tests/test_root_media.py',
 'device/myron27/tests/check_root_media.py',
 'device/myron27/userland_audit.py',
 'device/myron27/prepare_userland.py',
 'device/myron27/tests/test_userland_audit.py',
 'device/myron27/records/userland-20261108.md',
 'device/myron27/boot_assets.py',
 'device/myron27/tests/test_boot_assets.py',
 'device/myron27/tests/check_boot_payload.py',
 'device/myron27/records/boot-assets-20261108.md',
 'device/myron27/prepare_data_volume.py',
 'device/myron27/tests/test_data_volume.py',
 'device/myron27/tests/check_data_volume.py',
 'device/myron27/records/data-volume-20261108.md',
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
 'device/myron27/tests/test_shared_cache_carrier.py',
 'device/myron27/tests/test_ufs_storage_abi.py',
 'device/myron27/tests/verify_firmware.py',
}
allowed |= {'device/sm8850/drivers/NativeUfs/MyronBootLog.h', 'device/myron27/LOG-CAPTURE.md', 'device/myron27/package/MyronLogSnapshot.h', 'device/sm8850/drivers/NativeUfs/MyronRootBoot.h', 'device/sm8850/drivers/NativeUfs/MyronUfsProbe.cpp', 'device/myron27/READ-IOS27-LOG.cmd', 'device/sm8850/drivers/NativeUfs/MyronBootLogCore.h', 'device/myron27/myron_read_log.py'}
allowed.add('device/myron27/package/MyronSystemOSLibraries.h')
if set(delta['files'])!=allowed:raise SystemExit('Unexpected storage source delta paths')
snapshot['files'].update(delta['files'])
display=json.loads((here/'myron27-display-delta.json').read_text())
if display['base_reboot_sha256']!=hashlib.sha256((here/'myron27-reboot-delta.json').read_bytes()).hexdigest():
 raise SystemExit('Display delta requires the reviewed mount/reboot snapshot')
display_paths=set(['device/myron27/MyronStorageBoot.cpp', 'device/myron27/audit_ufs_storage_abi.py', 'device/myron27/boot_assets.py', 'device/myron27/build_ufs_dormant.py', 'device/myron27/display/AppleKeyStoreState/LICENSE', 'device/myron27/display/AppleKeyStoreState/NativeKeyStoreEvents.cpp', 'device/myron27/display/AppleKeyStoreState/README.md', 'device/myron27/display/AppleKeyStoreState/source.json', 'device/myron27/display/AppleKeyStoreState/test_closed_boundary.py', 'device/myron27/display/LICENSE', 'device/myron27/display/LegacyDisplaySurface.cpp', 'device/myron27/display/MyronDisplayProbe.cpp', 'device/myron27/display/MyronDisplayTransport.h', 'device/myron27/display/MyronKeyStoreProbe.cpp', 'device/myron27/display/NativeGOPWire.h', 'device/myron27/display/NativeGpuTrace.h', 'device/myron27/display/NativeHalfCodes.h', 'device/myron27/display/NativeLegacyDisplay.cpp', 'device/myron27/display/NativeLegacyRequest.h', 'device/myron27/display/Test/request-state.c', 'device/myron27/display/display_abi.py', 'device/myron27/display/display_build.py', 'device/myron27/display/legacy-display-24A446-iphone12-1.json', 'device/myron27/display/test_display_abi.py', 'device/myron27/display/test_display_transport.py', 'device/myron27/package/BootProcessProbe.c', 'device/myron27/package/BootProcessWorker.c', 'device/myron27/package/BootUiTraceCore.h', 'device/myron27/package/BootUiTraceDetails.h', 'device/myron27/package/BootUiTraceProbe.c', 'device/myron27/package/LICENSE-ProcessTrace.txt', 'device/myron27/package/MyronProcessLog.c', 'device/myron27/package/process-trace-source.json', 'device/myron27/patches/xnuprelink/zzzz-last-constant-padding.patch', 'device/myron27/prepare_desktop.py', 'device/myron27/root_runtime.py', 'device/myron27/scripts/build-myron-progress.py', 'device/myron27/tests/test_root_runtime.py', 'device/myron27/verify_native_artifact.py', 'device/sm8850/drivers/NativeUfs/MyronBootLog.h'])
display_paths.update({'device/myron27/board.toml', 'device/myron27/prepare_data_volume.py',
                      'device/myron27/tests/check_data_volume.py'})
if set(display['files'])!=display_paths:raise SystemExit('Unexpected display source delta paths')
snapshot['files'].update(display['files'])
for name,item in snapshot['files'].items():
 relative=Path(name)
 if relative.is_absolute() or '..' in relative.parts:raise SystemExit('Invalid source path')
 data=item['content'].encode()
 if hashlib.sha256(data).hexdigest()!=item['sha256']:raise SystemExit('Source input digest mismatch')
 target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
graphical=here/'myron-graphical'
subprocess.run(['patch','-s','-p1','-i',str(graphical/'device.patch')],cwd=root,check=True)
subprocess.run(['patch','-s','-p1','-i',str(here/'myron-setup-data.patch')],cwd=root,check=True)
subprocess.run(['patch','-s','-p1','-i',str(here/'myron-ufs-medium.patch')],cwd=root,check=True)
subprocess.run(['patch','-s','-p1','-i',str(here/'myron-setup-worker.patch')],cwd=root,check=True)
subprocess.run(['patch','-s','-p1','-i',str(here/'myron-skip-setup.patch')],cwd=root,check=True)
board=root/'device/myron27'
touch=board/'touch'
touch.mkdir(exist_ok=True)
for name in TOUCH_SOURCES:
 (touch/name).write_bytes((here/'myron-touch'/name).read_bytes())
for line in (touch/'board.patch').read_text().splitlines():
 if line.startswith('--- a/'):
  path=board/line[6:]
  data=path.read_bytes()
  if b'\r\n' in data: path.write_bytes(data.replace(b'\r\n',b'\n'))
subprocess.run(['patch','-s','-p1','-i',str(touch/'board.patch')],cwd=board,check=True)
(board/'graphical-board.patch').write_bytes((graphical/'board.patch').read_bytes())
(board/'package/MyronBootLogo.h').write_bytes((graphical/'MyronBootLogo.h').read_bytes())
gpu=board/'gpu'
gpu.mkdir(exist_ok=True)
for path in (here/'myron-gpu').glob('Myron*'):
 if path.suffix in ('.c','.h'):(gpu/path.name).write_bytes(path.read_bytes())
for path in (here/'myron-gpu/native').iterdir():
 if path.is_file():(gpu/path.name).write_bytes(path.read_bytes())
(gpu/'firmware-3.0.306.json').write_bytes((here/'myron-gpu/firmware-3.0.306.json').read_bytes())
subprocess.run(['patch','-s','-p1','-i',str(gpu/'board.patch')],cwd=board,check=True)
subprocess.run([sys.executable,str(here/'myron-runtime/prepare.py'),str(root)],check=True)
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
if options.userland:
 import shutil
 d=root/'device/myron27';u=root/'upstream'
 # Cheap negative controls run before any multi-gigabyte firmware extraction.
 run([sys.executable,d/'tests/test_userland_audit.py','-v'])
 run([sys.executable,d/'tests/test_dyld_flow.py','-v'])
 run([sys.executable,d/'tests/test_root_media.py','-v'])
 run([sys.executable,d/'tests/test_original_root.py','-v'])
 archive_tool=shutil.which('ipsw')
 if not archive_tool:raise SystemExit('Install blacktop/tap/ipsw first')
 run(['sudo','-n',sys.executable,d/'prepare_userland.py','--upstream',u,'--archive-tool',Path(archive_tool).resolve(),
      '--out',root/'private-userland','--report',root/'reports/original-userland.json',
      '--data-seed',Path(os.environ['MYRON_DATA_SEED']).resolve()])
 raise SystemExit(0)
root_sources=[
 {'path':'references/QcomGeniSpi','url':'https://github.com/UniXNU/QcomGeniSpi.git','commit':'eac47baefe6a5d2368a70351e6ad1b6361bedbe2'},
 {'path':'references/loader-basecore','url':'https://github.com/microsoft/mu_basecore.git','commit':'cfb93724a06ff86ff5ba971413368a7809ee42a5'},
 {'path':'upstream/drivers/RamBlock','url':'https://github.com/UniXNU/RamBlock.git','commit':'4be2d7eb05ef5a98126c91e0302c149140c0e3e1'},
 {'path':'upstream/kits/VerifiedRoot','url':'https://github.com/UniXNU/VerifiedRoot.git','commit':'974f043d0c71ba2e60331483a41c6c6d35274ee3'},
 {'path':'upstream/drivers/VirtioMmioBlock','url':'https://github.com/UniXNU/VirtioMmioBlock.git','commit':'4e1013eb8c45077b57f8d38d61b389fe899ea1c3'},
]
if os.environ.get('MYRON_GPU_NATIVE') == '1':
 sys.path.insert(0,str(board/'gpu'))
 from gpu_build import firmware_inputs
 if not os.environ.get('MYRON_GPU_FIRMWARE'):raise SystemExit('Set MYRON_GPU_FIRMWARE to the verified 3.0.306 directory')
 firmware_inputs(board/'gpu',Path(os.environ['MYRON_GPU_FIRMWARE']))
 for name,pin in json.loads((board/'gpu/dependencies.json').read_text()).items():
  root_sources.append(dict(path='references/myron-gpu/'+name,**pin))
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for path in pool.map(fetch,snapshot['sources']+root_sources):print('Pinned source:',path,flush=True)
d=root/'device/myron27';u=root/'upstream';out=root/'out'
run([sys.executable,d/'install_upstream.py',u])
qualify_root_inputs()
# Compile and unpack the full board before spending time on native XNU.
# No Apple image or device identity is needed for this empty-FAT smoke test.
import shutil
run(['brew','install','qemu'])
run([sys.executable,'-m','pip','install','pyelftools==0.32','unicorn==2.1.4'])
llvm_bin=Path(subprocess.check_output(['brew','--prefix','llvm'],text=True).strip())/'bin'
lld_bin=Path(subprocess.check_output(['brew','--prefix','lld'],text=True).strip())/'bin'
firmware_clang=root/'qualification/firmware-bin';firmware_clang.mkdir(exist_ok=False)
# Homebrew ships LLVM and LLD separately. Give EDK II one complete tool prefix.
for tool in ('clang','clang++','llvm-lib','llvm-objcopy','llvm-rc','ld.lld','lld-link'):
 candidates=[llvm_bin/tool,lld_bin/tool]
 selected=next((p for p in candidates if p.is_file()),None)
 if selected is None:raise SystemExit('Missing firmware tool before native compilation: '+tool)
 (firmware_clang/tool).symlink_to(selected)
firmware_qemu=shutil.which('qemu-system-aarch64')
if not firmware_qemu:raise SystemExit('Missing firmware QEMU tool before native compilation')
firmware_log=root/'reports/firmware-preflight.log'
with firmware_log.open('w') as log:
 status=subprocess.run([sys.executable,str(d/'prepare_firmware_tools.py'),'--upstream',str(u),
  '--clang-bin',str(firmware_clang),'--qemu',firmware_qemu,
  '--out',str(root/'qualification/firmware-tools')],stdout=log,stderr=subprocess.STDOUT).returncode
if status:
 lines=firmware_log.read_text(errors='replace').splitlines()
 first_error=next((i for i,line in enumerate(lines) if 'error:' in line or '***' in line),None)
 if first_error is not None:
  print('First firmware preflight error:',flush=True)
  print('\n'.join(lines[max(0,first_error-5):first_error+16]),flush=True)
 print('\n'.join(lines[-120:]),flush=True)
 raise SystemExit('Full firmware preflight failed before native XNU compilation')
shutil.copyfile(root/'qualification/firmware-tools/report.json',root/'reports/firmware-preflight.json')
print('PASS full firmware compile/unpack and PAC preflight before native build',flush=True)
run([sys.executable,d/'check_compiler.py','--out',root/'reports'])
run([sys.executable,d/'build_native.py','--upstream',u,'--references',root/'references','--xnu',root/'references/xnu','--out',out,'-j','3'])


