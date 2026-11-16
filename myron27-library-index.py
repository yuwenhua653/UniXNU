#!/usr/bin/env python3
"""Export a bounded static symbol index from the pinned original SystemOS.

No device addresses or user captures are inputs. Original images stay private.
The index is reusable for offline attribution without recompiling the kernel.
"""
import argparse,importlib.util,json,os,shutil,subprocess,sys,tomllib
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
MAX_BYTES=16*1024*1024
def load(name):
 spec=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/(name+'.py'))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def selected(path):
 return path.startswith('/usr/lib/system/') or path in (
  '/usr/lib/libobjc.A.dylib', '/usr/lib/libc++abi.dylib',
  '/usr/lib/libc++.1.dylib', '/usr/lib/libSystem.B.dylib',
  '/System/Library/Frameworks/Foundation.framework/Foundation',
  '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
def write_index(cache,path):
 result=dict(format=1,target='iPhone12,1/27.0.1/24A446',runtime_observation=False,
  region_start=hex(cache.region_start),max_slide=hex(cache.max_slide),images=cache.images,selected=[])
 for image in cache.images:
  if not selected(image['path']):continue
  meta=cache.macho(image);symbols=[];seen=set()
  for address,name,source in cache.symbols(image,strict=False):
   if name in ('<redacted>','') or (address,name) in seen:continue
   seen.add((address,name));symbols.append((address,name,source))
  row=dict(path=image['path'],uuid=image['uuid'],address=hex(image['address']),size=image['size'],
   starts=meta['starts'],symbols=symbols,warnings=meta.get('symbol_warnings',[]))
  # One named ABI compatibility query, independent of any device observation.
  targets=[address for address,name,_ in symbols if name.lstrip('_')=='os_lockdown_mode_enabled']
  row['lockdown_query']=[cache.describe(address,128) for address in sorted(set(targets))]
  result['selected'].append(row)
 encoded=json.dumps(result,separators=(',',':')).encode()
 if len(encoded)>MAX_BYTES:raise ValueError(f'Symbol index {len(encoded)} bytes exceeds {MAX_BYTES} byte limit')
 Path(path).write_bytes(encoded)
 return dict(images=len(result['images']),indexed=len(result['selected']),bytes=len(encoded))
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ('device','upstream','work','output','archive-tool'):p.add_argument('--'+key,type=Path,required=True)
 a=p.parse_args();work=a.work.resolve();out=a.output.resolve()
 if sys.platform!='darwin' or os.geteuid()!=0:raise ValueError('Requires read-only macOS image inspection')
 if work.exists() or out.exists():raise ValueError('Require fresh directories')
 work.mkdir(parents=True,mode=0o700);out.mkdir(parents=True)
 extract=load('myron27-fault-extract');symbolicate=load('myron27-fault-symbolicate')
 sys.path[:0]=[str(a.device.resolve()),str(a.upstream.resolve()/'scripts')]
 import prepare_userland
 import prepare_data_volume as volume
 from unixnu.ipsw import Ipsw
 from unixnu import userdata
 require=extract.require
 require(subprocess.check_output(['git','-C',str(a.upstream),'rev-parse','HEAD'],text=True).strip()==extract.UPSTREAM,'Wrong helper revision')
 require(shutil.disk_usage(work).free>11*1024**3,'Insufficient temporary space')
 config=tomllib.loads((a.device/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1/profile.toml').read_text())
 source=Ipsw(SimpleNamespace(board=config,out_root=work),config['ipsw']['url'])
 try:
  prepare_userland.validate_manifest(source)
  require(source.info('Cryptex1,SystemOS')[:2]==extract.MEMBER,'Wrong source image')
  print('Downloading pinned original SystemOS; no kernel build',flush=True)
  encrypted=source.extract('Cryptex1,SystemOS')
  require(encrypted.stat().st_size==extract.MEMBER[1],'Truncated image')
 finally:
  source.zip.close();source.stream.close()
 dest=work/'decoded';dest.mkdir()
 decoded=subprocess.run([str(a.archive_tool),'fw','aea',str(encrypted),'--output',str(dest)],capture_output=True)
 require(decoded.returncode==0,'Image decode failed; private output withheld')
 image=volume.regular(dest/Path(extract.MEMBER[0]).with_suffix('').name)
 raw=extract.check_raw_image(image,userdata)
 print('PASS original raw volume identity; indexing libraries',flush=True)
 with volume.attached(image,work/'mount',True) as mounted:
  require(mounted['uuid']==extract.SYSTEMOS[0],'Wrong original volume UUID')
  with symbolicate.CacheSet(mounted['path']/'System/Library/Caches/com.apple.dyld') as cache:
   summary=write_index(cache,out/'library-index.json')
 summary.update(result='passed',source_volume=raw,kernel_built=False,phone_accessed=False,
  original_files_modified=False,source_commit=os.environ.get('GITHUB_SHA','unknown'))
 (out/'index-report.json').write_text(json.dumps(summary,indent=2)+'\n')
 print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
