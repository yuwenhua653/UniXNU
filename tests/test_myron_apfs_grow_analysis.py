import importlib.util,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('growth_analysis',Path(__file__).resolve().parents[1]/'myron27-apfs-grow-analysis.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Cache:
 images=[dict(path=m.APFS,uuid='fixture',address=0x1000,size=0x1000)]
 def macho(self,image):return dict(starts=[0x1000,0x1004,0x1008],symbol_warnings=[])
 def symbols(self,image,strict=False):return [(0x1000,'_APFSContainerResize','export'),(0x1004,'_APFSContainerGetMinimalSize','export')]
 def read(self,a,n,executable=False):return bytes.fromhex('c0035fd6')*(n//4),None
 def image_for(self,a):return self.images[0]
class Tests(unittest.TestCase):
 def test_boot_slot_distinguishes_absence_and_symlink(self):
  config=[dict(value={'Boot':{'restore-datapartition':{'Program':'/usr/libexec/HorizonSetup','RequireSuccess':True}}})]
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'usr/libexec').mkdir(parents=True)
   self.assertEqual(m.early_boot_slot(p,config)['path_kind'],'absent')
   target=p/'usr/libexec/HorizonSetup';target.symlink_to('missing')
   self.assertEqual(m.early_boot_slot(p,config)['path_kind'],'symlink')
   target.unlink();target.write_text('fixture')
   self.assertEqual(m.early_boot_slot(p,config)['path_kind'],'regular')
   self.assertEqual(target.read_text(),'fixture')
   with self.assertRaisesRegex(ValueError,'Ambiguous'):m.early_boot_slot(p,config*2)
 def test_embedded_xml_parsed_not_text_grep(self):
  import plistlib
  x=plistlib.dumps({'LaunchDaemons':['/fixture/jobs']});r=m.embedded_plists(b'prefix\0'+x+b'\0suffix')
  self.assertEqual(len(r),1);self.assertEqual(r[0]['value']['LaunchDaemons'],['/fixture/jobs'])
  self.assertEqual(m.embedded_plists(b'<?xml invalid</plist>'),[])
 def test_api_boundaries_and_no_mutation_claim(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'x.json';m.write_cache(Cache(),out,SimpleNamespace(setup_method_flow=lambda *a,**kw:[]));r=json.loads(out.read_text())
   self.assertEqual(len(r['functions']),2);self.assertFalse(r['resize_called']);self.assertFalse(r['phone_accessed'])
   self.assertNotIn('bytes',r['functions'][0]['instructions'][0])
 def test_missing_ambiguous_or_unbounded_entry_refused(self):
  for kind in ('missing','duplicate','boundary'):
   c=Cache()
   if kind=='missing':c.symbols=lambda *a,**kw:[]
   if kind=='duplicate':c.symbols=lambda *a,**kw:[(0x1000,'_APFSContainerResize','export'),(0x1004,'_APFSContainerResize','export'),(0x1008,'_APFSContainerGetMinimalSize','export')]
   if kind=='boundary':c.macho=lambda x:dict(starts=[0x1008])
   with tempfile.TemporaryDirectory() as t:
    p=Path(t)/'no.json'
    with self.assertRaises(ValueError):m.write_cache(c,p,None)
    self.assertFalse(p.exists())
if __name__=='__main__':unittest.main()
