#!/usr/bin/env python3
"""Build a pinned masked-WFE compatibility derivative without recompiling XNU."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib
import zlib

p=argparse.ArgumentParser(description=__doc__)
for n in ('base','work','output','clang-bin','qemu'):p.add_argument('--'+n,type=Path,required=True)
p.add_argument("--source-repo", type=Path, help="Exact pinned source checkout for a previously qualified native artifact")
p.add_argument("--producer-run", help="Original artifact-producing run; requires --source-repo")
a=p.parse_args()
if bool(a.source_repo) != bool(a.producer_run): p.error("Recovery requires both source checkout and producer run")
for k,v in vars(a).items():
    if isinstance(v,Path):setattr(a,k,v.resolve())
repo=a.source_repo or Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('boot_only',repo/'myron27-boot-only.py')
bp=importlib.util.module_from_spec(spec);spec.loader.exec_module(bp)
need,sha,save=bp.need,bp.sha,bp.save
need(not a.work.exists() and not a.output.exists(),'Use fresh work/output directories')
a.work.mkdir(parents=True);start=time.monotonic()
producer=bp.read_json(a.base/'producer.json')
commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
need(producer['source_commit']==commit,'Payload must come from this exact checked-out source commit')
if a.source_repo is None: need(commit==os.environ['GITHUB_SHA'],'Source differs from workflow commit')
need(producer['run_id']==(a.producer_run or os.environ['GITHUB_RUN_ID']),'Payload producer run differs')
need(producer['source_delta_sha256']==sha((repo/'myron27-storage-delta.json').read_bytes()),'Native source snapshot differs')
mraw=(a.base/'deployment.json').read_bytes();raw=(a.base/'root-startup.img').read_bytes()
need(sha(mraw)==producer['manifest_sha256'] and sha(raw)==producer['boot_sha256'],'Native artifact transport differs')
m=json.loads(mraw)
need('entry_observer' not in m,'Terminal entry probe must not be used as continuous input')
for n,size,digest in (
 ('root-container.raw',15092154368,'7d3b1200d14e4f27f12ef1680184033b0f95035475635f57c5b4130c28cdb81c'),
 ('policy-carrier.bin',117911552,'4e733b6230b29d409860a0d2cd8d05d23a60ab9b54ab6cb1662c777a4205da16')):
    need(m['files'][n]==dict(bytes=size,sha256=digest),'Installed root/policy identity changed')
r=m['image_reports']['root-startup.img']
need(len(raw)==bp.BOOT_BYTES and m['files']['root-startup.img']==dict(bytes=len(raw),sha256=sha(raw)),'Native image mismatch')
need(r['fat_offset']==bp.FAT_OFFSET and sha(raw[4096:bp.FD_OFFSET])==r['shim_sha256'],'Native image layout/shim differs')
need(sha(raw[bp.FD_OFFSET:bp.FAT_OFFSET])==r['fd_sha256'] and sha(raw[bp.FAT_OFFSET:])==r['payload_sha256'],'Native FD/FAT mismatch')
env=dict(os.environ,CLANG_BIN=str(a.clang_bin)+'/',PATH=str(a.clang_bin)+os.pathsep+os.environ['PATH'])
subprocess.run([sys.executable,str(repo/'myron27-build.py'),'--source-only'],env=env,check=True)
device=Path(os.environ['RUNNER_TEMP'])/'myron-iphone27/device/myron27';sys.path.insert(0,str(device))
from prepare_firmware_source import prepare
from prepare_loader import prepare as loader
from myron_continuous_contract import kernel_definitions
up=a.work/'upstream'
bp.checkout('https://github.com/UniXNU/UniXNU.git','04573c510c5fd4892ca6948739389141cc9e05f5',up)
bp.checkout('https://github.com/UniXNU/DarwinBoot.git','3c75734014cdab0acd9541e88057b7606ee7ae08',up/'drivers/DarwinBoot')
payload=a.work/'payload';payload.mkdir();fat=raw[bp.FAT_OFFSET:];(payload/'payload.img').write_bytes(fat)
def read(name):return subprocess.check_output(['mtype','-i',str(payload/'payload.img'),'::/EFI/UniXNU/'+name])
hashes=r['embedded_files']
need(set(hashes)=={'EFI/UniXNU/Payloads/'+n for n in ('kernel.macho','kernel.macho.adt','kernel.macho.trustcache','scratch-data.img')},'Unexpected payload inventory')
for name,digest in hashes.items():need(sha(read(name[len('EFI/UniXNU/'):]))==digest,'Embedded file mismatch '+name)
kernel=read('Payloads/kernel.macho');definitions=kernel_definitions(kernel)
required={'_boot_progress_init','_boot_progress_stage','_boot_progress_bind','_boot_progress_putc','_myron_boot_progress_state'}
need(required<=definitions.keys(),'Continuous recorder missing from final prelinked kernel')
need(b'MYRON iOS27 - CONTINUOUS XNU BOOT' in kernel,'Wrong final recorder implementation')
menu=tomllib.loads(read('unixnu.toml').decode());entries=[e for e in menu['entry'] if e['id']==menu['boot']['default']]
need(len(entries)==1 and menu['boot']['timeout']==-1 and menu['boot']['rotate']==0,'Manual menu policy changed')
e=entries[0]
need(e['type']=='xnu' and e['path']=='Payloads/kernel.macho' and e['initrd']=='Payloads/scratch-data.img','Unexpected boot entry')
need({'boot-progress=2','myron27-dyld-startup=1','cpus=1'}<=set(e['args'].split()),'Continuous startup arguments missing')
# Validate original bytes first; preserve native provenance separately from this derivative.
from myron27_idle_compat import patch_kernel, OFFSET
from pyfatfs.PyFatFS import PyFatFS
with PyFatFS(str(payload/'payload.img'), read_only=True) as fs:
    before_files = {name: sha(fs.readbytes(name)) for name in fs.walk.files()}
new_kernel, adjustment = patch_kernel(kernel)
with PyFatFS(str(payload/'payload.img')) as fs:
    with fs.openbin('EFI/UniXNU/Payloads/kernel.macho', 'r+') as file:
        file.seek(OFFSET)
        need(file.write(b'\0\0\0\0') == 4, 'Incomplete scalar write')
with PyFatFS(str(payload/'payload.img'), read_only=True) as fs:
    after_files = {name: sha(fs.readbytes(name)) for name in fs.walk.files()}
expected_files = dict(before_files)
expected_files['/EFI/UniXNU/Payloads/kernel.macho'] = sha(new_kernel)
need(after_files == expected_files, 'Other FAT files changed')
need(read('Payloads/kernel.macho') == new_kernel, 'mtools kernel readback differs')
fat = (payload/'payload.img').read_bytes()
need(len(fat) == len(raw[bp.FAT_OFFSET:]), 'FAT size changed')
hashes = dict(hashes)
hashes['EFI/UniXNU/Payloads/kernel.macho'] = sha(new_kernel)
kernel = new_kernel
save(a.work/'idle-compatibility.json', adjustment)
h=lambda n:hashes['EFI/UniXNU/Payloads/'+n]
header=(f'#define MYRON_KERNEL_FAT_BYTES 0x{len(fat):x}ULL\n#define MYRON_KERNEL_FAT_CRC32 0x{zlib.crc32(fat):08x}U\n'
        f'#define MYRON_KERNEL_FAT_SHA256 "{sha(fat)}"\n#define MYRON_R46_KERNEL_SHA256 "{h("kernel.macho")}"\n')
(payload/'KernelPayloadExpected.h').write_text(header)
proof=dict(result='passed',bytes=len(fat),sha256=sha(fat),crc32=f'{zlib.crc32(fat):08x}',transport_header_sha256=sha(header.encode()),
    kernel_sha256=h('kernel.macho'),adt_sha256=h('kernel.macho.adt'),kernel_args=e['args'],root_volume_enabled=True,
    boot_assets=dict(initrd=e['initrd'],data_sha256=h('scratch-data.img'),trust_bundle_sha256=h('kernel.macho.trustcache'),dyld_startup_probe_enabled=True),
    producer=producer,compatibility_adjustment=adjustment,phone_tested=False)
save(payload/'payload.json',proof)
prepare(a.work/'mu')
subprocess.run(['make','-C',str(a.work/'mu/Mu_Basecore/BaseTools/Source/C'),'-j4','CLANG=1','CC=clang','CXX=clang++'],env=env,check=True)
loader(up/'drivers/DarwinBoot',a.work/'loader-source')
def run(script,*args):subprocess.run([sys.executable,str(device/script),*map(str,args)],env=env,check=True)
run('tests/test_handoff_qemu.py','--clang',a.clang_bin/'clang','--qemu',a.qemu,'--edk2',a.work/'mu/Mu_Basecore','--out',a.work/'capsule-test')
run('tests/check_root_handoff.py','--edk2',a.work/'mu/Mu_Basecore','--upstream',up,'--staged',a.work/'loader-source','--payload',payload,'--out',a.work/'root-handoff','--cc',a.clang_bin/'clang')
run('build_firmware.py','--mu',a.work/'mu','--upstream',up,'--staged',a.work/'loader-source','--clang-bin',a.clang_bin,'--payload',payload,'--out',a.work/'firmware')
run('tests/verify_firmware.py','--build',a.work/'firmware','--mu',a.work/'mu','--staged',a.work/'loader-source','--qemu-test',a.work/'capsule-test','--out',a.work/'firmware/firmware-verification.json')
fv=bp.read_json(a.work/'firmware/firmware-verification.json');fw=bp.read_json(a.work/'firmware/firmware-build.json');host=bp.read_json(a.work/'root-handoff/report.json')
need(fv['result']==fw['result']==host['result']=='passed','Incomplete qualification')
need(fv['full_fd_unpacked'] and fv['actual_compile_commands_checked']>=400 and fv['efi_capsule_matches_qemu_executed_bytes'],'Incomplete FD verification')
need(fw['payload']==proof and host['kernel_sha256']==h('kernel.macho') and host['fat_sha256']==sha(fat),'Build/qualification payload mismatch')
need(host['root_sidecars_checked'] and host['root_sidecar_failure_cases']==12 and host['byte_equality_at_handoff'],'Incomplete root handoff test')
need(fw['source_stage']['driver_staged_sha256']==host['driver_sha256'] and fw['source_stage']['stream_source_sha256']==host['stream_source_sha256'],'Loader source mismatch')
for name,digest in bp.PUBLISHERS.items():need(fw['board_source_hashes'][name]==digest,'Memory publisher changed')
fd=(a.work/'firmware/Build/myronPkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd').read_bytes()
need(len(fd)==bp.FD_BYTES and sha(fd)==fv['fd_sha256']==fw['fd_sha256'],'Firmware mismatch')
image=raw[:bp.FD_OFFSET]+fd+fat
need(len(image)==len(raw) and image[:bp.FD_OFFSET]==raw[:bp.FD_OFFSET] and image[bp.FAT_OFFSET:]==fat,'Image layout or shim changed')
a.output.mkdir();(a.output/'root-startup.img').write_bytes(image)
report=dict(result='passed',kind='continuous-xnu-source-boot',producer=producer,assembly_commit=os.environ['GITHUB_SHA'],assembly_run=os.environ['GITHUB_RUN_ID'],intentional_stop=False,
    compatibility_adjustment=adjustment,required_symbols=sorted(required),kernel_sha256=h('kernel.macho'),firmware_verification=fv,root_handoff=host,
    boot_sha256=sha(image),elapsed_seconds=round(time.monotonic()-start,1),root_install_reusable=True,phone_tested=False,desktop_reached=False)
save(a.output/'continuous-report.json',report)
m=copy.deepcopy(m);m['files']['root-startup.img']=dict(bytes=len(image),sha256=sha(image))
r=m['image_reports']['root-startup.img'];r.update(sha256=sha(image),fd_sha256=sha(fd),firmware_report_sha256=sha((a.output/'continuous-report.json').read_bytes()),firmware_report_scope='continuous-xnu-idle-compatibility',payload_sha256=sha(fat),embedded_files=hashes)
m['continuous_boot']=dict(intentional_stop=False,kernel_sha256=h('kernel.macho'),source_commit=commit,compatibility_adjustment=adjustment)
save(a.output/'deployment.json',m)
print('PASS: pinned native kernel with scoped idle compatibility derivative; phone/desktop execution remains unverified')

