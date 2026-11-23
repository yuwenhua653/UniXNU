#!/usr/bin/env python3
"""Independently check downloaded component bytes; never hardware qualification."""
import argparse, hashlib, json, struct, zlib, zipfile
from pathlib import Path


def require(ok, reason):
    if not ok: raise ValueError(reason)


def sha(data): return hashlib.sha256(data).hexdigest()


def image(data, kind, special):
    require(len(data)>=32,'short Mach-O')
    magic,cpu,subtype,actual,ncmd,size=struct.unpack_from('<6I',data)
    require((magic,cpu,subtype&0xffffff,actual)==(0xfeedfacf,0x100000c,2,kind),'wrong arm64e Mach-O type')
    cursor=32; platform=[]; signatures=[]
    require(size<=len(data)-32,'commands out of bounds')
    for _ in range(ncmd):
        require(cursor+8<=32+size,'truncated command')
        cmd,n=struct.unpack_from('<II',data,cursor)
        require(n>=8 and cursor+n<=32+size,'command out of bounds')
        if cmd==0x32:
            require(n>=24,'short build version');platform.append(struct.unpack_from('<II',data,cursor+8))
        if cmd==0x1d:
            require(n==16,'short signature command');signatures.append(struct.unpack_from('<II',data,cursor+8))
        cursor+=n
    require(cursor==32+size and platform==[(2,27<<16)] and len(signatures)==1,'iOS27 target/signature differs')
    offset,length=signatures[0]
    require(offset>=cursor and offset+length<=len(data),'signature out of bounds')
    blob=data[offset:offset+length]
    magic,total,count=struct.unpack_from('>III',blob)
    require(magic==0xfade0cc0 and total<=length and 12+8*count<=total,'invalid signature superblob')
    slots={};ranges=[]
    for i in range(count):
        slot,at=struct.unpack_from('>II',blob,12+8*i)
        require(slot not in slots and at>=12+8*count and at+8<=total,'invalid signature index')
        n=struct.unpack_from('>I',blob,at+4)[0]
        require(n>=8 and at+n<=total and all(at+n<=a or at>=b for a,b in ranges),'overlapping signature blob')
        slots[slot]=blob[at:at+n];ranges.append((at,at+n))
    cd=slots[0]
    magic,n,version,flags,hoff,ident,ns,nc,limit=struct.unpack_from('>9I',cd)
    hsize,htype,_,page=struct.unpack_from('4B',cd,36)
    require(magic==0xfade0c02 and n==len(cd) and flags&2,'not an ad-hoc CodeDirectory')
    require((hsize,htype,page)==(32,2,12) and limit==offset,'unsupported signature coverage')
    require(nc==(limit+4095)//4096 and hoff>=ns*32 and hoff+nc*32<=n,'invalid code hash table')
    for i in range(nc):
        require(hashlib.sha256(data[i*4096:min((i+1)*4096,limit)]).digest()==cd[hoff+i*32:hoff+(i+1)*32],f'code page {i} mismatch')
    for i in range(1,ns+1):
        digest=cd[hoff-i*32:hoff-(i-1)*32]
        source=special.get(i,slots.get(i))
        if digest==bytes(32):continue
        require(source is not None and hashlib.sha256(source).digest()==digest,f'special slot {i} mismatch')
    return dict(sha256=sha(data),bytes=len(data),cdhash=sha(cd)[:40],pages=nc,
                arm64e=True,platform='iOS',minimum_os='27.0')


def audit(archive, expected_sha):
    require(sha(archive.read_bytes())==expected_sha,'Actions artifact SHA-256 mismatch')
    with zipfile.ZipFile(archive) as z:
        require(len(z.namelist())==len(set(z.namelist())),'duplicate ZIP members')
        base='build/adreno-metal-plugin27/'
        read=lambda n:z.read(base+n)
        report=json.loads(read('myron-userspace-build.json'))
        require(report['target']=='iPhone12,1/24A446' and report['compiled'],'wrong build target')
        for key in ('installed','hardware_tested','accelerator_published','original_trust_bundle_merged','data_seed_modified'):
            require(report[key] is False,'unexpected enabled state: '+key)
        manifest=z.read('userspace-source.json')
        require(manifest==read('myron-userspace-source.json') and sha(manifest)==report['source_manifest_sha256'],'source manifest mismatch')
        trust=json.loads(read('trust.json')); bundle='NativeAdrenoMetal.bundle/'
        special={1:read(bundle+'Info.plist'),3:read(bundle+'_CodeSignature/CodeResources')}
        images={}
        for name,kind,key in [('NativeAdrenoMetal',8,'cdhash'),('libvulkan_freedreno.dylib',6,'turnip_cdhash')]:
            result=image(read(bundle+name),kind,special if kind==8 else {})
            require(all(result[k]==v for k,v in report['images'][name].items()),'build report differs: '+name)
            require(result['cdhash']==trust[key],'trust CDHash differs: '+name)
            images[name]=result
        daemon=image(read('adrenoprobed'),2,{})
        require(daemon['cdhash']==trust['daemon_cdhash'],'daemon CDHash differs')
        data=read('gpuaddon-candidate.bin')
        require(sha(data)==report['addon_sha256'] and len(data)==report['addon_bytes'],'addon digest differs')
        magic,count,reserved,total=struct.unpack_from('<8sIIQ',data)
        require(magic==b'NGPUADD2' and reserved==0 and total==len(data),'invalid addon header')
        cursor=24;files={}
        for _ in range(count):
            require(cursor+24<=len(data),'short addon record')
            plen,mode,size,packed=struct.unpack_from('<IIQQ',data,cursor);cursor+=24
            require(1<plen<=160 and cursor+plen<=len(data),'invalid addon path length')
            path=data[cursor:cursor+plen];cursor+=(plen+7)&~7
            require(path[-1]==0 and b'\0' not in path[:-1],'invalid addon path')
            name=path[:-1].decode()
            require(name not in files and name.startswith('addons/'+bundle) and '..' not in name.split('/'),'unexpected addon entry')
            require(cursor+packed<=len(data),'short addon stream')
            stream=zlib.decompressobj();raw=stream.decompress(data[cursor:cursor+packed],size+1)
            require(stream.eof and not stream.unused_data and len(raw)==size,'invalid addon content')
            require(raw==read(name.removeprefix('addons/')),'addon/source byte mismatch')
            require(mode==(0o755 if name.split('/')[-1] in images else 0o644),'addon mode mismatch')
            files[name]=sha(raw);cursor+=(packed+7)&~7
        expected={n.removeprefix(base) for n in z.namelist() if n.startswith(base+bundle) and not n.endswith('/')}
        require(cursor==len(data) and {n.removeprefix('addons/') for n in files}==expected,'addon files differ')
    return dict(artifact_sha256=expected_sha,target=report['target'],images=images,
                daemon=daemon,addon_sha256=report['addon_sha256'],addon_bytes=len(data),addon_files=files,
                host_verified=True,hardware_tested=False,flashable=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path);p.add_argument('--sha256',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=audit(a.archive,a.sha256)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: artifact, iOS27 Mach-O, all 4K code/signature slots, CDHashes and exact addon bytes')
