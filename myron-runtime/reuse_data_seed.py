#!/usr/bin/env python3
"""Reuse the byte-identical first persistent Data seed; never reseed an install."""
import hashlib
import json
from pathlib import Path
import shutil
import struct

RUN = '45074791666'
COMMIT = 'c2df8b8c2b93878b0f159821e6da1a7df18ab59d'
TRANSPORT = '528d1c330b73d799ef1b6fa49c4b46d4d4ad69b8537e6acec617468c45568611'
LOGICAL = '6834ba25bba6e94b5d646538f6548a95abeaa2d30a8af13b8238031e7997b94a'
BYTES = 1073741824
BOOT_HASHES = {'dd9676f5ff641e11f6ddbfdb3be7d48512e14cb90cf23720c196b299187e6e9d',
               'cdbdcab96330a8143d332f18cec9229fdaea0686b742daeefaca0f9692aea962'}

def require(ok, message):
    if not ok: raise ValueError(message)

def extract(boot, manifest, output):
    """Read only a pinned old boot. No reliance on ZIP names or current branch."""
    raw=Path(boot).read_bytes()
    require(hashlib.sha256(raw).hexdigest() in BOOT_HASHES, 'Wrong retained-seed boot image')
    d=json.loads(Path(manifest).read_text())
    r=d['image_reports']['root-startup.img']
    f=raw[r['fat_offset']:]
    require(hashlib.sha256(f).hexdigest()==r['payload_sha256'], 'FAT payload mismatch')
    u16=lambda o:struct.unpack_from('<H',f,o)[0]
    u32=lambda o:struct.unpack_from('<I',f,o)[0]
    bs=u16(11);cs=f[13]*bs;fb=u16(14)*bs;db=(u16(14)+f[16]*u32(36))*bs
    require(f[82:90]==b'FAT32   ' and bs==512, 'Unexpected FAT layout')
    def chain(cl):
        result=[];seen=set()
        while 2<=cl<0xffffff8:
            require(cl not in seen and fb+cl*4+4<=db, 'Invalid FAT chain')
            seen.add(cl);off=db+(cl-2)*cs
            require(off+cs<=len(f), 'FAT extent outside image')
            result.append(f[off:off+cs]);cl=u32(fb+cl*4)&0xfffffff
        require(cl>=0xffffff8, 'Truncated FAT chain')
        return b''.join(result)
    cl=u32(44)
    for part in ('EFI','UniXNU','Payloads','scratch-data.img'):
        found=[];lf={};data=chain(cl)
        for off in range(0,len(data),32):
            e=data[off:off+32]
            if e[0]==0:break
            if e[0]==229:lf={};continue
            if e[11]==15:
                lf[e[0]&31]=(e[1:11]+e[14:26]+e[28:32]).decode('utf-16le');continue
            short=e[:8].decode().strip();ext=e[8:11].decode().strip()
            name=''.join(lf[k] for k in sorted(lf)).split('\0')[0].rstrip('\uffff') if lf else short+('.'+ext if ext else '')
            lf={}
            if name.lower()==part.lower():found.append(((struct.unpack_from('<H',e,20)[0]<<16)|struct.unpack_from('<H',e,26)[0],struct.unpack_from('<I',e,28)[0]))
        require(len(found)==1, 'Missing/ambiguous seed path')
        cl,size=found[0]
    seed=chain(cl)[:size]
    require(hashlib.sha256(seed).hexdigest()==TRANSPORT, 'Retained Data seed differs')
    Path(output).write_bytes(seed)

def unpack(seed, raw):
    import data_seed
    report=data_seed.inspect_seed(seed)
    require(report['transport_sha256']==TRANSPORT and report['logical_sha256']==LOGICAL and
            report['logical_bytes']==BYTES and report['encoding']=='packed', 'Refusing foreign persistent Data seed')
    with Path(seed).open('rb') as src, Path(raw).open('xb') as dst:
        header=src.read(32);count=struct.unpack_from('<Q',header,24)[0]
        entries=[struct.unpack('<QQ',src.read(16)) for _ in range(count)]
        dst.truncate(BYTES)
        for offset,length in entries:
            dst.seek(offset)
            while length:
                block=src.read(min(length,1024*1024));require(block,'Truncated seed')
                dst.write(block);length-=len(block)
    require(data_seed.sha(raw)==LOGICAL, 'Unpacked Data hash mismatch')
    return report

def reuse(seed, output):
    import prepare_data_volume as volume
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    raw=output/'data.cdr';packed=output/'data.dbr'
    encoded=unpack(seed,raw)
    shutil.copyfile(seed,packed)
    with volume.attached(raw,output/'read-mount',True) as mounted:
        volume.run('diskutil','verifyVolume',mounted['device'])
        uuid=mounted['uuid'];free=shutil.disk_usage(mounted['path']).free
    require(volume.sha(raw)==LOGICAL, 'Readonly APFS check changed retained seed')
    report=dict(format=1,volume_uuid=uuid,seed_path=str(packed),raw_path=str(raw),
                initial_free_bytes=free,filesystem='apfs',raw_reopened_readonly=True,
                filesystem_verified=True,**encoded,runtime_qualified=False,persistent=False,
                phone_written=False,reused_from_run=RUN,reused_from_commit=COMMIT)
    (output/'volume.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--boot',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();extract(a.boot,a.manifest,a.out)
    print('PASS: retained Data seed '+TRANSPORT)
