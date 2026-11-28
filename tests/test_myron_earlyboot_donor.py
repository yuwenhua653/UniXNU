import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'myron-runtime'))
from earlyboot_donor import verify,LAUNCHD_SHA256
class Donor(unittest.TestCase):
 def test_actual_directory_and_absent_program(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);directory=root/'usr/libexec';directory.mkdir(parents=True)
   (directory/'installd').write_bytes(b'keep')
   self.assertTrue(verify(root,LAUNCHD_SHA256)['original_path_absent'])
   self.assertEqual((directory/'installd').read_bytes(),b'keep')
   with self.assertRaisesRegex(ValueError,'launchd'):verify(root,'0'*64)
   target=directory/'HorizonSetup'
   for kind in ('file','directory','dangling-link','existing-link'):
    if kind=='file':target.write_bytes(b'original')
    elif kind=='directory':target.mkdir()
    else:target.symlink_to('absent' if kind=='dangling-link' else 'installd')
    with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'shadowed'):verify(root,LAUNCHD_SHA256)
    if kind=='directory':target.rmdir()
    else:target.unlink()
 def test_invalid_parent(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'usr').mkdir()
   with self.assertRaises(ValueError):verify(root,LAUNCHD_SHA256)
   (root/'real').mkdir();(root/'usr/libexec').symlink_to(root/'real')
   with self.assertRaises(ValueError):verify(root,LAUNCHD_SHA256)
if __name__=='__main__':unittest.main()
