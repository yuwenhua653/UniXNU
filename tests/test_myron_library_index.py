import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('index',Path(__file__).resolve().parents[1]/'myron27-library-index.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Cache:
 region_start=0x180000000;max_slide=0x10000000
 images=[dict(path='/usr/lib/system/libsystem_c.dylib',uuid='fixture',address=0x180001000,size=4096),
         dict(path='/System/Library/PrivateFrameworks/Other.framework/Other',uuid='other',address=0x180002000,size=4096)]
 def macho(self,image):return dict(starts=[image['address']],symbol_warnings=[])
 def symbols(self,image,strict):return [(image['address'],'_abort','fixture')]
class IndexTests(unittest.TestCase):
 def test_scope_excludes_unrelated_usr_libraries(self):
  self.assertTrue(m.selected('/usr/lib/system/libsystem_kernel.dylib'))
  self.assertTrue(m.selected('/usr/lib/libobjc.A.dylib'))
  self.assertFalse(m.selected('/usr/lib/swift/libswiftCore.dylib'))
  self.assertFalse(m.selected('/usr/lib/libUnrelated.dylib'))
 def test_duplicate_and_redacted_symbols_keep_function_starts(self):
  c=Cache();a=c.images[0]['address']
  c.symbols=lambda image,strict:[(a,'_abort','export'),(a,'_abort','local'),(a,'<redacted>','local')]
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.json';m.write_index(c,p);x=json.loads(p.read_text())['selected'][0]
  self.assertEqual(x['symbols'],[[a,'_abort','export']]);self.assertEqual(x['starts'],[a])
 def test_only_selected_symbols_and_all_image_ranges(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'index.json';r=m.write_index(Cache(),p);x=json.loads(p.read_text())
   self.assertEqual(r['indexed'],1);self.assertEqual(len(x['images']),2)
   self.assertFalse(x['runtime_observation']);self.assertEqual(x['selected'][0]['symbols'][0][1],'_abort')
 def test_limit_fails_without_partial_output(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'index.json';old=m.MAX_BYTES;m.MAX_BYTES=1
   try:
    with self.assertRaises(ValueError):m.write_index(Cache(),p)
    self.assertFalse(p.exists())
   finally:m.MAX_BYTES=old
 def test_named_diagnostic_is_bounded_and_deduplicated(self):
  c=Cache();c.symbols=lambda image,strict:[(image['address'],'_os_lockdown_mode_enabled','a'),(image['address'],'_os_lockdown_mode_enabled','b')]
  calls=[];c.describe=lambda address,window:calls.append((address,window)) or {'address':address}
  with tempfile.TemporaryDirectory() as d:m.write_index(c,Path(d)/'x.json')
  self.assertEqual(calls,[(c.images[0]['address'],128)])
if __name__=='__main__':unittest.main()
