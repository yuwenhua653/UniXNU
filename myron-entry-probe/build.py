#!/usr/bin/env python3
"""Qualify a pinned retained-kernel observer, then rebuild only its firmware."""
import argparse,copy,hashlib,importlib.util,json,os,subprocess,sys,time,zlib
from pathlib import Path
import probe
p=argparse.ArgumentParser(description=__doc__)
for n in ('baseline-source','base','work','output','clang-bin','qemu'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args()
for k,v in vars(a).items():setattr(a,k,v.resolve())
repo=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('boot_only',repo/'myron27-boot-only.py');bp=importlib.util.module_from_spec(spec);spec.loader.exec_module(bp)
review=bp.check_sources(repo,a.baseline_source);raw,manifest=bp.read_base(a.base)
probe.need(not a.work.exists() and not a.output.exists(),'Use fresh outputs');a.work.mkdir(parents=True)
start=time.monotonic();env=dict(os.environ,CLANG_BIN=str(a.clang_bin)+'/',PATH=str(a.clang_bin)+os.pathsep+os.environ['PATH'])
subprocess.run([sys.executable,str(repo/'myron27-build.py'),'--source-only'],env=env,check=True)
device=Path(os.environ['RUNNER_TEMP'])/'myron-iphone27/device/myron27';sys.path.insert(0,str(device))
from prepare_firmware_source import prepare
from prepare_loader import prepare as loader
up=a.work/'upstream'
bp.checkout('https://github.com/UniXNU/UniXNU.git','04573c510c5fd4892ca6948739389141cc9e05f5',up)
bp.checkout('https://github.com/UniXNU/DarwinBoot.git','3c75734014cdab0acd9541e88057b7606ee7ae08',up/'drivers/DarwinBoot')
# Extract the pinned payload, instrument only its exact kernel copy.
payload=a.work/'payload';proof=bp.payload(a.base,payload)
fat=payload/'payload.img'
original=subprocess.check_output(['mtype','-i',str(fat),'::/EFI/UniXNU/Payloads/kernel.macho'])
(a.work/'original.macho').write_bytes(original)
pr=probe.build(a.work/'original.macho',a.work/'probe',a.clang_bin/'clang')
subprocess.run([sys.executable,str(Path(__file__).with_name('test_observer.py')),'--probe',str(a.work/'probe'),'-v'],check=True,env=env)
subprocess.run([sys.executable,str(Path(__file__).with_name('test_qemu.py')),'--probe',str(a.work/'probe'),'--out',str(a.work/'prefix-test'),'--clang',str(a.clang_bin/'clang'),'--qemu',str(a.qemu)],check=True,env=env)
subprocess.run(['mcopy','-o','-i',str(fat),str(a.work/'probe/kernel.macho'),'::/EFI/UniXNU/Payloads/kernel.macho'],check=True)
expected=manifest['image_reports']['root-startup.img']['embedded_files']
for name,digest in expected.items():
    data=subprocess.check_output(['mtype','-i',str(fat),'::/'+name])
    probe.need(probe.sha(data)==(pr['output_sha256'] if name.endswith('/kernel.macho') else digest),'Unexpected payload change '+name)
old_menu=subprocess.check_output(['mtype','-i',str(fat),'::/EFI/UniXNU/unixnu.toml'])
# Same size and boot entry; the external guide explicitly identifies the C-entry stop.
newfat=fat.read_bytes();proof.update(kernel_sha256=pr['output_sha256'],sha256=probe.sha(newfat),crc32=f'{zlib.crc32(newfat):08x}')
header=(f'#define MYRON_KERNEL_FAT_BYTES 0x{len(newfat):x}ULL\n#define MYRON_KERNEL_FAT_CRC32 0x{zlib.crc32(newfat):08x}U\n#define MYRON_KERNEL_FAT_SHA256 "{probe.sha(newfat)}"\n#define MYRON_R46_KERNEL_SHA256 "{pr["output_sha256"]}"\n')
(payload/'KernelPayloadExpected.h').write_text(header);proof['transport_header_sha256']=probe.sha(header.encode());bp.save(payload/'payload.json',proof)
prepare(a.work/'mu')
subprocess.run(['make','-C',str(a.work/'mu/Mu_Basecore/BaseTools/Source/C'),'-j4','CLANG=1','CC=clang','CXX=clang++'],env=env,check=True)
loader(up/'drivers/DarwinBoot',a.work/'loader-source')
def run(script,*args):subprocess.run([sys.executable,str(device/script),*map(str,args)],env=env,check=True)
run('tests/test_handoff_qemu.py','--clang',a.clang_bin/'clang','--qemu',a.qemu,'--edk2',a.work/'mu/Mu_Basecore','--out',a.work/'capsule-test')
run('tests/check_root_handoff.py','--edk2',a.work/'mu/Mu_Basecore','--upstream',up,'--staged',a.work/'loader-source','--payload',payload,'--out',a.work/'root-handoff','--cc',a.clang_bin/'clang')
run('build_firmware.py','--mu',a.work/'mu','--upstream',up,'--staged',a.work/'loader-source','--clang-bin',a.clang_bin,'--payload',payload,'--out',a.work/'firmware')
run('tests/verify_firmware.py','--build',a.work/'firmware','--mu',a.work/'mu','--staged',a.work/'loader-source','--qemu-test',a.work/'capsule-test','--out',a.work/'firmware/firmware-verification.json')
fv=bp.read_json(a.work/'firmware/firmware-verification.json');fw=bp.read_json(a.work/'firmware/firmware-build.json');host=bp.read_json(a.work/'root-handoff/report.json')
probe.need(fv['result']==fw['result']==host['result']=='passed','Incomplete qualification')
probe.need(fv['full_fd_unpacked'] and fv['actual_compile_commands_checked']>=400 and fv['efi_capsule_matches_qemu_executed_bytes'],'Incomplete FD verification')
probe.need(fw['payload']==proof and host['kernel_sha256']==pr['output_sha256'] and host['fat_sha256']==proof['sha256'],'Build/qualification payload mismatch')
probe.need(host['root_sidecars_checked'] and host['root_sidecar_failure_cases']==12 and host['byte_equality_at_handoff'],'Incomplete root handoff test')
probe.need(fw['source_stage']['driver_staged_sha256']==host['driver_sha256'] and fw['source_stage']['stream_source_sha256']==host['stream_source_sha256'],'Loader source mismatch')
for name,digest in bp.PUBLISHERS.items():probe.need(fw['board_source_hashes'][name]==digest,'Memory publisher changed')
fd=(a.work/'firmware/Build/myronPkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd').read_bytes()
probe.need(len(fd)==bp.FD_BYTES and probe.sha(fd)==fv['fd_sha256']==fw['fd_sha256'],'Firmware mismatch')
image=raw[:bp.FD_OFFSET]+fd+newfat
probe.need(len(image)==len(raw) and image[:bp.FD_OFFSET]==raw[:bp.FD_OFFSET],'Header/shim changed')
a.output.mkdir();(a.output/'root-startup.img').write_bytes(image)
report=dict(result='passed',kind='terminal-xnu-entry-observer',baseline_run=bp.BASE_RUN,source_check=review,
    probe=pr,firmware_verification=fv,root_handoff=host,boot_sha256=probe.sha(image),elapsed_seconds=round(time.monotonic()-start,1),
    kernel_recompiled=False,root_media_rebuilt=False,phone_tested=False,desktop_reached=False)
bp.save(a.output/'entry-report.json',report)
m=copy.deepcopy(manifest);m['files']['root-startup.img']=dict(bytes=len(image),sha256=probe.sha(image))
r=m['image_reports']['root-startup.img'];r.update(sha256=probe.sha(image),fd_sha256=probe.sha(fd),payload_sha256=proof['sha256'],firmware_report_sha256=probe.sha((a.output/'entry-report.json').read_bytes()),firmware_report_scope='terminal-xnu-entry-observer')
r['embedded_files']['EFI/UniXNU/Payloads/kernel.macho']=pr['output_sha256']
m['entry_observer']=dict(terminal_stop=True,source_kernel_sha256=probe.SHA,kernel_sha256=pr['output_sha256'],phase_meanings=pr['phase_meanings'])
bp.save(a.output/'deployment.json',m)
print('PASS: qualified entry observer and firmware; terminal 2716 is not a desktop boot.')
