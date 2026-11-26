import importlib.util,json,tempfile,unittest
from unittest import mock
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
 def test_posterboard_uuid_and_exact_function_boundaries(self):
  base=0x180000000;c=Cache()
  c.images=[dict(path='/System/Library/PrivateFrameworks/PosterBoard.framework/PosterBoard',
   uuid='2ce463af35a63164ac6cb7a007e81d10',address=base,size=0x300000)]
  starts=sorted(base+x for x in (0x6a400,0x6a500,0x6be00,0x6bf00,0x266800,0x266900))
  c.macho=lambda image:dict(starts=starts)
  c.symbols=lambda image,strict:[(base+0x6a400,'_exact','test'),(base+0x6b000,'_unrelated_nearest','test')]
  with tempfile.TemporaryDirectory() as d,mock.patch.object(m,'setup_method_flow',return_value=[]) as flow:
   path=Path(d)/'poster.json';m.write_posterboard_queries(c,path);report=json.loads(path.read_text())
   self.assertEqual(flow.call_count,3)
   self.assertEqual(report['sites'][1]['exact_start_names'],[])
   self.assertEqual(report['sites'][2]['exact_start_names'],['_exact'])
   self.assertTrue(all(row['window_bytes']<=2048 and not row['truncated'] for row in report['sites']))
   self.assertTrue(all(row['window_offset']==row['function_offset'] for row in report['sites']))
   self.assertTrue(all(call.kwargs['string_limit']==512 for call in flow.call_args_list))
   self.assertFalse(report['raw_image_bytes_exported'])
   c.images[0]['uuid']='wrong'
   with self.assertRaisesRegex(ValueError,'UUID'):m.write_posterboard_queries(c,Path(d)/'bad.json')
   self.assertFalse((Path(d)/'bad.json').exists())
 def test_null_indirect_reference_does_not_resolve_cache_header(self):
  from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
  import struct
  c=Cache();decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);decoder.detail=True
  def read(address,size,executable=False):
   if address==0x1000:return struct.pack('<I',0x10000800),None # adr x0, +0x100
   if address==0x1100:return bytes(size),None
   if address==c.region_start:return b'dyld_v1  arm64e\0'+bytes(size-16),None
   raise ValueError('unmapped')
  c.read=read
  self.assertEqual(m.setup_method_flow(c,c.images[0],decoder,{},0x1000,0x1004),[])
 def test_long_assertion_string_is_bounded_and_opt_in(self):
  from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
  import struct
  c=Cache();decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);decoder.detail=True
  message='assertion: '+('x'*240)
  def read(address,size,executable=False):
   if address==0x1000:return struct.pack('<I',0x10000800),None
   if address==0x1100:return (message.encode()+b'\0'+bytes(size))[:size],None
   raise ValueError('unmapped')
  c.read=read
  self.assertEqual(m.setup_method_flow(c,c.images[0],decoder,{},0x1000,0x1004),[])
  self.assertEqual(m.setup_method_flow(c,c.images[0],decoder,{},0x1000,0x1004,string_limit=512),[('0x0',message)])
if __name__=='__main__':unittest.main()
