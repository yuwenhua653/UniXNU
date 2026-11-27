#!/usr/bin/env python3
"""Export the existing myron Data overlay from root recovery, read-only."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import struct
import re
import zipfile
import zlib
import myron_read_log as log

PAGES=262144
BITMAP_BLOCKS=8
WINDOW_BLOCKS=1+BITMAP_BLOCKS+PAGES
GROWN_PAGES=4194304
GROWN_BLOCKS=2+128+GROWN_PAGES
require=log.require

def seed_identity(deployment):
    contract=deployment.get('data_seed',{})
    require(isinstance(contract,dict) and contract.get('format')==1 and
            contract.get('logical_bytes')==PAGES*4096,'Missing original 1 GiB seed contract')
    digest=contract.get('logical_sha256')
    require(isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest) and
            digest!='0'*64,'Invalid original seed digest')
    return digest

def load_deployment(deployment_path,seed_contract_path):
    deployment=json.loads(Path(deployment_path).read_text())
    deployment['data_seed']=json.loads(Path(seed_contract_path).read_text())
    seed_identity(deployment)
    return deployment

def geometry(deployment):
    log.window(deployment) # all existing deployment/partition/carrier guards
    g=deployment['geometry']
    marker=g['last']+1-g['reserveBlocks']-WINDOW_BLOCKS-1
    root_end=g['first']+(deployment['files']['root-container.raw']['bytes']+4095)//4096
    require(marker-root_end>=1024,'Data overlaps signed root or guard')
    return marker

def validate(marker,header,bitmap,first,expected_seed,pages=PAGES):
    require(pages in (PAGES,GROWN_PAGES),'Unsupported Data capacity')
    bitmap_blocks=pages//32768
    require(len(marker)==len(header)==4096 and len(bitmap)==bitmap_blocks*4096,'Short Data metadata')
    require(marker[:8]==b'MYRDATA1' and struct.unpack_from('<IIQQ',marker,8)==(1,2,first,2+bitmap_blocks+pages),
            'No committed matching myron Data marker; nothing exported')
    require(struct.unpack_from('<I',marker,32)[0]==zlib.crc32(marker[:32]),'Data marker CRC differs')
    require(header[:8]==b'SHNGDATA' and struct.unpack_from('<IIQ',header,8)==(1,64,pages),
            'Unsupported Data overlay header')
    require(header[24:56].hex()==expected_seed,'Data belongs to a different seed')
    require(struct.unpack_from('<I',header,60)[0]==zlib.crc32(header[:60]),'Overlay CRC differs')

def selected(device,deployment,original):
    target=original-GROWN_BLOCKS
    root_end=deployment['geometry']['first']+(deployment['files']['root-container.raw']['bytes']+4095)//4096
    if target-root_end<1024:return original,PAGES,None,None
    marker=device.read(target,1)
    require(len(marker)==4096,'Short growth marker')
    if not any(marker):
        require(not any(device.read(original-1048610,1)),
                'Legacy expanded Data present; stale original export refused')
        return original,PAGES,target,marker
    require(marker[:8]==b'MYRDATA1' and struct.unpack_from('<I',marker,8)[0]==1 and
            struct.unpack_from('<QQ',marker,16)==(target,GROWN_BLOCKS) and
            struct.unpack_from('<I',marker,32)[0]==zlib.crc32(marker[:32]),'Growth marker damaged; stale original export refused')
    state=struct.unpack_from('<I',marker,12)[0]
    require(state in (1,2),'Unknown growth marker state')
    if state==1:
        require(not any(device.read(original-1048610,1)),
                'Legacy expanded Data present; stale original export refused')
    return (target,GROWN_PAGES,target,marker) if state==2 else (original,PAGES,target,marker)

def capture(device,deployment,out):
    out=Path(out);require(not out.exists(),'Output already exists')
    partial=out.with_suffix(out.suffix+'.partial');require(not partial.exists(),'Partial export already exists; keep it and choose a new name')
    first=geometry(deployment)
    expected_seed=seed_identity(deployment)
    layout,gpt=device.layout();require(layout==deployment['layout'],'GPT differs from deployment')
    first,pages,growth_first,growth_marker=selected(device,deployment,first)
    bitmap_blocks=pages//32768
    marker=device.read(first,1);header=device.read(first+1,1);bitmap=device.read(first+2,bitmap_blocks)
    validate(marker,header,bitmap,first,expected_seed,pages)
    count=sum(b.bit_count() for b in bitmap);done=0;digest=hashlib.sha256()
    print(f'Exporting {count*4096//1048576} MiB of changed Data pages; phone writes: 0',flush=True)
    with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for name,data in [('marker.bin',marker),('overlay-header.bin',header),('bitmap.bin',bitmap)]:z.writestr(name,data)
        with z.open('pages.bin','w',force_zip64=True) as dest:
            i=0
            while i<pages:
                if not (bitmap[i>>3]>>(i&7)&1):i+=1;continue
                n=1
                while n<128 and i+n<pages and bitmap[(i+n)>>3]>>((i+n)&7)&1:n+=1
                data=device.read(first+2+bitmap_blocks+i,n)
                require(len(data)==n*4096,'Short Data page read')
                dest.write(data);digest.update(data);i+=n;done+=n
                if done//4096!=(done-n)//4096:print(f'{done*4096//1048576} / {count*4096//1048576} MiB',flush=True)
        require(device.read(first,1)==marker and device.read(first+1,1)==header and
                device.read(first+2,bitmap_blocks)==bitmap,'Data metadata changed during export')
        require(growth_first is None or device.read(growth_first,1)==growth_marker,
                'Active Data selection changed during export')
        require(device.layout()==(layout,gpt),'GPT changed during export')
        require(done==count,'Export page count differs')
        z.writestr('report.json',json.dumps(dict(format=1,read_only=True,device_writes=0,
            complete=True,contains_user_data=True,marker_lba=first,pages=pages,present_pages=count,
            logical_bytes=pages*4096,active_overlay='grown' if pages==GROWN_PAGES else 'original',
            seed_sha256=expected_seed,pages_sha256=digest.hexdigest(),
            encoding='pages.bin contains bitmap-present pages in ascending page order'),indent=2))
    partial.rename(out)
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--deployment',type=Path,default=Path(__file__).with_name('deployment.json'))
    p.add_argument('--seed-contract',type=Path,default=Path(__file__).with_name('data-seed.json'))
    p.add_argument('--adb',default='adb');p.add_argument('--out',type=Path)
    a=p.parse_args();adb=shutil.which(a.adb);require(adb,'adb not found in PATH')
    out=a.out or Path('myron-data-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
    print('SEND THIS ZIP:',capture(log.Recovery(adb),load_deployment(a.deployment,a.seed_contract),out).resolve())

if __name__=='__main__':main()
