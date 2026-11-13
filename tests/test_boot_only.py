#!/usr/bin/env python3
"""Reject unsafe reuse and verify that the splicer cannot change payload bytes."""
import argparse, copy, importlib.util, json, os
from pathlib import Path
import tempfile, unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('boot_only',Path(__file__).resolve().parents[1]/'myron27-boot-only.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
p=argparse.ArgumentParser();p.add_argument('--baseline-source',type=Path,required=True);p.add_argument('--base',type=Path,required=True)
a,rest=p.parse_known_args()
REPO=Path(__file__).resolve().parents[1]

class ReuseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.repo=Path(tmp.name)
        for name in ('myron27-inputs.json','myron27-storage-delta.json'):
            (self.repo/name).write_bytes((REPO/name).read_bytes())
    def edit(self,name,fn):
        path=self.repo/'myron27-storage-delta.json';d=b.read_json(path)
        row=d['files'][name];row['content']=fn(row['content']);row['sha256']=b.sha(row['content'].encode());b.save(path,d)
    def test_current_firmware_only_delta_accepted(self):
        r=b.check_sources(self.repo,a.baseline_source)
        self.assertTrue(r['payload_sources_unchanged']);self.assertTrue(r['loader_sources_unchanged'])
    def test_changed_loader_refused(self):
        self.edit(b.PREFIX+'loader/Handoff.S',lambda s:s+'\n// changed\n')
        with self.assertRaisesRegex(ValueError,'Payload/loader'):b.check_sources(self.repo,a.baseline_source)
    def test_changed_repo_pin_refused(self):
        self.edit(b.PREFIX+'prepare_firmware_source.py',lambda s:s.replace('e51cd877e31c8fbb322032dc4cb6715e83d25ad3','0'*40))
        with self.assertRaisesRegex(ValueError,'repository pins'):b.check_sources(self.repo,a.baseline_source)
    def test_changed_memory_contract_refused(self):
        self.edit(b.PREFIX+'firmware_memory_contract.py',lambda s:s+'\n# changed\n')
        with self.assertRaisesRegex(ValueError,'memory contract'):b.check_sources(self.repo,a.baseline_source)
    def test_non_bds_firmware_change_refused(self):
        def change(s):
            d=json.loads(s);name=next(n for n in d['files'] if n!=b.BDS)
            d['files'][name]['content']+='\n';d['files'][name]['sha256']=b.sha(d['files'][name]['content'].encode())
            return json.dumps(d,indent=2)+'\n'
        self.edit(b.PREFIX+'fixtures/firmware-source.json',change)
        with self.assertRaisesRegex(ValueError,'BDS-only'):b.check_sources(self.repo,a.baseline_source)
    def test_bad_source_digest_refused(self):
        d=b.read_json(self.repo/'myron27-storage-delta.json');next(iter(d['files'].values()))['sha256']='0'*64
        b.save(self.repo/'myron27-storage-delta.json',d)
        with self.assertRaisesRegex(ValueError,'source digest'):b.check_sources(self.repo,a.baseline_source)

class CheckoutTests(unittest.TestCase):
    def test_empty_submodule_placeholder_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'drivers/DarwinBoot';target.mkdir(parents=True)
            with patch.object(b.subprocess,'run') as run,patch.object(b.subprocess,'check_output',return_value='pinned\n'):
                b.checkout('unused','pinned',target)
                self.assertEqual(run.call_count,3)
    def test_nonempty_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);(target/'keep').write_text('keep')
            with patch.object(b.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'absent or empty'):b.checkout('unused','pinned',target)
                run.assert_not_called()
            self.assertEqual((target/'keep').read_text(),'keep')

class BinaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.raw,cls.m=b.read_base(a.base)
    def test_known_release_and_unchanged_splice(self):
        raw=self.raw;fd=raw[b.FD_OFFSET:b.FAT_OFFSET]
        self.assertEqual(b.splice(raw,fd),raw)
    def test_only_firmware_bytes_may_change(self):
        changed=b.splice(self.raw,b'F'*b.FD_BYTES)
        self.assertEqual(changed[:b.FD_OFFSET],self.raw[:b.FD_OFFSET])
        self.assertEqual(changed[b.FAT_OFFSET:],self.raw[b.FAT_OFFSET:])
        self.assertEqual(len(changed),len(self.raw))
    def test_changed_source_refused(self):
        changed=bytearray(self.raw);changed[-1]^=1
        with self.assertRaisesRegex(ValueError,'Source image changed'):b.splice(changed,bytes(b.FD_BYTES))
    def test_wrong_firmware_size_refused(self):
        with self.assertRaisesRegex(ValueError,'3MiB'):b.splice(self.raw,b'short')
    def test_real_payload_contract(self):
        import shutil
        if not shutil.which('mtype'):self.skipTest('mtools not installed locally; CI requires mtools')
        with tempfile.TemporaryDirectory() as temp:
            report=b.payload(a.base,Path(temp)/'payload')
            self.assertEqual(report['sha256'],self.m['image_reports']['root-startup.img']['payload_sha256'])
            self.assertTrue(report['boot_assets']['dyld_startup_probe_enabled'])

if __name__=='__main__':unittest.main(argv=[__file__]+rest)
