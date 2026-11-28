#!/usr/bin/env python3
"""Read-only recovery scan for allowlisted APFS-helper JSON; never exports pages.

This is a content scan, not an APFS pathname resolver. Reports can be stale;
absence does not prove the helper did not run (fragmentation/compression).
"""
import argparse,datetime,hashlib,json,re,shutil,struct,zipfile
from pathlib import Path
import export_data as data

STATUS={'refused','inspected','already-expanded','expanded-and-verified','resize-outcome-unverified-no-auto-retry'}
REASONS={
'iOS physical-device execution only','root required','IOKit unavailable',
'Data is not a separate mounted APFS volume','invalid Data BSD identity','Data IOMedia missing',
'Data volume class/UUID unavailable','unexpected APFS parent chain','physical-store name unavailable',
'physical store does not belong to NativeRamBlock','cannot inspect raw Data store',
'Data geometry or APFS superblock check failed','growth guards refused; no resize attempted',
'APFS sizing API returned implausible limits','prior or unavailable operation journal',
'operation journal not durable',
'live Data snapshot unavailable or inconsistent','mounted Data has not acquired expanded capacity',
'Data identity or capacity changed before journal','Data identity or capacity changed before resize',
'APFS live-space or resize API unavailable',
*{name+' unavailable' for name in ('IOBSDNameMatching','IOServiceGetMatchingService',
'IORegistryEntryGetParentIterator','IOIteratorNext','IOObjectRelease','IOObjectConformsTo','IORegistryEntryCreateCFProperty','IORegistryEntryGetRegistryEntryID')}}
NUMBERS={'physical_bytes','container_bytes_before','authorized_bytes','free_bytes_before',
'decision','minimum_status','minimum_bytes','resize_status','container_bytes_after','free_bytes_after',
'observation_stage','observation_status'}
KEYS={'format','resize_called','changes_gpt','exit_status','status','reason','volume','volume_uuid',
'physical_store','container_media','resize_api_available'}|NUMBERS

def clean_report(r):
    if not isinstance(r,dict) or not set(r)<=KEYS:return None
    if type(r.get('format')) is not int or r['format']!=1 or r.get('changes_gpt') is not False:return None
    if type(r.get('resize_called')) is not bool or type(r.get('exit_status')) is not int or r['exit_status'] not in (0,2,3):return None
    if r.get('status') not in STATUS:return None
    if 'reason' in r and r['reason'] not in REASONS:return None
    if r['status']=='refused' and 'reason' not in r:return None
    for k,v in r.items():
        if k in NUMBERS and (type(v) is not int or not -(1<<63)<=v<(1<<64)):return None
        if k in ('volume','physical_store','container_media') and (not isinstance(v,str) or not re.fullmatch(r'disk\d+(?:s\d+)*',v) or len(v)>24):return None
        if k=='volume_uuid' and (not isinstance(v,str) or not re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}',v)):return None
        if k=='resize_api_available' and type(v) is not bool:return None
    return r

def candidates(raw):
    # Only parse small, flat JSON objects. No raw snippets ever leave memory.
    for m in re.finditer(rb'\{[^{}\x00]{0,4094}\}',raw):
        b=m.group()
        if b'"resize_called"' not in b:continue
        try:r=json.loads(b)
        except (ValueError,UnicodeDecodeError):continue
        r=clean_report(r)
        if r is not None:yield m.start(),r

def capture(device,deployment,out):
    out=Path(out);data.require(not out.exists(),'Output already exists')
    original=data.geometry(deployment);seed=data.seed_identity(deployment)
    layout,gpt=device.layout();data.require(layout==deployment['layout'],'GPT differs from deployment')
    first,pages,growth_first,growth_marker=data.selected(device,deployment,original)
    bb=pages//32768;marker=device.read(first,1);header=device.read(first+1,1);bitmap=device.read(first+2,bb)
    data.validate(marker,header,bitmap,first,seed,pages)
    count=sum(b.bit_count() for b in bitmap);done=0;found={};tail=b'';last_end=-1
    print(f'Reading {count*4096//1048576} MiB of allocated overlay pages; phone writes: 0; raw pages will NOT be saved.',flush=True)
    i=0
    while i<pages:
        if not (bitmap[i>>3]>>(i&7)&1):i+=1;continue
        n=1
        while n<128 and i+n<pages and bitmap[(i+n)>>3]>>((i+n)&7)&1:n+=1
        raw=device.read(first+2+bb+i,n);data.require(len(raw)==n*4096,'Short Data read')
        if i*4096!=last_end:tail=b''
        combined=tail+raw;base=i*4096-len(tail)
        for at,r in candidates(combined):
            canonical=json.dumps(r,sort_keys=True).encode();digest=hashlib.sha256(canonical).hexdigest()
            if digest not in found:
                data.require(len(found)<64,'Too many report candidates; no output written')
                found[digest]=dict(report=r,logical_offsets=[],sha256=digest)
            offset=base+at;locations=found[digest]['logical_offsets']
            if offset not in locations and len(locations)<16:locations.append(offset)
        tail=combined[-4095:];last_end=(i+n)*4096;i+=n;done+=n
        if done//8192!=(done-n)//8192:print(f'Read {done*4096//1048576} / {count*4096//1048576} MiB; reports {len(found)}',flush=True)
    data.require(device.read(first,1)==marker and device.read(first+1,1)==header and
                 device.read(first+2,bb)==bitmap,'Data metadata changed; no output written')
    data.require(growth_first is None or device.read(growth_first,1)==growth_marker,'Data selection changed; no output written')
    data.require(device.layout()==(layout,gpt) and done==count,'Incomplete or changed scan; no output written')
    report=dict(format=1,read_only=True,device_writes=0,raw_data_exported=False,complete=True,
        logical_bytes=pages*4096,present_pages=count,report_candidates=len(found),
        freshness='Content matches only: may be stale or deleted. No candidate does not prove helper absence.',
        captured_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED) as z:
        z.writestr('scan-report.json',json.dumps(report,indent=2))
        z.writestr('helper-report-candidates.json',json.dumps(list(found.values()),indent=2))
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--deployment',type=Path,default=Path(__file__).with_name('deployment.json'))
    p.add_argument('--seed-contract',type=Path,default=Path(__file__).with_name('data-seed.json'))
    p.add_argument('--adb',default='adb');p.add_argument('--out',type=Path)
    a=p.parse_args();adb=shutil.which(a.adb);data.require(adb,'adb not found in PATH')
    out=a.out or Path('myron-growth-report-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
    print('SEND THIS SMALL ZIP:',capture(data.log.Recovery(adb),data.load_deployment(a.deployment,a.seed_contract),out).resolve())

if __name__=='__main__':main()
