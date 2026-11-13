import importlib.util
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('collector',Path(__file__).resolve().parents[1]/'myron27-collect-native-checks.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
class CollectionTests(unittest.TestCase):
    def test_private_mount_is_not_scanned_and_permission_error_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'myron-private-native/myron-iphone27'
            blocked=work/'private-userland/root-media';blocked.mkdir(parents=True)
            (blocked/'native-link.log').write_text('must not read')
            good=work/'out/logs';good.mkdir(parents=True);(good/'kernel.log').write_text('PASS')
            bad=work/'out/unreadable';bad.mkdir()
            (work/'out/link').symlink_to(blocked,target_is_directory=True)
            real=os.scandir
            def scan(path):
                if 'private-userland' in str(path): raise AssertionError('Private mount traversed')
                if Path(path)==bad: raise PermissionError(13,'simulated EACCES',str(path))
                return real(path)
            with patch.object(os,'scandir',scan):r=c.collect(root,root/'staged')
            self.assertEqual(r['files'],['myron-private-native/myron-iphone27/out/logs/kernel.log'])
            self.assertEqual(len(r['errors']),1)
            self.assertEqual((root/'staged'/r['files'][0]).read_text(),'PASS')
if __name__=='__main__':unittest.main()
