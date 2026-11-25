#!/usr/bin/env python3
"""Export the existing myron Data overlay from root recovery, read-only."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zipfile
import zlib
import myron_read_log as log

PAGES=262144
BITMAP_BLOCKS=8
WINDOW_BLOCKS=1+BITMAP_BLOCKS+PAGES
SEED='6834ba25bba6e94b5d646538f6548a95abeaa2d30a8af13b8238031e7997b94a'
require=log.require

def geometry(deployment):
    log.window(deployment) # all existing deployment/partition/carrier guards
    g=deployment['geometry']
    marker=g['last']+1-g['reserveBlocks']-WINDOW_BLOCKS-1
    root_end=g['first']+(deployment['files']['root-container.raw']['bytes']+4095)//4096
    require(marker-root_end>=1024,'Data overlaps signed root or guard')
    return marker

def validate(marker,header,bitmap,first):
    require(len(marker)==len(header)==4096 and len(bitmap)==32768,'Short Data metadata')
    require(marker[:8]==b'MYRDATA1' and struct.unpack_from('<IIQQ',marker,8)==(1,2,first,WINDOW_BLOCKS+1),
            'No committed matching myron Data marker; nothing exported')
    require(struct.unpack_from('<I',marker,32)[0]==zlib.crc32(marker[:32]),'Data marker CRC differs')
    require(header[:8]==b'SHNGDATA' and struct.unpack_from('<IIQ',header,8)==(1,64,PAGES),
            'Unsupported Data overlay header')
    require(header[24:56].hex()==SEED,'Data belongs to a different seed')
    require(struct.unpack_from('<I',header,60)[0]==zlib.crc32(header[:60]),'Overlay CRC differs')

def capture(device,deployment,out):
    out=Path(out);require(not out.exists(),'Output already exists')
    partial=out.with_suffix(out.suffix+'.partial');require(not partial.exists(),'Partial export already exists; keep it and choose a new name')
    first=geometry(deployment)
    layout,gpt=device.layout();require(layout==deployment['layout'],'GPT differs from deployment')
    marker=device.read(first,1);header=device.read(first+1,1);bitmap=device.read(first+2,BITMAP_BLOCKS)
    validate(marker,header,bitmap,first)
    count=sum(b.bit_count() for b in bitmap);done=0;digest=hashlib.sha256()
    print(f'Exporting {count*4096//1048576} MiB of changed Data pages; phone writes: 0',flush=True)
    with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for name,data in [('marker.bin',marker),('overlay-header.bin',header),('bitmap.bin',bitmap)]:z.writestr(name,data)
        with z.open('pages.bin','w',force_zip64=True) as dest:
            i=0
            while i<PAGES:
                if not (bitmap[i>>3]>>(i&7)&1):i+=1;continue
                n=1
                while n<128 and i+n<PAGES and bitmap[(i+n)>>3]>>((i+n)&7)&1:n+=1
                data=device.read(first+2+BITMAP_BLOCKS+i,n)
                require(len(data)==n*4096,'Short Data page read')
                dest.write(data);digest.update(data);i+=n;done+=n
                if done//4096!=(done-n)//4096:print(f'{done*4096//1048576} / {count*4096//1048576} MiB',flush=True)
        require(device.read(first,1)==marker and device.read(first+1,1)==header and
                device.read(first+2,BITMAP_BLOCKS)==bitmap,'Data metadata changed during export')
        require(device.layout()==(layout,gpt),'GPT changed during export')
        require(done==count,'Export page count differs')
        z.writestr('report.json',json.dumps(dict(format=1,read_only=True,device_writes=0,
            complete=True,contains_user_data=True,marker_lba=first,pages=PAGES,present_pages=count,
            seed_sha256=SEED,pages_sha256=digest.hexdigest(),
            encoding='pages.bin contains bitmap-present pages in ascending page order'),indent=2))
    partial.rename(out)
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--deployment',type=Path,default=Path(__file__).with_name('deployment.json'))
    p.add_argument('--adb',default='adb');p.add_argument('--out',type=Path)
    a=p.parse_args();adb=shutil.which(a.adb);require(adb,'adb not found in PATH')
    out=a.out or Path('myron-data-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
    print('SEND THIS ZIP:',capture(log.Recovery(adb),json.loads(a.deployment.read_text()),out).resolve())

if __name__=='__main__':main()
