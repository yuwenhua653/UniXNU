#!/usr/bin/env python3
"""Fetch pinned full-OTA operations and extract exactly four verified A840 files.

Partial images are scratch extraction containers, never flashable images.
No boot/vendor/system partition is exported. Whole-OTA authenticity is not claimed.
"""
import argparse, concurrent.futures, hashlib, json, lzma, bz2, os, subprocess, time, urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent

def require(ok,why):
    if not ok:raise ValueError(why)

def fetch(plan,op):
    start=op['offset'];size=op['bytes']
    url=plan['url']+f'?offset={start}&length={size}'
    for attempt in range(3):
        try:
            request=urllib.request.Request(url,headers={'Range':f'bytes={start}-{start+size-1}','User-Agent':'myron-a840-firmware/1'})
            with urllib.request.urlopen(request,timeout=50) as response:
                require(response.status==206,'Server did not honor bounded range')
                data=response.read(size+1)
            require(len(data)==size and hashlib.sha256(data).hexdigest()==op['sha256'],'OTA operation hash mismatch')
            raw=data if op['type']==0 else bz2.decompress(data) if op['type']==1 else lzma.decompress(data)
            require(len(raw)==sum(n for _,n in op['spans']),'OTA operation expansion mismatch')
            return op,raw
        except Exception:
            if attempt==2:raise
            time.sleep(attempt+1)

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--scratch',type=Path,required=True)
    p.add_argument('--dump-erofs',default='dump.erofs');a=p.parse_args()
    plan=json.loads((HERE/'firmware-ota-ranges.json').read_text());pins=json.loads((HERE/'firmware-3.0.306.json').read_text())['files']
    a.output.mkdir(parents=True,exist_ok=True);a.scratch.mkdir(parents=True,exist_ok=True)
    images={}
    for part,entry in plan['partitions'].items():
        image=a.scratch/(part+'.partial.img');images[part]=image
        with image.open('wb') as f:f.truncate(entry['image_bytes'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for op,raw in pool.map(lambda o:fetch(plan,o),entry['operations']):
                at=0
                with image.open('r+b') as f:
                    for off,n in op['spans']:
                        require(0<=off<=entry['image_bytes']-n,'Out-of-image extent')
                        require(os.pwrite(f.fileno(),raw[at:at+n],off)==n,'Short extraction write');at+=n
    for name,row in plan['files'].items():
        raw=subprocess.check_output([a.dump_erofs,'--cat','--nid='+str(row['nid']),str(images[row['partition']])])
        pin=pins[name]
        require(len(raw)==pin['bytes'] and hashlib.sha256(raw).hexdigest()==pin['sha256'],'Extracted firmware mismatch: '+name)
        (a.output/name).write_bytes(raw);print('Verified',name,pin['sha256'],flush=True)
    (a.output/'provenance.json').write_text(json.dumps(dict(android_build='OS3.0.306.0.WPMCNXM',files=pins,
        ota_ranges_sha256=hashlib.sha256((HERE/'firmware-ota-ranges.json').read_bytes()).hexdigest(),whole_ota_verified=False),indent=2)+'\n')

if __name__=='__main__':main()
