#!/usr/bin/env python3
"""Stage audited iPhone27 Metal addon/owner trust without changing Data or boot.

Inputs are local verified artifacts. Output is NOT a flashable image. The
loader/install/capacity integration must separately qualify before enabling
myron-gpu-metal=1. Original Apple modules and signed plugin bytes stay exact.
"""
import argparse, hashlib, json, os, plistlib, struct, uuid, zipfile, zlib
from pathlib import Path
from audit_userspace_artifact import audit, image, require, sha
ORIGINAL_SHA = '095605d6abf4e82545579930d54a3476dfac35f754c504f87b456daa058cb9d4'
ORIGINAL_MODULES = (
 '3d81f304c3bc3c05ed32e729b64788ba245f69302ff6ede8c1272a38a7136ec5',
 '4a9332cd17629a94587fe3899157a397b4b9e0a48adad88f8bdf4b293a953ae9',
)
# Already compiled arm64e iOS27 component; no new component build is triggered.
COMPONENT = dict(run=45925023720,commit='80b1c03cfa826cc34f8e06b93d7bebd4eae40f82',
 artifact_sha256='14f73775ea5109f39d8a94837999ddc79ddb46bc76b1b2e87b47e691a1e12549')
DATA_HELPER = dict(run=46101684719,commit='dd3f5dd812780b7f748e10d3ebe025841087898c',
 artifact_sha256='94b355b6813acfe60c95e8028fcf49788b0db4cbe311c3573e51deaaa31b2eeb',
 binary_sha256='ef3d5cacb0b4d81aca3ff19bbb5e0e038a2303ac61429b32a96d74779867d148',
 cdhash='43f44f5c45a8a3e143166bb20042a28b526bc346',
 earlyboot_sha256='5fca4eb0f70b6915c51bedf01fad094c6f79ff1d65d401d9088a10c654a5cb0e',
 earlyboot_cdhash='51cce781ca983db76dd990f7cab5ede0dc7ff13b')


def verify_helper_sources(report):
 expected=json.loads(Path(__file__).with_name('data-helper-sources.json').read_text())
 require(isinstance(report,dict) and report.get('source_sha256')==expected,
         'Data helper contains older or unverified expansion sources; repair startup and rebuild the helper before packaging')

def data_helper(archive):
 raw=Path(archive).read_bytes()
 require(sha(raw)==DATA_HELPER['artifact_sha256'],'Wrong Data helper artifact')
 with zipfile.ZipFile(archive) as z:
  require(set(z.namelist())=={'myron-data-grow','HorizonSetup','build.json','entitlements.plist','earlyboot-entitlements.plist','host-checks.json'},'Data helper inventory')
  verify_helper_sources(json.loads(z.read('build.json')))
  binary=z.read('myron-data-grow');report=image(binary,2,{})
  require(report['sha256']==DATA_HELPER['binary_sha256'] and report['cdhash']==DATA_HELPER['cdhash'],'Data helper signature identity')
  early=z.read('HorizonSetup')
  ent={k:True for k in ('platform-application','com.apple.private.security.no-container',
                      'com.apple.private.security.no-sandbox')}
  early_report=image(early,2,{},identifier='com.apple.HorizonSetup',entitlements=ent)
  require(early_report['sha256']==DATA_HELPER['earlyboot_sha256'] and
          early_report['cdhash']==DATA_HELPER['earlyboot_cdhash'],'Early adapter signature identity')
 return {'addons/myron-data-grow':(0o755,binary),
         'addons/myron-data-earlyboot/HorizonSetup':(0o755,early)}



def modules(data):
 require(len(data)>=8,'Short trust bundle')
 count=struct.unpack_from('<I',data)[0]
 require(0<count<=128 and 4+count*4<=len(data),'Trust bundle count')
 offsets=struct.unpack_from('<'+str(count)+'I',data,4)
 require(offsets[0]==4+4*count and all(a<b for a,b in zip(offsets,offsets[1:])),'Trust offsets')
 out=[]
 for start,end in zip(offsets,(*offsets[1:],len(data))):
  require(start%4==0 and end<=len(data) and end-start>=24,'Trust module bounds')
  block=data[start:end];version,ident,n=struct.unpack_from('<I16sI',block)
  require(version==2 and any(ident) and len(block)==24+24*n,'Trust module shape')
  hashes=[]
  for at in range(24,len(block),24):
   h=block[at:at+20]
   require(1<=block[at+20]<=4 and (not hashes or hashes[-1]<h),'Trust entry order/type')
   hashes.append(h)
  out.append(block)
 require(len({x[4:20] for x in out})==len(out),'Trust UUID collision')
 return out


def owner_trust(original,cdhashes):
 require(sha(original)==ORIGINAL_SHA,'Wrong iPhone12,1/24A446 original trust bundle')
 old=modules(original)
 require(tuple(map(sha,old))==ORIGINAL_MODULES,'Changed original Apple trust modules')
 hashes=sorted(bytes.fromhex(x) for x in cdhashes)
 require(len(hashes)==4 and len(set(hashes))==4 and all(len(x)==20 for x in hashes) and
         bytes.fromhex(DATA_HELPER['cdhash']) in hashes and bytes.fromhex(DATA_HELPER['earlyboot_cdhash']) in hashes,
         'Plugin, Turnip, Data helper and early adapter CDHashes required')
 ident=uuid.uuid5(uuid.NAMESPACE_URL,'org.unixnu.myron.24A446.metal:'+''.join(x.hex() for x in hashes))
 own=struct.pack('<I16sI',2,ident.bytes,len(hashes))+b''.join(x+bytes([2,0,0,0]) for x in hashes)
 blocks=[own,*old];cursor=4+4*len(blocks);offsets=[]
 for block in blocks: offsets.append(cursor);cursor+=len(block)
 out=struct.pack('<I',len(blocks))+struct.pack('<3I',*offsets)+b''.join(blocks)
 require(modules(out)[1:]==old,'Original trust preservation failed')
 return out


def addon(files):
 pad=lambda x:x+bytes(-len(x)%8)
 body=b''
 require(bool(files) and len(files)<=4096,'Addon count')
 for name,(mode,data) in sorted(files.items()):
  path=name.encode()+b'\0'
  require(1<len(path)<=160 and '\0' not in name and name.startswith('addons/') and
          all(p not in ('','.','..') for p in name.split('/')) and mode in (0o644,0o755),'Addon path/mode')
  packed=zlib.compress(data,9)
  body+=struct.pack('<IIQQ',len(path),mode,len(data),len(packed))+pad(path)+pad(packed)
 return b'NGPUADD2'+struct.pack('<IIQ',len(files),0,24+len(body))+body


def prepare(archive,original_path,out,helper_archive=None):
 report=audit(archive,COMPONENT['artifact_sha256'])
 original=original_path.read_bytes()
 helper_archive=helper_archive or os.environ.get('MYRON_DATA_HELPER_ARTIFACT')
 require(bool(helper_archive),'Pinned Data helper artifact required')
 helper_files=data_helper(helper_archive)
 hashes=[x['cdhash'] for x in report['images'].values()]+[DATA_HELPER['cdhash'],DATA_HELPER['earlyboot_cdhash']]
 trust=owner_trust(original,hashes)
 files={}
 with zipfile.ZipFile(archive) as z:
  base='build/adreno-metal-plugin27/'
  for path,digest in report['addon_files'].items():
   raw=z.read(base+path.removeprefix('addons/'))
   require(sha(raw)==digest,'Component changed after audit')
   files[path]=(0o755 if path.split('/')[-1] in report['images'] else 0o644,raw)
 require(len(files)==5,'Unexpected component bundle')
 # Publication marker is outside the sealed bundle; code signatures unchanged.
 files['addons/NativeAdrenoMetal.publish']=(0o644,b'1\n')
 files.update(helper_files)
 blob=addon(files)
 result=dict(format=1,target='iPhone12,1/24A446',component=COMPONENT,
  images=report['images'],original_trust_sha256=ORIGINAL_SHA,
  original_modules=list(ORIGINAL_MODULES),original_modules_unchanged=True,
  owner_cdhashes=sorted(hashes),data_helper=DATA_HELPER,
  data_helper_sources_sha256=sha(Path(__file__).with_name('data-helper-sources.json').read_bytes()),
  earlyboot_task='restore-datapartition',earlyboot_program='/usr/libexec/HorizonSetup',
  service_cache_modified=False,
  outputs={'gpuaddon.bin':dict(bytes=len(blob),sha256=sha(blob)),
           'kernel.macho.trustcache':dict(bytes=len(trust),sha256=sha(trust))},
  addon_files={p:dict(mode=mode,bytes=len(raw),sha256=sha(raw)) for p,(mode,raw) in files.items()},
  required_plugin_name='NativeAdrenoMetal',required_plugin_class='NativeAdrenoMetalDevice',
  probe_daemon_installed=False,data_seed_modified=False,
  installed=False,boot_capacity_qualified=False,hardware_tested=False,flashable=False)
 out.mkdir(parents=True,exist_ok=False)
 (out/'gpuaddon.bin').write_bytes(blob);(out/'kernel.macho.trustcache').write_bytes(trust)
 (out/'metal-sidecars.json').write_text(json.dumps(result,indent=2)+'\n')
 return result


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--artifact',type=Path,required=True);p.add_argument('--original-trust',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True);p.add_argument('--data-helper',type=Path)
 a=p.parse_args()
 r=prepare(a.artifact,a.original_trust,a.out,a.data_helper)
 print('PASS: unchanged signed plugin/Turnip, publication marker and owner trust; not installed or flashable')
 print(json.dumps(r['outputs'],indent=2))
