#!/usr/bin/env python3
"""Read-only myron LUN0 GPT capture and native root geometry derivation.

Never opens a disk for writing or changes GPT. Inputs are saved header/table
bytes; the native driver rechecks the partition before publishing root media.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import uuid
import zlib
import zipfile

BLOCK = 4096
LINUX_DATA = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
FILES = ('primary-header.bin','primary-entries.bin','backup-header.bin','backup-entries.bin')


def require(ok, message):
    if not ok: raise ValueError(message)


def header(raw, own, other):
    require(len(raw)==BLOCK,'GPT header must be one physical 4K block')
    sig,rev,size,crc,reserved,current,alternate,first,last,guid,table,count,width,table_crc = struct.unpack_from('<8s4I4Q16sQ3I',raw)
    require(sig==b'EFI PART' and rev==0x10000 and 92<=size<=BLOCK and reserved==0,
            'Unsupported GPT header')
    require((current,alternate)==(own,other),'GPT header LBA/capacity mismatch')
    check=bytearray(raw[:size]);check[16:20]=bytes(4)
    require(zlib.crc32(check)==crc,'GPT header CRC mismatch')
    require(any(guid) and 0<count<=128 and width==128,'Unsupported GPT GUID/entry geometry')
    blocks=(count*width+BLOCK-1)//BLOCK
    require(first<=last<(other if own==1 else own),'GPT usable range invalid')
    return dict(first=first,last=last,guid=guid,table=table,count=count,width=width,
                table_crc=table_crc,blocks=blocks)


def validated_table(primary, entries, backup, backup_entries, disk_last):
    require(type(disk_last) is int and 11<=disk_last<=0xffffffff,'Unsupported READ(10) capacity')
    p=header(primary,1,disk_last);b=header(backup,disk_last,1)
    require(2<=p['table']<=64 and p['first']>=p['table']+p['blocks'] and
            disk_last-p['last']>p['blocks'],'Primary GPT bounds overlap usable blocks')
    require(all(p[k]==b[k] for k in ('first','last','guid','count','width','table_crc')) and
            p['last']<b['table']<disk_last and b['blocks']<=disk_last-b['table'],
            'Backup GPT mismatch/bounds')
    require(len(entries)==len(backup_entries)==p['blocks']*BLOCK,'GPT table length mismatch')
    n=p['count']*128
    require(zlib.crc32(entries[:n])==p['table_crc'] and
            zlib.crc32(backup_entries[:n])==b['table_crc'],'GPT table CRC mismatch')
    require(entries[:n]==backup_entries[:n],'Primary/backup GPT tables differ')
    used=[]
    for i in range(p['count']):
        e=entries[i*128:(i+1)*128]
        if not any(e[:16]):continue
        kind,ident,first,last,attrs=struct.unpack_from('<16s16s3Q',e)
        require(any(ident) and p['first']<=first<=last<=p['last'],'Invalid partition GUID/range')
        require(all(ident!=r['guid'] for r in used),'Duplicate partition GUID')
        require(all(last<r['first'] or r['last']<first for r in used),'Partitions overlap')
        try:name=e[56:128].decode('utf-16-le').split('\0',1)[0]
        except UnicodeDecodeError as exc:raise ValueError('Invalid GPT name') from exc
        row=dict(index=i+1,first=first,last=last,guid=ident,name=name,kind=kind,attrs=attrs)
        used.append(row)
    return p,used


def inspect(primary, entries, backup, backup_entries, disk_last):
    p,used=validated_table(primary,entries,backup,backup_entries,disk_last)
    selected=[r for r in used if r['name']=='unixnu']
    require(len(selected)==1,'Require exactly one unixnu partition; no userdata fallback')
    r=selected[0]
    require(r['kind']==LINUX_DATA and r['attrs']==0,'unixnu type/attributes differ from native driver')
    require(r['first']>=6 and disk_last-r['last']>=5,'unixnu geometry unsupported by native driver')
    return dict(first=r['first'],last=r['last'],diskLast=disk_last,
                partitionGuid=str(uuid.UUID(bytes_le=r['guid'])),partition_index=r['index'],
                partition_bytes=(r['last']-r['first']+1)*BLOCK,
                disk_guid=str(uuid.UUID(bytes_le=p['guid'])))


def read_capture(directory):
    directory=Path(directory)
    meta_path=directory/'capture.json'
    require(meta_path.is_file() and meta_path.stat().st_size<=16384,'Missing/big capture metadata')
    meta=json.loads(meta_path.read_text())
    require(meta.get('format')==1 and meta.get('device')=='myron' and meta.get('lun')==0 and
            meta.get('logical_block_size')==BLOCK,'Capture is not myron LUN0/4K')
    values=[]
    for name in FILES:
        f=directory/name
        require(f.is_file() and not f.is_symlink() and f.stat().st_size<=16384,'Invalid captured GPT file: '+name)
        raw=f.read_bytes()
        require(hashlib.sha256(raw).hexdigest()==meta.get('sha256',{}).get(name),'Capture bytes changed: '+name)
        values.append(raw)
    layout=inspect(*values,meta.get('disk_last'))
    binding=hashlib.sha256(json.dumps(dict(layout=layout,files=meta['sha256']),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return layout,binding


def geometry(directory, image_bytes, carrier_bytes):
    layout,binding=read_capture(directory)
    return allocate(layout,image_bytes,carrier_bytes),binding


def allocate(layout, image_bytes, carrier_bytes):
    require(type(image_bytes) is int and image_bytes>=BLOCK and image_bytes%BLOCK==0,'Invalid root image size')
    require(type(carrier_bytes) is int and BLOCK<=carrier_bytes<=128*1024**2 and carrier_bytes%BLOCK==0,'Invalid carrier size')
    reserve=((carrier_bytes+1024**2-1)//1024**2)*256
    offset=layout['partition_bytes']-reserve*BLOCK
    require(offset>=image_bytes,'Original root and policy reserve do not fit unixnu')
    result={k:layout[k] for k in ('first','last','diskLast','partitionGuid')}
    result.update(carrierOffset=offset,carrierCapacity=carrier_bytes,reserveBlocks=reserve)
    from prepare_root_bundle import check_geometry
    check_geometry(result)
    return result


HISTORY_FILES=('storage-report-r65s.json','verification.json','installation.json')


def read_history(directory):
    """Validate R65s pre-change GPT plus R65t/u post-change reports.

    This derives historical geometry, never fabricates a post-change GPT dump
    and never asserts that the currently connected handset still matches it.
    Original reports stay private; only hashes and geometry leave this reader.
    """
    raw={}
    for name in HISTORY_FILES:
        path=Path(directory)/name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<=2*1024**2,
                'Missing/invalid historical report: '+name)
        raw[name]=path.read_bytes()
    storage,verified,installed=(json.loads(raw[n]) for n in HISTORY_FILES)
    require(storage.get('revision')=='65s' and storage.get('collection_finished') is True and
            storage.get('gpt_validated') is True and storage.get('partition_write_performed') is False,
            'Require completed R65s pre-change inspection')
    identity=storage['identity'];geo=storage['geometry']
    require(identity.get('ro.product.device')=='myron' and identity.get('uid')=='0' and
            storage.get('adb_transport_state')=='recovery' and geo.get('disk')=='/dev/block/sda' and
            geo.get('sector')==BLOCK and type(geo.get('total_bytes')) is int and
            geo['total_bytes']%BLOCK==0,'Historical device/LUN/sector mismatch')
    disk_last=geo['total_bytes']//BLOCK-1
    probes=storage['probes'];parts=[]
    for name,size in (('gpt_read_1',BLOCK),('gpt_read_2',6*BLOCK),('gpt_read_3',5*BLOCK)):
        row=probes[name]
        require(row.get('returncode')==0 and row.get('stdout_bytes')==size,'Historical GPT read failed')
        data=base64.b64decode(row['stdout_bytes_base64'],validate=True)
        require(len(data)==size,'Historical GPT read length mismatch');parts.append(data)
    first,primary_region,backup_region=parts
    require(first==primary_region[BLOCK:2*BLOCK],'Historical primary header reads differ')
    p=header(first,1,disk_last)
    require(p['table']==2 and p['count']==64 and p['width']==128,'Unsupported R65s GPT layout')
    backup=backup_region[-BLOCK:];b=header(backup,disk_last,1)
    require(b['table']==disk_last-4,'Unsupported R65s backup table placement')
    count=p['blocks']*BLOCK
    p,rows=validated_table(first,primary_region[2*BLOCK:2*BLOCK+count],backup,
                           backup_region[:count],disk_last)
    require(hashlib.sha256(primary_region).hexdigest()==storage['gpt']['primary_sha256'] and
            hashlib.sha256(backup_region).hexdigest()==storage['gpt']['backup_sha256'],
            'Historical GPT region hash mismatch')
    users=[r for r in rows if r['name']=='userdata']
    require(len(users)==1 and users[0]['index']==34 and not any(r['name']=='unixnu' for r in rows) and
            all(r['index']!=35 for r in rows),'Historical pre-change partition set mismatch')
    user=users[0]
    require(user['last']==max(r['last'] for r in rows) and geo.get('index')==34 and
            geo.get('raw')=='/dev/block/sda34' and geo.get('start_512')==user['first']*8 and
            geo.get('userdata_bytes')==(user['last']-user['first']+1)*BLOCK,
            'Historical userdata does not match raw GPT')
    require(verified.get('partition_verified') is True,'Missing post-change partition verification')
    root=verified['root_binding'];start=root.get('first_lba');end=root.get('last_lba')
    require(root.get('name')=='unixnu' and root.get('sector_bytes')==BLOCK and
            type(start) is int and type(end) is int and user['first']<start<=end<=user['last'] and
            start%256==0 and (end+1)%256==0 and (end-start+1)*BLOCK==32*1024**3 and
            disk_last-end>=5,'Historical unixnu bounds invalid')
    ident=uuid.UUID(root['guid'])
    require(ident.int!=0 and ident.bytes_le.hex()==root.get('guid_bytes_le') and
            all(ident.bytes_le!=r['guid'] for r in rows),'Historical unixnu GUID invalid')
    digest=root.get('image_sha256');size=root.get('image_bytes')
    require(isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest) and
            type(size) is int and BLOCK<=size<=(end-start+1)*BLOCK and size%BLOCK==0,
            'Historical image identity invalid')
    require(installed.get('revision')=='65u' and installed.get('root_image_installed') is True and
            installed.get('gpt_unchanged') is True and installed.get('root_guid')==str(ident) and
            installed.get('image_sha256')==installed.get('device_image_sha256')==digest and
            installed.get('written_bytes')==size,'Historical installation/verification mismatch')
    offset=0
    for row in installed['chunks']:
        n=row.get('bytes')
        require(type(row.get('offset')) is int and row['offset']==offset and type(n) is int and
                n==min(64*1024**2,size-offset) and n>0 and
                isinstance(row.get('sha256'),str) and re.fullmatch('[0-9a-f]{64}',row['sha256']),
                'Historical installation chunks incomplete')
        offset+=n
    require(offset==size,'Historical installation coverage incomplete')
    layout=dict(first=start,last=end,diskLast=disk_last,partitionGuid=str(ident),partition_index=35,
                partition_bytes=(end-start+1)*BLOCK,disk_guid=str(uuid.UUID(bytes_le=p['guid'])))
    binding=hashlib.sha256(json.dumps(dict(source='historical-r65s-r65u',layout=layout,
        files={k:hashlib.sha256(v).hexdigest() for k,v in raw.items()}),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return layout,binding


def historical_geometry(directory,image_bytes,carrier_bytes):
    layout,binding=read_history(directory)
    return allocate(layout,image_bytes,carrier_bytes),binding


def read_blocks(call, path, skip, count):
    """Read exact bytes through legacy exec-out without remote dd diagnostics.

    exec-out can merge remote stderr into stdout before the host sees it.
    Suppress stderr on the device, and append a failure marker on nonzero dd
    status so even a full-length failed read cannot be accepted.
    """
    require(re.fullmatch(r'/dev/block/sda|/dev/block/sd[a-z][1-9][0-9]*',path) is not None,
            'Invalid binary read path')
    require(type(skip) is int and skip>=0 and type(count) is int and 1<=count<=16384,
            'Invalid binary read range')
    command=(f'dd if={path} bs=4096 skip={skip} count={count} '
             '2>/dev/null || printf MYRON_READ_FAILED')
    raw=call('exec-out',command)
    require(len(raw)==count*BLOCK,
            f'Short or contaminated device read: {path}, LBA {skip}, '
            f'expected {count*BLOCK} bytes, received {len(raw)} bytes; '
            f'dd_failed={raw.endswith(b"MYRON_READ_FAILED")}')
    return raw


def capture(adb, output, serial=None):
    """Only fixed read-only ADB commands, in an already-running root recovery."""
    output=Path(output).resolve();require(not output.exists(),'Use a new capture directory')
    def call(*args):
        r=subprocess.run([str(adb),*(['-s',serial] if serial else []),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        return r.stdout
    def shell(*args):return call('shell',*args).decode().strip()
    require(shell('getprop','ro.product.device')=='myron','Connected device is not myron')
    require(shell('id','-u')=='0','Use recovery with root ADB; ordinary Android is insufficient')
    require(shell('getprop','ro.bootmode')=='recovery' or shell('getprop','init.svc.recovery')=='running',
            'Device must already be in recovery; this tool does not reboot it')
    target=shell('readlink','-f','/dev/block/by-name/unixnu')
    require(re.fullmatch(r'/dev/block/sda[1-9][0-9]*',target) is not None,'unixnu is not on expected LUN0 sda')
    require(shell('cat','/sys/class/block/sda/queue/logical_block_size')=='4096','LUN0 logical block size is not 4096')
    sectors=shell('cat','/sys/class/block/sda/size')
    require(sectors.isdecimal() and int(sectors)%8==0,'Invalid LUN0 capacity')
    disk_last=int(sectors)//8-1
    require(11<=disk_last<=0xffffffff,'Unsupported LUN0 capacity')
    def read(lba,count):
        require(1<=count<=4 and 0<=lba<=disk_last and count<=disk_last-lba+1,'Bounded GPT read exceeded')
        return read_blocks(call,'/dev/block/sda',lba,count)
    primary=read(1,1);p=header(primary,1,disk_last)
    require(2<=p['table']<=64 and p['first']>=p['table']+p['blocks'],'Unsafe primary table range')
    backup=read(disk_last,1);b=header(backup,disk_last,1)
    require(p['last']<b['table']<disk_last and b['blocks']<=disk_last-b['table'],'Unsafe backup table range')
    entries=read(p['table'],p['blocks']);back_entries=read(b['table'],b['blocks'])
    layout=inspect(primary,entries,backup,back_entries,disk_last)
    require(target=='/dev/block/sda'+str(layout['partition_index']),'Kernel partition mapping differs from GPT')
    # A second pass detects GPT updates during capture. CRC checks are not a
    # proof of freshness after capture; installation must re-read the device.
    values=(primary,entries,backup,back_entries)
    again=(read(1,1),read(p['table'],p['blocks']),read(disk_last,1),read(b['table'],b['blocks']))
    require(values==again,'GPT changed during read-only capture')
    meta=dict(format=1,device='myron',lun=0,logical_block_size=BLOCK,disk_last=disk_last,
              source='adb-recovery',read_only=True,gpt_double_read_equal=True,
              sha256={n:hashlib.sha256(v).hexdigest() for n,v in zip(FILES,values)})
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='myron-gpt-',dir=output.parent) as temp:
        work=Path(temp)
        for n,v in zip(FILES,values):(work/n).write_bytes(v)
        (work/'capture.json').write_text(json.dumps(meta,indent=2)+'\n')
        read_capture(work)
        work.rename(output)
    return dict(captured=True,read_only=True,device_writes=0,partition_bytes=layout['partition_bytes'],directory=str(output))


def archive_capture(directory):
    directory=Path(directory);read_capture(directory)
    archive=directory.with_name(directory.name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name in ('capture.json',*FILES):z.write(directory/name,name)
    return str(archive)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    c=sub.add_parser('capture');c.add_argument('--adb',default='adb');c.add_argument('--out',type=Path,required=True);c.add_argument('--zip',action='store_true')
    g=sub.add_parser('geometry');source=g.add_mutually_exclusive_group(required=True)
    source.add_argument('--capture',type=Path);source.add_argument('--history',type=Path)
    g.add_argument('--image-bytes',type=int,required=True);g.add_argument('--carrier-bytes',type=int,required=True)
    a=p.parse_args()
    if a.mode=='capture':
        result=capture(a.adb,a.out)
        if a.zip:result['send_zip']=archive_capture(a.out)
    else:
        historical=a.history is not None
        geo,binding=(historical_geometry if historical else geometry)(
            a.history if historical else a.capture,a.image_bytes,a.carrier_bytes)
        result=dict(geometry=geo,geometry_binding_sha256=binding,
                    geometry_source='historical-r65s-r65u' if historical else 'captured-gpt',
                    current_device_verified=False,post_change_gpt_bytes_validated=not historical,
                    device_runtime_verified=False)
    print(json.dumps(result,indent=2))
