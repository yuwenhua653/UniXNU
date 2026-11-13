#!/usr/bin/env python3
"""Rebuild only reviewed board firmware around a pinned, unchanged iOS27 payload.

No XNU compiler, IPSW download, root-media generation or device access. This
route is deliberately limited to BDS/display diagnostics; incompatible source
changes require a newly qualified baseline, never silent reuse.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib
import zlib

BASE_COMMIT = 'ce869a1d7be7c845b1202777c05c3d61baf1a681'
BASE_RUN = 43349357896
BASE_MANIFEST = '09454c2348ec41420d2a9c90656bc9746d11b18a9352f9b572e96eedceac6429'
BASE_BOOT = 'a251b4eaf6f17feff09aed144259aafbc28dde01ec9508269184b6a1cb2b1735'
BOOT_BYTES = 95428608
FD_OFFSET, FD_BYTES, FAT_BYTES = 8192, 0x300000, 88*1024**2
FAT_OFFSET = FD_OFFSET+FD_BYTES
BDS = 'Platforms/Xiaomi/myronPkg/Library/MyronBootManagerLib/MyronBootManagerLib.c'
PREFIX = 'device/myron27/'
ALLOWED = {PREFIX+n for n in ('fixtures/firmware-source.json', 'prepare_firmware_source.py', 'firmware_memory_contract.py')}
# This reviewed update only changes the BDS digest/restoration path. Publishers
# remain the original 2GiB versions; arbitrary contract changes are refused.
MEMORY_CONTRACT = '463a400a8c3c897649ded49b64df90c6aa4cc6acc1e0f9b193c6a5f2b4f4f59d'
PUBLISHERS = {
 'Library/MyronBootManagerLib/BootMemory.c':'2aaa607ee7cb004ecd3a99fdb0a2be2d9524a815a3cacf99da04531b5b165400',
 'Library/MyronBootManagerLib/MemoryWindow.h':'c03c16e7520a84dfeac3897579f3b2cae4c94509ddaa6569a1f0458081a8ac9e',
}


def need(ok, message):
    if not ok: raise ValueError(message)


def sha(data): return hashlib.sha256(data).hexdigest()
def read_json(p): return json.loads(Path(p).read_text())
def save(p, obj): Path(p).write_text(json.dumps(obj,indent=2)+'\n')


def sources(repo):
    raw=(repo/'myron27-inputs.json').read_bytes()
    base=json.loads(raw);delta=read_json(repo/'myron27-storage-delta.json')
    need(delta['base_snapshot_sha256']==sha(raw),'Wrong source snapshot base')
    base['files'].update(delta['files'])
    for name,row in base['files'].items():
        need(sha(row['content'].encode())==row['sha256'],'Changed source digest: '+name)
    return base['files']


def check_sources(current, baseline):
    old,new=sources(baseline),sources(current)
    need(set(old)==set(new),'Source inventory changed; full qualification required')
    changed={p for p in old if old[p]!=new[p]}
    need(changed<=ALLOWED,'Payload/loader sources changed; no firmware-only reuse: '+str(sorted(changed-ALLOWED)))
    key=PREFIX+'fixtures/firmware-source.json'
    a,b=json.loads(old[key]['content']),json.loads(new[key]['content'])
    need(set(a['files'])==set(b['files']),'Firmware module inventory changed')
    fw_changed=[p for p in a['files'] if a['files'][p]!=b['files'][p]]
    need(set(fw_changed)<={BDS},'Firmware changes exceed reviewed BDS-only scope')
    for p,row in b['files'].items():
        need(sha(row['content'].encode())==row['sha256'],'Bad firmware source digest: '+p)
        need(row['base_sha256']==a['files'][p]['base_sha256'],'Firmware base changed: '+p)
    key=PREFIX+'prepare_firmware_source.py'
    normalize=lambda s:re.sub(r"SOURCE_SHA256 = '[0-9a-f]{64}'",'SOURCE_SHA256 = REVIEWED',s)
    need(normalize(old[key]['content'])==normalize(new[key]['content']),'Firmware repository pins or preparation changed')
    need(sha(new[PREFIX+'fixtures/firmware-source.json']['content'].encode()) in new[key]['content'],
         'Firmware snapshot is not pinned by preparer')
    key=PREFIX+'firmware_memory_contract.py'
    need(new[key]==old[key] or new[key]['sha256']==MEMORY_CONTRACT,'Unreviewed memory contract')
    return dict(changed_sources=sorted(changed),changed_firmware_sources=fw_changed,
                baseline_commit=BASE_COMMIT,payload_sources_unchanged=True,loader_sources_unchanged=True)


def read_base(base):
    raw=(base/'root-startup.img').read_bytes()
    manifest=(base/'deployment.json').read_bytes()
    need(sha(manifest)==BASE_MANIFEST,'Baseline manifest changed')
    need(len(raw)==BOOT_BYTES and sha(raw)==BASE_BOOT,'Baseline boot image changed')
    m=json.loads(manifest);r=m['image_reports']['root-startup.img']
    need(m['files']['root-startup.img']==dict(bytes=len(raw),sha256=sha(raw)),'Baseline descriptor mismatch')
    need(r['fat_offset']==FAT_OFFSET and len(raw[FAT_OFFSET:])==FAT_BYTES,'Baseline payload layout changed')
    need(sha(raw[4096:FD_OFFSET])==r['shim_sha256'],'Baseline shim mismatch')
    need(sha(raw[FD_OFFSET:FAT_OFFSET])==r['fd_sha256'],'Baseline firmware mismatch')
    need(sha(raw[FAT_OFFSET:])==r['payload_sha256'],'Baseline FAT mismatch')
    return raw,m


def payload(base, out):
    raw,m=read_base(base);out.mkdir(parents=True,exist_ok=False)
    fat=raw[FAT_OFFSET:];(out/'payload.img').write_bytes(fat)
    report=m['image_reports']['root-startup.img'];hashes=report['embedded_files']
    def read(name):return subprocess.check_output(['mtype','-i',str(out/'payload.img'),'::/EFI/UniXNU/'+name])
    for name,digest in hashes.items():
        need(name.startswith('EFI/UniXNU/Payloads/') and '/' not in name[len('EFI/UniXNU/Payloads/'):], 'Unexpected embedded name')
        need(sha(read(name[len('EFI/UniXNU/'):]))==digest,'Embedded file mismatch: '+name)
    menu=tomllib.loads(read('unixnu.toml').decode())
    selected=[e for e in menu['entry'] if e['id']==menu['boot']['default']]
    need(len(selected)==1 and menu['boot']['timeout']==-1 and menu['boot']['rotate']==0,'Changed manual boot policy')
    e=selected[0]
    need(e['type']=='xnu' and e['path']=='Payloads/kernel.macho' and e['initrd']=='Payloads/scratch-data.img','Unexpected boot entry')
    need('myron27-dyld-startup=1' in e['args'].split(),'Wrong retained startup variant')
    h=lambda name:hashes['EFI/UniXNU/Payloads/'+name]
    header=(f'#define MYRON_KERNEL_FAT_BYTES 0x{len(fat):x}ULL\n'
            f'#define MYRON_KERNEL_FAT_CRC32 0x{zlib.crc32(fat):08x}U\n'
            f'#define MYRON_KERNEL_FAT_SHA256 "{sha(fat)}"\n'
            f'#define MYRON_R46_KERNEL_SHA256 "{h("kernel.macho")}"\n')
    (out/'KernelPayloadExpected.h').write_text(header)
    p=dict(result='passed',bytes=len(fat),sha256=sha(fat),crc32=f'{zlib.crc32(fat):08x}',
           transport_header_sha256=sha(header.encode()),kernel_sha256=h('kernel.macho'),
           adt_sha256=h('kernel.macho.adt'),kernel_args=e['args'],root_volume_enabled=True,
           boot_assets=dict(initrd=e['initrd'],data_sha256=h('scratch-data.img'),
               trust_bundle_sha256=h('kernel.macho.trustcache'),dyld_startup_probe_enabled=True),
           reused_from_run=BASE_RUN,baseline_boot_sha256=BASE_BOOT,phone_tested=False)
    save(out/'payload.json',p)
    return p


def splice(raw, fd):
    need(len(raw)==BOOT_BYTES and sha(raw)==BASE_BOOT,'Source image changed during build')
    need(len(fd)==FD_BYTES,'Firmware must remain exactly 3MiB')
    result=raw[:FD_OFFSET]+fd+raw[FAT_OFFSET:]
    need(result[:FD_OFFSET]==raw[:FD_OFFSET] and result[FAT_OFFSET:]==raw[FAT_OFFSET:],'Non-firmware bytes changed')
    need(len(result)==len(raw),'Boot image size changed')
    return result


def finish(base, work, output, source_check, elapsed):
    raw,m=read_base(base);p=read_json(work/'payload/payload.json')
    fw=read_json(work/'firmware/firmware-build.json')
    fv=read_json(work/'firmware/firmware-verification.json')
    host=read_json(work/'root-handoff/report.json')
    need(fw['result']==fv['result']==host['result']=='passed','Incomplete firmware/handoff qualification')
    need(fv['full_fd_unpacked'] and fv['actual_compile_commands_checked']>=400 and
         fv['efi_capsule_matches_qemu_executed_bytes'],'Incomplete final FD checks')
    need(fw['payload']==p and host['fat_sha256']==p['sha256']==sha(raw[FAT_OFFSET:]),'Payload changed during qualification')
    need(host['root_sidecars_checked'] and host['root_sidecar_failure_cases']==12 and
         host['inputs_read_from_fat'] and host['byte_equality_at_handoff'],'Root handoff qualification missing')
    stage=fw['source_stage']
    need(stage['driver_staged_sha256']==host['driver_sha256'] and
         stage['stream_source_sha256']==host['stream_source_sha256'],'Qualified loader differs from built loader')
    for name,digest in PUBLISHERS.items():
        need(fw['board_source_hashes'][name]==digest,'Memory publisher changed')
    fd=(work/'firmware/Build/myronPkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd').read_bytes()
    need(sha(fd)==fw['fd_sha256']==fv['fd_sha256'],'Built firmware/report mismatch')
    image=splice(raw,fd)
    output.mkdir(parents=True,exist_ok=False)
    out_image=output/'root-startup.img';out_image.write_bytes(image)
    need(out_image.read_bytes()==image,'Boot output readback mismatch')
    proof=dict(result='passed',scope='firmware-only',baseline_run=BASE_RUN,baseline_commit=BASE_COMMIT,
               baseline_image_sha256=BASE_BOOT,source_check=source_check,fd_sha256=sha(fd),
               boot_sha256=sha(image),bytes=len(image),kernel_recompiled=False,root_media_rebuilt=False,
               header_and_shim_unchanged=True,entire_fat_byte_identical=True,
               root_install_reusable=True,elapsed_seconds=round(elapsed,1),
               firmware_verification=fv,root_handoff=host,phone_tested=False,desktop_reached=False)
    save(output/'boot-only-report.json',proof)
    m=copy.deepcopy(m);m['files']['root-startup.img']=dict(bytes=len(image),sha256=sha(image))
    r=m['image_reports']['root-startup.img']
    r.update(bytes=len(image),sha256=sha(image),fd_sha256=sha(fd),
             firmware_report_sha256=sha((output/'boot-only-report.json').read_bytes()),
             firmware_report_scope='firmware-only',inherited_payload_qualification_run=BASE_RUN)
    m['boot_only_rebuild']=dict(baseline_run=BASE_RUN,baseline_boot_sha256=BASE_BOOT,
                              report_sha256=sha((output/'boot-only-report.json').read_bytes()))
    save(output/'deployment.json',m)
    return proof


def checkout(url, pin, target):
    need(not target.is_symlink() and (not target.exists() or
         (target.is_dir() and not any(target.iterdir()))), 'Dependency target must be absent or empty')
    target.mkdir(parents=True,exist_ok=True)
    subprocess.run(['git','-C',str(target),'init','-q'],check=True)
    subprocess.run(['git','-C',str(target),'fetch','-q','--depth','1',url,pin],check=True)
    subprocess.run(['git','-C',str(target),'checkout','-q','--detach','FETCH_HEAD'],check=True)
    need(subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip()==pin,'Wrong dependency pin')


def main():
    a=argparse.ArgumentParser(description=__doc__)
    for n in ('baseline-source','base','work','output','clang-bin','qemu'):
        a.add_argument('--'+n,type=Path,required=True)
    a=a.parse_args()
    for n,v in vars(a).items():setattr(a,n,v.resolve())
    repo=Path(__file__).resolve().parent
    need(subprocess.check_output(['git','-C',str(a.baseline_source),'rev-parse','HEAD'],text=True).strip()==BASE_COMMIT,'Wrong baseline checkout')
    review=check_sources(repo,a.baseline_source);read_base(a.base)
    need(not a.work.exists() and not a.output.exists(),'Use new work/output directories')
    a.work.mkdir(parents=True);start=time.monotonic()
    env=dict(os.environ,CLANG_BIN=str(a.clang_bin)+'/',PATH=str(a.clang_bin)+os.pathsep+os.environ['PATH'])
    subprocess.run([sys.executable,str(repo/'myron27-build.py'),'--source-only'],env=env,check=True)
    device=Path(os.environ['RUNNER_TEMP'])/'myron-iphone27/device/myron27'
    sys.path.insert(0,str(device))
    from prepare_firmware_source import prepare
    from prepare_loader import prepare as loader
    upstream=a.work/'upstream'
    checkout('https://github.com/UniXNU/UniXNU.git','04573c510c5fd4892ca6948739389141cc9e05f5',upstream)
    checkout('https://github.com/UniXNU/DarwinBoot.git','3c75734014cdab0acd9541e88057b7606ee7ae08',upstream/'drivers/DarwinBoot')
    prepare(a.work/'mu')
    subprocess.run(['make','-C',str(a.work/'mu/Mu_Basecore/BaseTools/Source/C'),'-j4','CLANG=1','CC=clang','CXX=clang++'],env=env,check=True)
    loader(upstream/'drivers/DarwinBoot',a.work/'loader-source')
    payload(a.base,a.work/'payload')
    def run(script,*args):subprocess.run([sys.executable,str(device/script),*map(str,args)],env=env,check=True)
    run('tests/test_handoff_qemu.py','--clang',a.clang_bin/'clang','--qemu',a.qemu,
        '--edk2',a.work/'mu/Mu_Basecore','--out',a.work/'capsule-test')
    run('tests/check_root_handoff.py','--edk2',a.work/'mu/Mu_Basecore','--upstream',upstream,
        '--staged',a.work/'loader-source','--payload',a.work/'payload','--out',a.work/'root-handoff','--cc',a.clang_bin/'clang')
    try:
        run('build_firmware.py','--mu',a.work/'mu','--upstream',upstream,'--staged',a.work/'loader-source',
            '--clang-bin',a.clang_bin,'--payload',a.work/'payload','--out',a.work/'firmware')
        run('tests/verify_firmware.py','--build',a.work/'firmware','--mu',a.work/'mu',
            '--staged',a.work/'loader-source','--qemu-test',a.work/'capsule-test','--out',a.work/'firmware/firmware-verification.json')
    except Exception:
        log=a.work/'firmware/build.log'
        if log.exists():print('\n'.join(log.read_text(errors='replace').splitlines()[-100:]),file=sys.stderr)
        raise
    proof=finish(a.base,a.work,a.output,review,time.monotonic()-start)
    print(json.dumps({k:v for k,v in proof.items() if k not in ('firmware_verification','root_handoff')},indent=2))


if __name__=='__main__':main()
