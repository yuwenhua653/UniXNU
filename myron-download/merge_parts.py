#!/usr/bin/env python3
"""Join raw parts or GitHub artifact ZIP wrappers; preserve the original ZIP."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

NAME='myron-ios27-device-root-package.zip'
SIZE=10356020059
SHA='5147cdae6353d979ff5dcb3472cd9a71cbce3399aaf0119dc4e87b2ea87d34b0'
PART_BYTES=450*1024**2
COUNT=(SIZE+PART_BYTES-1)//PART_BYTES


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while data:=f.read(8*1024**2):h.update(data)
    return h.hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def merge(directory):
    directory=Path(directory);m=json.loads((directory/'parts.json').read_text(encoding='utf-8'))
    require(m.get('archive')==NAME and m.get('bytes')==SIZE and m.get('sha256')==SHA,'Wrong source package')
    require(len(m['parts'])==COUNT,'Wrong part count')
    for i,row in enumerate(m['parts']):
        require(row['file']==NAME+f'.part{i:02d}' and row['bytes']==min(PART_BYTES,SIZE-i*PART_BYTES),'Wrong part layout')
    final=directory/NAME
    if final.exists():
        require(final.is_file() and final.stat().st_size==SIZE and digest(final)==SHA,'Existing output differs; move it aside first')
        print('Existing original ZIP is already correct.');return final
    sources=[]
    for i,row in enumerate(m['parts']):
        raw=directory/row['file'];wrapped=directory/f'myron-root-part{i:02d}.zip'
        require(raw.is_file() or wrapped.is_file(),'Missing part '+str(i).zfill(2))
        sources.append((raw if raw.is_file() else wrapped,raw.is_file()))
    require(shutil.disk_usage(directory).free>=SIZE+256*1024**2,'Need at least 11 GB free to merge')
    temporary=directory/(NAME+'.merging')
    h=hashlib.sha256();total=0
    try:
        with temporary.open('wb') as dest:
            for i,(row,(path,is_raw)) in enumerate(zip(m['parts'],sources)):
                z=None
                if is_raw:
                    source=path.open('rb')
                else:
                    z=zipfile.ZipFile(path)
                    require(z.namelist()==[row['file']],'Unexpected wrapped part: '+path.name)
                    info=z.getinfo(row['file'])
                    require(info.file_size==row['bytes'] and not info.flag_bits&1,'Wrong wrapped size')
                    source=z.open(row['file'])
                part_hash=hashlib.sha256();size=0
                try:
                    with source:
                        while data:=source.read(8*1024**2):
                            size+=len(data)
                            require(size<=row['bytes'],'Oversized part '+str(i))
                            part_hash.update(data);h.update(data);dest.write(data)
                finally:
                    if z:z.close()
                require(size==row['bytes'] and part_hash.hexdigest()==row['sha256'],'Damaged part '+str(i).zfill(2)+'; download only this part again')
                total+=size;print(f'Part {i+1}/{COUNT} verified; {total/SIZE:.0%}',flush=True)
            require(total==SIZE and h.hexdigest()==SHA,'Merged ZIP differs from original')
            dest.flush();os.fsync(dest.fileno())
        os.replace(temporary,final)
    except BaseException:
        temporary.unlink(missing_ok=True);raise
    print('SUCCESS: original ZIP restored and SHA256 verified. No phone operation performed.')
    return final


if __name__=='__main__':
    try:merge(Path(__file__).resolve().parent)
    except (Exception,KeyboardInterrupt) as e:
        print('STOP:',str(e) or 'Interrupted; downloaded parts are preserved.')
        raise SystemExit(1)
