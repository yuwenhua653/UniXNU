import hashlib,io,json
from pathlib import Path
import tempfile,unittest,zipfile
from unittest.mock import patch
import merge_parts as m
import split_artifact as s

class PartsTests(unittest.TestCase):
    def setUp(self):
        self.raw=bytes(range(256))*83;self.name=m.NAME
        for module in (m,s):
            for key,value in dict(SIZE=len(self.raw),SHA=hashlib.sha256(self.raw).hexdigest(),PART_BYTES=4096,COUNT=6).items():
                p=patch.object(module,key,value);p.start();self.addCleanup(p.stop)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)/'parts'
        s.split(io.BytesIO(self.raw),self.root)
    def test_wrapped_parts_restore_exact_original(self):
        for i,p in enumerate(sorted(self.root.glob('*.part*'))):
            with zipfile.ZipFile(self.root/f'myron-root-part{i:02d}.zip','w') as z:z.write(p,p.name)
            p.unlink()
        out=m.merge(self.root);self.assertEqual(out.read_bytes(),self.raw)
        self.assertEqual(m.merge(self.root),out)
    def test_bad_part_rejected_and_preserved(self):
        p=self.root/(self.name+'.part02');p.write_bytes(b'X'*p.stat().st_size)
        with self.assertRaisesRegex(ValueError,'Damaged part 02'):m.merge(self.root)
        self.assertFalse((self.root/self.name).exists());self.assertTrue(p.exists())
    def test_missing_part_before_output(self):
        (self.root/(self.name+'.part03')).unlink()
        with self.assertRaisesRegex(ValueError,'Missing part 03'):m.merge(self.root)
        self.assertFalse((self.root/(self.name+'.merging')).exists())
    def test_short_source_does_not_publish_manifest(self):
        target=self.root.parent/'bad'
        with self.assertRaisesRegex(ValueError,'Truncated'):s.split(io.BytesIO(self.raw[:-1]),target)
        self.assertFalse((target/'parts.json').exists())
    def test_changed_source_hash_does_not_publish_manifest(self):
        target=self.root.parent/'bad'
        with self.assertRaisesRegex(ValueError,'SHA256'):s.split(io.BytesIO(b'X'+self.raw[1:]),target)
        self.assertFalse((target/'parts.json').exists())
    def test_renamed_part_rejected(self):
        p=self.root/'parts.json';j=json.loads(p.read_text());j['parts'][0]['file']='../unsafe'
        p.write_text(json.dumps(j))
        with self.assertRaisesRegex(ValueError,'layout'):m.merge(self.root)

if __name__=='__main__':unittest.main()
