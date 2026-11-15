#!/usr/bin/env python3
"""Synthetic cache bounds/identity/address checks; no original Apple bytes."""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fault_symbolicate', ROOT/'myron27-fault-symbolicate.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

BASE = 0x180000000
UUID = bytes.fromhex('0102030405060708090a0b0c0d0e0f10')
CHILD_UUID = bytes.fromhex('1112131415161718191a1b1c1d1e1f20')


def cache_bytes(*, base=BASE, identity=UUID, child=None, image=True, prot=5):
    """A bounded modern arm64e header, one mapping and one tiny Mach-O."""
    b = bytearray(0x4000)
    b[:16] = b'dyld_v1  arm64e'.ljust(16, b'\0')
    struct.pack_into('<II', b, 16, 0x200, 1)
    struct.pack_into('<QQ', b, 40, len(b), 0)
    b[88:104] = identity
    struct.pack_into('<QQQ', b, 224, BASE, 0x100000, 0x100000)
    struct.pack_into('<II', b, 312, 0x240, 1)
    struct.pack_into('<QQQII', b, 0x200, base, len(b), 0, prot, prot)
    struct.pack_into('<QQQQQQII', b, 0x240, base, len(b), 0, 0, 0, 0, prot, prot)
    if child is not None:
        struct.pack_into('<II', b, 392, 0x2a0, 1)
        struct.pack_into('<16sQ32s', b, 0x2a0, child, 0x10000, b'.01')
    if image:
        struct.pack_into('<QQ', b, 136, 0x300, 1)
        struct.pack_into('<16sQII', b, 0x300, identity, base+0x1000, 0x1000, 0x380)
        path = b'/usr/lib/libSynthetic.dylib\0'
        b[0x380:0x380+len(path)] = path
        # Segment file offsets in a cache image refer to its containing cache.
        commands = bytearray()
        commands += struct.pack('<II16sQQQQIIII', 0x19, 152, b'__TEXT', base+0x1000, 0x1000,
                                0x1000, 0x1000, 5, 5, 1, 0)
        commands += struct.pack('<16s16sQQ8I', b'__text', b'__TEXT', base+0x1200, 0x80,
                                0x1200, 2, 0, 0, 0x80000400, 0, 0, 0)
        commands += struct.pack('<II16sQQQQIIII', 0x19, 72, b'__LINKEDIT', base+0x2000, 0x1000,
                                0x2000, 0x1000, 1, 1, 0, 0)
        commands += struct.pack('<IIII', 0x26, 16, 0x2800, 5)
        commands += struct.pack('<IIIIII', 2, 24, 0x2900, 1, 0x2a00, 8)
        commands += struct.pack('<II16s', 0x1b, 24, identity)
        struct.pack_into('<8I', b, 0x1000, 0xfeedfacf, 0x100000c, 2, 6, 5, len(commands), 0, 0)
        b[0x1020:0x1020+len(commands)] = commands
        for at in range(0x1200,0x1280,4):
            struct.pack_into('<I', b, at, 0xd503201f)  # nop
        struct.pack_into('<I', b, 0x1204, 0xf9400008)  # ldr x8,[x0]
        struct.pack_into('<I', b, 0x121c, 0xd65f03c0)  # ret
        b[0x2800:0x2805] = b'\x80\x04\x20\x20\0'
        struct.pack_into('<IBBHQ', b, 0x2900, 1, 0xf, 1, 0, base+0x1200)
        b[0x2a00:0x2a08] = b'\0_start\0'
    return b


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.main = self.directory/'dyld_shared_cache_arm64e'

    def write(self, raw=None):
        self.main.write_bytes(cache_bytes() if raw is None else raw)
        c=m.CacheSet(self.directory)
        self.addCleanup(c.close)
        return c

    def test_exact_mapped_instruction_read(self):
        c = self.write()
        data, metadata = c.read(BASE+0x1204, 4, executable=True)
        self.assertEqual(data, bytes.fromhex('080040f9'))
        self.assertIsInstance(metadata, dict)

    def test_image_lookup_does_not_claim_gap(self):
        c = self.write()
        self.assertIsNotNone(c.image_for(BASE+0x1204))
        self.assertIsNone(c.image_for(BASE+0x3000))

    def test_unmapped_and_mapping_crossing_are_rejected(self):
        c = self.write()
        for va, size in ((BASE-4,4),(BASE+0x4000,4),(BASE+0x3ffe,4)):
            with self.subTest(va=va,size=size), self.assertRaises((m.Error,ValueError)):
                c.read(va,size)

    def test_executable_read_rejects_data_mapping(self):
        c = self.write(cache_bytes(prot=3))
        self.assertEqual(len(c.read(BASE+0x1100,4)[0]),4)
        with self.assertRaises((m.Error,ValueError)):
            c.read(BASE+0x1100,4,executable=True)

    def test_truncated_header_rejected(self):
        for size in (0,16,200,463):
            with self.subTest(size=size), self.assertRaises((m.Error,ValueError)):
                self.write(cache_bytes()[:size])

    def test_unexpected_architecture_rejected(self):
        b=cache_bytes();b[:16]=b'dyld_v1   arm64'.ljust(16,b'\0')
        with self.assertRaises((m.Error,ValueError)):
            self.write(b)

    def test_zero_uuid_rejected(self):
        b=cache_bytes();b[88:104]=bytes(16)
        with self.assertRaises((m.Error,ValueError)):
            self.write(b)

    def test_mapping_table_out_of_file_rejected(self):
        b=cache_bytes();struct.pack_into('<II',b,16,len(b)-16,2)
        with self.assertRaises((m.Error,ValueError)):
            self.write(b)

    def test_mapping_data_out_of_file_rejected(self):
        b=cache_bytes();struct.pack_into('<Q',b,0x200+16,len(b)-0x1000)
        with self.assertRaises((m.Error,ValueError)):
            self.write(b)

    def test_overlapping_mappings_rejected(self):
        b=cache_bytes();struct.pack_into('<I',b,20,2)
        struct.pack_into('<QQQII',b,0x220,BASE+0x1000,0x1000,0x1000,5,5)
        struct.pack_into('<I',b,316,2)
        # Put slide table elsewhere so its second row does not obscure header data.
        struct.pack_into('<I',b,312,0x500)
        b[0x500:0x538]=b[0x240:0x278]
        struct.pack_into('<QQQQQQII',b,0x538,BASE+0x1000,0x1000,0x1000,0,0,0,5,5)
        with self.assertRaises((m.Error,ValueError)):
            self.write(b)

    def test_missing_subcache_rejected(self):
        with self.assertRaises((m.Error,ValueError,FileNotFoundError)):
            self.write(cache_bytes(child=CHILD_UUID))

    def test_subcache_uuid_mismatch_rejected(self):
        (self.directory/'dyld_shared_cache_arm64e.01').write_bytes(
            cache_bytes(base=BASE+0x10000,identity=UUID,image=False))
        with self.assertRaises((m.Error,ValueError)):
            self.write(cache_bytes(child=CHILD_UUID))

    def test_matching_subcache_is_readable(self):
        child=cache_bytes(base=BASE+0x10000,identity=CHILD_UUID,image=False)
        child[0x1000:0x1004]=b'ABCD'
        (self.directory/'dyld_shared_cache_arm64e.01').write_bytes(child)
        c=self.write(cache_bytes(child=CHILD_UUID))
        self.assertEqual(c.read(BASE+0x11000,4)[0],b'ABCD')

    def test_unsafe_subcache_suffix_rejected(self):
        b=cache_bytes(child=CHILD_UUID)
        struct.pack_into('<32s',b,0x2a0+24,b'../outside')
        with self.assertRaises((m.Error,ValueError)):
            self.write(b)

    def test_image_text_bounds_rejected(self):
        b=cache_bytes();struct.pack_into('<QQ',b,136,len(b)-16,2)
        with self.assertRaises((m.Error,ValueError)):
            self.write(b)

    def test_recorded_slide_address_arithmetic(self):
        self.assertEqual(0x183257140-0x02e3c000,0x18041b140)
        # This is an explicitly labeled masking candidate, not PAC authentication.
        self.assertEqual((0x037670c183257474&((1<<36)-1))-0x02e3c000,0x18041b474)
        self.assertNotEqual(0x037670c183257474&((1<<39)-1),0x183257474)
        self.assertEqual(0x00000741e9d71f70-0x00000001e9d71f70,0x74000000000)

    def test_function_boundary_does_not_claim_exact_symbol(self):
        c=self.write();im=c.image_for(BASE+0x1204)
        first=c.symbol_for(BASE+0x1204,im)
        self.assertEqual(first['name'],'_start')
        self.assertTrue(first['exact_function_start_match'])
        other=c.symbol_for(BASE+0x1224,im)
        self.assertEqual(other['function_start'],hex(BASE+0x1220))
        self.assertFalse(other['exact_function_start_match'])
        self.assertIn('nearest static symbol',other['attribution'])

    def test_exact_instruction_disassembly(self):
        c=self.write();report=c.describe(BASE+0x1204,window=4)
        hit=[row for row in report['instructions'] if row['is_observed_pc']]
        self.assertEqual(len(hit),1)
        self.assertEqual((hit[0]['mnemonic'],hit[0]['operands']),('ldr','x8, [x0]'))

    def test_invalid_word_before_pc_does_not_hide_valid_pc(self):
        b=cache_bytes();struct.pack_into('<I',b,0x1200,0xffffffff)
        c=self.write(b);report=c.describe(BASE+0x1204,window=4)
        hit=next(row for row in report['instructions'] if row['is_observed_pc'])
        before=next(row for row in report['instructions'] if row['address']==hex(BASE+0x1200))
        self.assertEqual((hit['mnemonic'],hit['operands']),('ldr','x8, [x0]'))
        self.assertFalse(before['decoded'])
        self.assertTrue(hit['decoded'])

    def local_symbols(self,identity=CHILD_UUID):
        b=bytearray(0x400)
        b[:16]=b'dyld_v1  arm64e'.ljust(16,b'\0')
        b[88:104]=identity
        struct.pack_into('<QQ',b,72,0x100,0x100)
        struct.pack_into('<6I',b,0x100,0x20,1,0x40,8,0x50,1)
        struct.pack_into('<IBBHQ',b,0x120,1,0xf,1,0,BASE+0x1220)
        b[0x140:0x148]=b'\0_local\0'
        struct.pack_into('<QII',b,0x150,0x1000,0,1)
        (self.directory/'dyld_shared_cache_arm64e.symbols').write_bytes(b)

    def test_matching_local_symbols_uuid_is_used(self):
        b=cache_bytes();b[400:416]=CHILD_UUID;self.local_symbols()
        c=self.write(b);symbol=c.symbol_for(BASE+0x1224,c.image_for(BASE+0x1224))
        self.assertEqual((symbol['name'],symbol['source']),('_local','local_symbols'))
        self.assertTrue(symbol['exact_function_start_match'])

    def test_wrong_local_symbols_uuid_rejected(self):
        b=cache_bytes();b[400:416]=CHILD_UUID;self.local_symbols(UUID)
        c=self.write(b)
        with self.assertRaises((m.Error,ValueError)):
            c.symbol_for(BASE+0x1224,c.image_for(BASE+0x1224))

    def with_exports(self,trie):
        b=cache_bytes();count,size=struct.unpack_from('<II',b,0x1010)
        struct.pack_into('<IIII',b,0x1020+size,0x80000033,16,0x2b00,len(trie))
        struct.pack_into('<II',b,0x1010,count+1,size+16)
        b[0x2b00:0x2b00+len(trie)]=trie
        return b

    def test_export_trie_provides_exact_function_name(self):
        trie=b'\0\1_export\0\x0b'+b'\x03\0\xa0\x04\0'
        c=self.write(self.with_exports(trie))
        s=c.symbol_for(BASE+0x1224,c.image_for(BASE+0x1224))
        self.assertEqual((s['name'],s['source']),('_export','exports_trie'))
        self.assertTrue(s['exact_function_start_match'])

    def test_export_trie_cycle_rejected(self):
        c=self.write(self.with_exports(b'\0\1_cycle\0\0'))
        with self.assertRaisesRegex(m.Error,'cyclic'):
            c.symbol_for(BASE+0x1224,c.image_for(BASE+0x1224))

    def test_disassembly_rejects_unaligned_pc(self):
        c=self.write()
        with self.assertRaises((m.Error,ValueError)):
            c.describe(BASE+0x1205)

    def chained(self,page_size=4096):
        b=cache_bytes();count=len(b)//page_size
        struct.pack_into('<QQ',b,0x240+24,0x3000,24+count*2)
        struct.pack_into('<3I',b,0x3000,5,page_size,count)
        struct.pack_into('<Q',b,0x3010,BASE)
        starts=[0xffff]*count;starts[0x1300//page_size]=0x1300%page_size
        for n,start in enumerate(starts):struct.pack_into('<H',b,0x3018+n*2,start)
        plain=0x2500|(0xa5<<34)|(2<<52)
        auth=0x2600|(0xabcd<<34)|(1<<50)|(1<<51)|(1<<63)
        struct.pack_into('<Q',b,0x1300,plain);struct.pack_into('<Q',b,0x1310,auth)
        return b,plain,auth

    def test_v5_plain_and_authenticated_chain_members(self):
        for page_size in (4096,16384):
            with self.subTest(page_size=page_size):
                b,plain,auth=self.chained(page_size);c=self.write(b)
                p=c.pointer_chain(BASE+0x1300,0x1000)
                self.assertTrue(p['chain_member']);self.assertFalse(p['authenticated'])
                self.assertEqual(p['raw'],hex(plain))
                self.assertEqual(p['unsigned_runtime_target'],hex(BASE+0x3500))
                self.assertEqual(p['rebased_runtime_value'],hex((BASE+0x3500)|(0xa5<<56)))
                a=c.pointer_chain(BASE+0x1310,0x1000)
                self.assertTrue(a['chain_member']);self.assertTrue(a['authenticated'])
                self.assertEqual(a['raw'],hex(auth));self.assertEqual(a['diversity'],'0xabcd')
                self.assertTrue(a['address_diversity']);self.assertEqual(a['key'],'DA')
                self.assertFalse(a['native_pointer_authentication_executed'])
                self.assertEqual(a['chain_entries_traversed'],2)
                c.close()

    def test_v5_nonmember_is_not_a_decoded_pointer(self):
        b,_,_=self.chained();c=self.write(b)
        for off in (0x12f8,0x1308,0x1318,0x2000):
            with self.subTest(off=off):self.assertFalse(c.pointer_chain(BASE+off,0x1000)['chain_member'])

    def test_v5_bad_start_and_chain_bounds_rejected(self):
        b,_,_=self.chained();struct.pack_into('<H',b,0x301a,0xfff)
        c=self.write(b)
        with self.assertRaises((m.Error,ValueError)):c.pointer_chain(BASE+0x1300,0)
        c.close()
        b,_,_=self.chained();struct.pack_into('<Q',b,0x1300,0x2500|(0x7ff<<52))
        c=self.write(b)
        with self.assertRaises((m.Error,ValueError)):c.pointer_chain(BASE+0x1310,0)


if __name__=='__main__':
    unittest.main(verbosity=2)
