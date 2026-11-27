#!/usr/bin/env python3
"""Prepare a disjoint 16 GiB overlay image; never write a device or resize APFS.

The output is an intermediate migration image, NOT FLASHABLE. APFS still has
its old container capacity until an on-device Apple resize operation succeeds.
Do not boot or restore this image using the existing 1 GiB updater.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile
import zlib
import export_data as old

BLOCK=4096
PAGES=old.GROWN_PAGES
BITMAP_BLOCKS=PAGES//(8*BLOCK)
BLOCKS=2+BITMAP_BLOCKS+PAGES
require=old.require

def geometry(deployment):
    source=old.geometry(deployment)
    first=source-BLOCKS
    root_end=deployment['geometry']['first']+(deployment['files']['root-container.raw']['bytes']+BLOCK-1)//BLOCK
    require(first-root_end>=1024,'No disjoint 16 GiB migration extent above signed root guard')
    max_gib=(source-root_end-1024-2)//(262144+8)
    return dict(source_marker_lba=source,target_marker_lba=first,target_blocks=BLOCKS,
                source_blocks=old.WINDOW_BLOCKS+1,target_logical_bytes=PAGES*BLOCK,
                maximum_disjoint_whole_gib=max_gib,
                remaining_gap_bytes=(first-root_end-1024)*BLOCK,
                original_retained=True,apfs_resized=False,flashable=False)

def marker(first,state):
    block=bytearray(BLOCK);block[:8]=b'MYRDATA1'
    struct.pack_into('<IIQQ',block,8,1,state,first,BLOCKS)
    struct.pack_into('<I',block,32,zlib.crc32(block[:32]))
    return bytes(block)

def header(source):
    block=bytearray(source)
    struct.pack_into('<Q',block,16,PAGES)
    struct.pack_into('<I',block,60,zlib.crc32(block[:60]))
    return bytes(block)

def runs(bitmap):
    i=0
    while i<old.PAGES:
        if not (bitmap[i>>3]>>(i&7)&1):i+=1;continue
        n=1
        while n<128 and i+n<old.PAGES and bitmap[(i+n)>>3]>>((i+n)&7)&1:n+=1
        yield i,n
        i+=n

def prepare(export,deployment,output):
    plan=geometry(deployment);expected_seed=old.seed_identity(deployment);output=Path(output)
    require(not output.exists(),'Output exists; never overwrite a migration image')
    partial=output.with_suffix(output.suffix+'.partial')
    require(not partial.exists(),'Partial output exists; preserve it and choose a new path')
    with zipfile.ZipFile(export) as z:
        expected={'marker.bin','overlay-header.bin','bitmap.bin','pages.bin','report.json'}
        require(len(z.namelist())==len(expected) and set(z.namelist())==expected,'Unexpected/duplicate export entries')
        sizes={'marker.bin':BLOCK,'overlay-header.bin':BLOCK,'bitmap.bin':32768}
        require(all(z.getinfo(n).file_size==size for n,size in sizes.items()),'Bad metadata lengths')
        require(z.getinfo('report.json').file_size<16384,'Oversized report')
        report=json.loads(z.read('report.json'))
        require(report.get('read_only') is True and report.get('device_writes')==0 and
                report.get('complete') is True and report.get('seed_sha256')==expected_seed and
                report.get('pages')==old.PAGES and report.get('marker_lba')==plan['source_marker_lba'],
                'Export identity or completion differs')
        before=z.read('marker.bin');source=z.read('overlay-header.bin');bitmap=z.read('bitmap.bin')
        old.validate(before,source,bitmap,plan['source_marker_lba'],expected_seed)
        count=sum(b.bit_count() for b in bitmap)
        require(count==report.get('present_pages') and z.getinfo('pages.bin').file_size==count*BLOCK,
                'Export page count differs')
        digest=hashlib.sha256()
        with partial.open('x+b') as dest:
            dest.truncate(BLOCKS*BLOCK)
            # Incomplete marker stays pending even after offline verification.
            # A future device installer must verify a FRESH source export,
            # copy/read back the new extent and only then commit ready.
            dest.write(marker(plan['target_marker_lba'],1));dest.write(header(source));dest.write(bitmap)
            with z.open('pages.bin') as pages:
                for index,n in runs(bitmap):
                    data=pages.read(n*BLOCK);require(len(data)==n*BLOCK,'Short exported pages')
                    digest.update(data);dest.seek((2+BITMAP_BLOCKS+index)*BLOCK);dest.write(data)
                require(not pages.read(1),'Trailing exported pages')
            require(digest.hexdigest()==report['pages_sha256'],'Export page SHA256 differs')
            dest.flush();verify=hashlib.sha256()
            for index,n in runs(bitmap):
                dest.seek((2+BITMAP_BLOCKS+index)*BLOCK);verify.update(dest.read(n*BLOCK))
            require(verify.digest()==digest.digest(),'Prepared pages failed readback')
            dest.seek(2*BLOCK);grown=dest.read(BITMAP_BLOCKS*BLOCK)
            require(grown[:len(bitmap)]==bitmap and not any(grown[len(bitmap):]),'Extended bitmap differs')
            dest.seek(0);require(dest.read(BLOCK)==marker(plan['target_marker_lba'],1),'Pending marker differs')
            require(dest.read(BLOCK)==header(source),'Extended header differs')
        plan.update(present_pages=count,pages_sha256=digest.hexdigest(),seed_sha256=expected_seed,
                    source_metadata_sha256=hashlib.sha256(before+source+bitmap).hexdigest(),
                    output_bytes=BLOCKS*BLOCK,device_writes=0)
    partial.rename(output)
    return plan

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--deployment',type=Path,required=True)
    p.add_argument('--seed-contract',type=Path,required=True)
    p.add_argument('--export',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--plan',action='store_true',help='Read local geometry only; no phone I/O or output image')
    a=p.parse_args()
    if a.plan and (a.export or a.output):p.error('--plan does not use --export/--output')
    if not a.plan and (not a.export or not a.output):p.error('Preparation requires --export and --output')
    deployment=old.load_deployment(a.deployment,a.seed_contract)
    print(json.dumps(geometry(deployment) if a.plan else prepare(a.export,deployment,a.output),indent=2))
