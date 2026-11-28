#!/usr/bin/env python3
"""Read generated sidecars back independently; no device access or build."""
import argparse,json,struct,sys,unittest,zipfile,zlib
from pathlib import Path
from prepare_metal_sidecars import modules,owner_trust,addon,ORIGINAL_SHA,COMPONENT,DATA_HELPER,DATA_CACHE,data_helper
from data_launch_cache import load_archive
from audit_userspace_artifact import sha,image
p=argparse.ArgumentParser();p.add_argument('--artifact',type=Path,required=True)
p.add_argument('--data-helper',type=Path,required=True)
p.add_argument('--service-cache',type=Path,required=True)
p.add_argument('--original-trust',type=Path,required=True);p.add_argument('--sidecars',type=Path,required=True)
a,rest=p.parse_known_args()

class Sidecars(unittest.TestCase):
 def test_actual_plugin_signature_addon_and_owner_cache(self):
  original=a.original_trust.read_bytes();self.assertEqual(sha(original),ORIGINAL_SHA)
  report=json.loads((a.sidecars/'metal-sidecars.json').read_text())
  self.assertEqual(sha(a.artifact.read_bytes()),COMPONENT['artifact_sha256'])
  self.assertFalse(report['installed']);self.assertFalse(report['data_seed_modified'])
  with zipfile.ZipFile(a.artifact) as z:
   prefix='build/adreno-metal-plugin27/NativeAdrenoMetal.bundle/'
   special={1:z.read(prefix+'Info.plist'),3:z.read(prefix+'_CodeSignature/CodeResources')}
   helper_files=data_helper(a.data_helper)
   helper_files.update(load_archive(a.service_cache,DATA_CACHE))
   hashes=[bytes.fromhex(DATA_HELPER['cdhash'])]
   for name,kind in [('NativeAdrenoMetal',8),('libvulkan_freedreno.dylib',6)]:
    hashes.append(bytes.fromhex(image(z.read(prefix+name),kind,special if kind==8 else {})['cdhash']))
   raw=(a.sidecars/'kernel.macho.trustcache').read_bytes();blocks=modules(raw)
   self.assertEqual(blocks[1:],modules(original));self.assertEqual(len(blocks),3)
   self.assertEqual(blocks[0][24:],b''.join(x+b'\x02\x00\x00\x00' for x in sorted(hashes)))
   raw=(a.sidecars/'gpuaddon.bin').read_bytes();magic,count,reserved,total=struct.unpack_from('<8sIIQ',raw)
   self.assertEqual((magic,count,reserved,total),(b'NGPUADD2',9,0,len(raw)))
   cursor=24;seen=set()
   for _ in range(count):
    plen,mode,size,n=struct.unpack_from('<IIQQ',raw,cursor);cursor+=24
    name=raw[cursor:cursor+plen-1].decode();self.assertEqual(raw[cursor+plen-1],0)
    cursor+=(plen+7)&~7;data=zlib.decompress(raw[cursor:cursor+n]);cursor+=(n+7)&~7
    self.assertEqual(len(data),size);self.assertNotIn(name,seen);seen.add(name)
    if name=='addons/NativeAdrenoMetal.publish':self.assertEqual((mode,data),(0o644,b'1\n'))
    elif name in helper_files:self.assertEqual((mode,data),helper_files[name])
    else:self.assertEqual(data,z.read('build/adreno-metal-plugin27/'+name.removeprefix('addons/')))
    self.assertEqual(sha(data),report['addon_files'][name]['sha256'])
   self.assertEqual(cursor,len(raw));self.assertEqual(seen,set(report['addon_files']))
  for name,r in report['outputs'].items():
   raw=(a.sidecars/name).read_bytes();self.assertEqual((len(raw),sha(raw)),(r['bytes'],r['sha256']))
 def test_wrong_original_and_missing_or_duplicate_hash_rejected(self):
  raw=a.original_trust.read_bytes();changed=bytearray(raw);changed[-1]^=1
  for data,hashes in [(bytes(changed),['11'*20,'22'*20]),(raw,['11'*20]),(raw,['11'*20]*2)]:
   with self.assertRaises(ValueError):owner_trust(data,hashes)
 def test_corrupted_bundle_order_offsets_and_uuid_rejected(self):
  raw=(a.sidecars/'kernel.macho.trustcache').read_bytes();start=struct.unpack_from('<I',raw,4)[0]
  cases=[]
  b=bytearray(raw);struct.pack_into('<I',b,4,8);cases.append(b)
  b=bytearray(raw);b[start+4:start+20]=bytes(16);cases.append(b)
  b=bytearray(raw);b[start+24:start+48],b[start+48:start+72]=b[start+48:start+72],b[start+24:start+48];cases.append(b)
  b=bytearray(raw);b[start+44]=0;cases.append(b)
  for bad in cases:
   with self.assertRaises(ValueError):modules(bytes(bad))
 def test_invalid_addon_paths_and_modes_rejected(self):
  for path,mode in [('addons/../etc/passwd',0o644),('/addons/x',0o644),('addons/x',0o777),('addons/a\0b',0o644)]:
   with self.assertRaises(ValueError):addon({path:(mode,b'x')})

if __name__=='__main__':unittest.main(argv=[sys.argv[0],*rest])
