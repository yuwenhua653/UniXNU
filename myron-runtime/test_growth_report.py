#!/usr/bin/env python3
import argparse,ast,importlib.util,json,sys,tempfile,unittest,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--reader-directory',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.reader_directory.resolve()))
import capture_growth_report as m
# Reuse the existing read-only sparse peer, without executing its test runner.
tree=ast.parse((Path(__file__).resolve().parents[1]/'tests/test_myron_data_export.py').read_text())
peer=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Peer')
import struct,zlib
scope=dict(m=m.data,struct=struct,zlib=zlib,SEED='11'*32)
exec(compile(ast.Module(body=[peer],type_ignores=[]),'<sparse peer>','exec'),scope)
Peer=scope['Peer']
GOOD=dict(format=1,changes_gpt=False,resize_called=False,exit_status=2,status='refused',reason='unexpected APFS parent chain')
class Tests(unittest.TestCase):
 def test_live_space_report_fields(self):
  r=dict(GOOD,reason='live Data snapshot unavailable or inconsistent',container_media='disk3',
         observation_stage=10,observation_status=49154)
  self.assertEqual(m.clean_report(r),r)
  self.assertIsNone(m.clean_report(dict(r,container_media='/private/secret')))
  self.assertIsNone(m.clean_report(dict(r,observation_status='private note')))
 def test_only_allowlisted_fields(self):
  self.assertEqual(m.clean_report(GOOD),GOOD)
  for key,value in [('reason','private note'),('status','private note'),('volume','/private/secret'),('extra','private'),('physical_bytes','private'),('resize_called',1),('changes_gpt',True),('exit_status',64),('format',True)]:
   self.assertIsNone(m.clean_report(dict(GOOD,**{key:value})))
 def test_scan_ignores_private_surroundings(self):
  raw=b'private notes'+json.dumps(GOOD).encode()+b'password and unrelated text'
  found=list(m.candidates(raw));self.assertEqual(found,[(13,GOOD)])
  self.assertFalse(list(m.candidates(b'{"private":"secret"}')))
 def scan(self,grown=False,flip=False,chunk_boundary=False,gap=False):
  q=Peer(large=True,grown=grown);q.flip=flip
  q.bitmap[:]=bytes(len(q.bitmap));q.bitmap[0]=3
  offset=128*4096-16 if chunk_boundary else 4080
  if chunk_boundary:
   for i in range(130):q.bitmap[i>>3]|=1<<(i&7)
  payload=b'private notes'+bytes(offset-13)+json.dumps(GOOD).encode()
  payload+=bytes((130 if chunk_boundary else 2)*4096-len(payload))
  if gap:
   q.bitmap[0]=5;payload=payload[:4096]+bytes(4096)+payload[4096:]
  real=q.read
  def read(lba,n):
   start=q.first+2+q.bitmap_blocks
   if lba>=start:
    data=payload[(lba-start)*4096:(lba-start+n)*4096]
    return data
   return real(lba,n)
  q.read=read
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'report.zip'
   if flip:
    with self.assertRaisesRegex(ValueError,'metadata changed'):m.capture(q,q.d,out)
    self.assertFalse(out.exists());return
   m.capture(q,q.d,out)
   with zipfile.ZipFile(out) as z:
    self.assertEqual(set(z.namelist()),{'scan-report.json','helper-report-candidates.json'})
    b=z.read('helper-report-candidates.json');self.assertNotIn(b'private notes',b)
    rows=json.loads(b)
    if gap:self.assertEqual(rows,[]);return
    self.assertEqual(len(rows),1);self.assertEqual(rows[0]['report'],GOOD)
    self.assertEqual(rows[0]['logical_offsets'],[offset])
    self.assertEqual(json.loads(z.read('scan-report.json'))['logical_bytes'],(16 if grown else 1)<<30)
 def test_original(self):self.scan()
 def test_grown(self):self.scan(grown=True)
 def test_changed_metadata(self):self.scan(flip=True)
 def test_chunk_boundary(self):self.scan(chunk_boundary=True)
 def test_never_join_unallocated_gap(self):self.scan(gap=True)
if __name__=='__main__':unittest.main(argv=[sys.argv[0]])
