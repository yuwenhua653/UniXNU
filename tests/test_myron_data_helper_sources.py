import hashlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'myron-gpu'))
from prepare_metal_sidecars import verify_helper_sources
class Tests(unittest.TestCase):
 def test_manifest_tracks_real_sources(self):
  m=json.loads((ROOT/'myron-gpu/data-helper-sources.json').read_text())
  self.assertIn('MyronAPFSTransaction.h',m)
  self.assertIn('myron-data-grow.m',m)
  for name,digest in m.items():
   self.assertEqual(hashlib.sha256((ROOT/'myron-runtime'/name).read_bytes()).hexdigest(),digest)
  verify_helper_sources({'source_sha256':m})
 def test_missing_old_or_extra_source_refused(self):
  m=json.loads((ROOT/'myron-gpu/data-helper-sources.json').read_text())
  for bad in (None,{},dict(m,**{'myron-data-grow.m':'0'*64}),dict(m,extra='1'*64),
              {k:v for k,v in m.items() if k!='MyronAPFSTransaction.h'}):
   with self.assertRaisesRegex(ValueError,'older or unverified'):verify_helper_sources({'source_sha256':bad})
if __name__=='__main__':unittest.main()
