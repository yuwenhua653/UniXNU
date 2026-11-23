#!/usr/bin/env python3
"""Exercise seed identity and app budgeting before a native build."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True);p.add_argument('--seed',type=Path)
a,rest=p.parse_known_args();sys.path.insert(0,str(a.device.resolve()))
import staged_apps as apps
import reuse_data_seed as seed
import prepare_data_volume as volume

class Upgrade(unittest.TestCase):
    def test_budget_skips_oversized_tree_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'apps';src.mkdir()
            for name in ('MobileNotes.app','Big.app','Small.app','Linked.app'):
                (src/name).mkdir();(src/name/'signed-code').write_bytes(b'original')
            (src/'Linked.app/link').symlink_to(root)
            sizes={'MobileNotes.app':20<<20,'Big.app':2<<30,'Small.app':40<<20,'Linked.app':1}
            with patch.object(volume,'tree_usage',side_effect=lambda path,**kw:dict(allocation_estimate=sizes[path.name])):
                plan=apps.plan(src,root/'plan.json')
            self.assertEqual(plan['selected'],['MobileNotes.app','Small.app'])
            self.assertEqual(plan['allocation_bytes'],60<<20)
            self.assertFalse(plan['all_selected'])
            self.assertEqual((src/'MobileNotes.app/signed-code').read_bytes(),b'original')
    def test_empty_and_oversized_source_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'apps';src.mkdir()
            with self.assertRaises(ValueError):apps.plan(src,root/'plan.json')
            (src/'Big.app').mkdir()
            with patch.object(volume,'tree_usage',return_value=dict(allocation_estimate=apps.BUDGET+1)):
                with self.assertRaises(ValueError):apps.plan(src,root/'plan.json')
    def test_exact_upstream_transform_is_fail_closed(self):
        upstream=(Path(__file__).parent/'fixtures/myron-staged-apps-upstream.c').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            plan=Path(tmp)/'plan.json';plan.write_text(json.dumps(dict(build='24A446',selected=['MobileNotes.app'],allocation_bytes=20<<20)))
            code=apps.source(upstream,plan)
            self.assertIn('!strcmp(name,"MobileNotes.app")',code)
            self.assertIn('space->f_bavail <= 0',code)
            self.assertIn('mach_vm_allocate_kernel(map,&scratch,4096',code)
            self.assertIn('mach_vm_deallocate(map,scratch,4096)',code)
            self.assertIn('memcmp(bytes,expected,sizeof expected)',code)
            self.assertIn('VNOP_FSYNC(marker, MNT_WAIT, ctx)',code)
            with self.assertRaises(ValueError):apps.source(upstream.replace('O_CREAT | O_TRUNC','O_CREAT',1).replace('const uint32_t chunk = 1024 * 1024','const uint32_t chunk = 4096'),plan)
            plan.write_text(json.dumps(dict(build='24A446',selected=['../escape'],allocation_bytes=0)))
            with self.assertRaises(ValueError):apps.source(upstream,plan)
    def test_foreign_seed_never_creates_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);foreign=root/'foreign';foreign.write_bytes(bytes(4096))
            with self.assertRaises(ValueError):seed.unpack(foreign,root/'raw')
            self.assertFalse((root/'raw').exists())
    @unittest.skipUnless(a.seed,'exact retained package input required')
    def test_real_seed_roundtrip_and_bit_flip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);report=seed.unpack(a.seed,root/'raw')
            self.assertEqual(report['logical_sha256'],seed.LOGICAL)
            with (root/'raw').open('rb') as stream:
                self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),seed.LOGICAL)
            bad=bytearray(a.seed.read_bytes());bad[-1]^=1;(root/'bad').write_bytes(bad)
            with self.assertRaises(ValueError):seed.unpack(root/'bad',root/'bad-raw')
            self.assertFalse((root/'bad-raw').exists())

if __name__=='__main__':unittest.main(argv=[sys.argv[0],*rest])
