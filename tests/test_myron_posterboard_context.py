import importlib.util
from pathlib import Path
import struct
import unittest
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

spec=importlib.util.spec_from_file_location('poster',Path(__file__).resolve().parents[1]/'myron_posterboard_context.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Cache:
    def __init__(self, words):
        self.code=struct.pack('<'+'I'*len(words),*words).ljust(32,b'\0')
        self.chain=True
    def image_for(self,address):return {'address':address}
    def symbol_for(self,address,image,strict=False):
        return {'address':hex(0x1100),'name':'_target'} if address>=0x1100 else None
    def read(self,address,size,executable=False):
        if address!=0x1000:raise ValueError('unmapped')
        return self.code[:size],None
    def pointer_chain(self,address,slide):
        assert address==0x2000 and slide==0
        return {'chain_member':self.chain,'unsigned_runtime_target':'0x1100'}

class Context(unittest.TestCase):
    def setUp(self):
        self.decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);self.decoder.detail=True
    def test_direct_thunk_and_exact_symbol(self):
        rows=m.call_entry(Cache([0x14000040]),self.decoder,0x1000)
        self.assertEqual(rows[-1]['exact_symbol'],'_target')
        self.assertNotIn('bytes',rows[0])
    def test_adrp_add_branch_thunk(self):
        # adrp x16,0x1000; add x16,x16,#0x100; br x16
        rows=m.call_entry(Cache([0x90000010,0x91040210,0xd61f0200]),self.decoder,0x1000)
        self.assertEqual(rows[-1]['exact_symbol'],'_target')
    def test_indirect_target_requires_verified_chain(self):
        # adrp x16, 0x2000; ldr x16, [x16]; br x16
        cache=Cache([0xb0000010,0xf9400210,0xd61f0200])
        rows=m.call_entry(cache,self.decoder,0x1000)
        self.assertEqual(rows[-1]['exact_symbol'],'_target')
        self.assertTrue(rows[0]['pointer_targets'][0]['static_chain_only'])
        cache.chain=False
        self.assertEqual(len(m.call_entry(cache,self.decoder,0x1000)),1)
    def test_nearest_symbol_and_cycle_are_not_targets(self):
        self.assertIsNone(m.exact_symbol(Cache([]),0x1104))
        self.assertEqual(len(m.call_entry(Cache([0x14000000]),self.decoder,0x1000)),1)
    def test_overwritten_pointer_is_not_followed(self):
        cache=Cache([0xb0000010,0xf9400210,0xd2800010,0xd61f0200]) # mov x16,#0
        self.assertEqual(len(m.call_entry(cache,self.decoder,0x1000)),1)
    def test_function_collection_is_bounded(self):
        class Many(Cache):
            def read(self,address,size,executable=False):
                return struct.pack('<I',0xd503201f)*(size//4),None
        names={0x3000+i*4096:{'-[PBFPosterExtensionDataStore init]'} for i in range(60)}
        starts=sorted(names)+[0x3000+60*4096]
        result=m.collect(Many([]),{'address':0},starts,names,self.decoder,lambda *a,**k:[])
        self.assertGreater(result['omitted_functions'],0)
        self.assertTrue(all(x['truncated'] and len(x['instructions'])==512 for x in result['functions']))
        self.assertFalse(result['runtime_observation'])
    def test_initialization_chain_precedes_gallery_and_is_not_truncated(self):
        class Many(Cache):
            def read(self,address,size,executable=False):
                return struct.pack('<I',0xd503201f)*(size//4),None
        names={0x3000+i*4096:{'-[PBFPosterExtensionDataStore reload]'} for i in range(60)}
        factory=0x3000+60*4096
        names[factory]={'-[PBFPosterExtensionDataStoreXPCServiceGlue _lock_dataStoreWithError:]'}
        starts=sorted(names)+[factory+4096]
        result=m.collect(Many([]),{'address':0},starts,names,self.decoder,lambda *a,**k:[])
        row=next(f for f in result['functions'] if f['offset']==hex(factory))
        self.assertFalse(row['truncated'])
        self.assertEqual(len(row['instructions']),1024)

if __name__=='__main__':unittest.main()
