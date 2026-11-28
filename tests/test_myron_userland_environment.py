#!/usr/bin/env python3
"""Exercise reconstructed userland audits and the explicit privileged argument path."""
import argparse,ast,contextlib,importlib.util,io,os,plistlib,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--device',type=Path,required=True)
args=parser.parse_args();device=args.device.resolve()
repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(device))
spec=importlib.util.spec_from_file_location('original_userland_fixtures',device/'tests/test_userland_audit.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
prep=fixtures.prep

class ExplicitGrowth(unittest.TestCase):
 def test_real_audit_keeps_donor_guard(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)/'os';system=Path(t)/'system'
   version=root/'System/Library/CoreServices/SystemVersion.plist';version.parent.mkdir(parents=True)
   version.write_bytes(plistlib.dumps(dict(ProductBuildVersion=prep.volume.BUILD,ProductVersion=prep.volume.VERSION)))
   trust=set()
   for name,kind in [('sbin/launchd',2),('usr/lib/dyld',7)]:
    raw,tc,_,_=fixtures.executable(kind);trust|=tc
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
   with patch.object(prep.volume,'check_userland',return_value=(root/'private/var',None)):
    for growth,reason in [('16','analyzed original launchd'),('8','Wrong early-task growth selection')]:
     with self.subTest(growth=growth),self.assertRaisesRegex(ValueError,reason):
      prep.audit_mounts(root,system,trust,set(),data_growth=growth)
    # Positive control for dispatch only: use the synthetic image's hash in
    # this scoped fixture. The production donor constant is never changed.
    import earlyboot_donor
    digest=fixtures.hashlib.sha256((root/'sbin/launchd').read_bytes()).hexdigest()
    (root/'usr/libexec').mkdir();checkpoints={}
    with patch.object(earlyboot_donor,'LAUNCHD_SHA256',digest):
     with self.assertRaisesRegex(ValueError,'Missing original shared cache'):
      prep.audit_mounts(root,system,trust,set(),lambda n,r:checkpoints.update({n:r}),data_growth='16')
     self.assertTrue(checkpoints['early-task-donor']['original_path_absent'])
     (root/'usr/libexec/HorizonSetup').symlink_to('absent')
     with self.assertRaisesRegex(ValueError,'must not be shadowed'):
      prep.audit_mounts(root,system,trust,set(),data_growth='16')
 def test_build_passes_growth_as_a_sudo_argument(self):
  tree=ast.parse((repo/'myron27-build.py').read_text())
  branch=[n for n in tree.body if isinstance(n,ast.If) and ast.unparse(n.test)=='options.userland']
  self.assertEqual(len(branch),1)
  code=compile(ast.Module(body=branch[0].body,type_ignores=[]),'actual-userland-branch','exec')
  for growth in (None,'16','8'):
   commands=[];env=dict(os.environ,MYRON_DATA_SEED='/fixture/seed')
   env.pop('MYRON_DATA_GROW',None)
   if growth is not None:env['MYRON_DATA_GROW']=growth
   ns=dict(root=Path('/fixture/build'),sys=sys,os=os,Path=Path,run=lambda cmd:commands.append(list(map(str,cmd))))
   with self.subTest(growth=growth),patch.dict(os.environ,env,clear=True),patch.object(shutil,'which',return_value='/fixture/ipsw'):
    with self.assertRaises(ValueError if growth=='8' else SystemExit) as caught:exec(code,ns)
    privileged=[c for c in commands if c[0]=='sudo']
    if growth=='8':self.assertFalse(privileged);continue
    self.assertEqual(caught.exception.code,0);self.assertEqual(len(privileged),1)
    cmd=privileged[0];self.assertEqual(cmd[:3],['sudo','-n',sys.executable])
    if growth is None:self.assertNotIn('--data-grow',cmd)
    else:self.assertEqual(cmd[-2:],['--data-grow','16'])
 def test_privileged_cli_receives_flag_without_environment(self):
  tree=ast.parse((device/'prepare_userland.py').read_text())
  branch=[n for n in tree.body if isinstance(n,ast.If) and ast.unparse(n.test)=="__name__ == '__main__'"]
  self.assertEqual(len(branch),1)
  code=compile(ast.Module(body=branch[0].body,type_ignores=[]),'actual-prepare-cli','exec')
  for growth in (None,'16','8'):
   calls=[];argv=['prepare_userland.py','--upstream','/fixture/upstream','--out','/fixture/out',
    '--report','/fixture/report','--archive-tool','/fixture/ipsw','--data-seed','/fixture/seed']
   if growth is not None:argv+=['--data-grow',growth]
   ns=dict(argparse=argparse,Path=Path,__doc__='CLI test',prepare=lambda *a:calls.append(a))
   with self.subTest(growth=growth),patch.dict(os.environ,{},clear=True),patch.object(sys,'argv',argv):
    if growth=='8':
     with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as caught:exec(code,ns)
     self.assertEqual(caught.exception.code,2);self.assertFalse(calls)
    else:
     exec(code,ns);self.assertEqual(len(calls),1);self.assertEqual(calls[0][-1],growth)

plain=dict(os.environ)
for k in ('MYRON_GPU_NATIVE','MYRON_PACKED_KERNEL','MYRON_METAL_ARTIFACT','MYRON_DATA_GROW','MYRON_DATA_HELPER_ARTIFACT','MYRON_DATA_CACHE_ARTIFACT'):
 plain.pop(k,None)
production=dict(plain,MYRON_GPU_NATIVE='1',MYRON_PACKED_KERNEL='1',MYRON_DATA_GROW='16',
 MYRON_METAL_ARTIFACT='/fixture/not-an-artifact.zip',MYRON_DATA_HELPER_ARTIFACT='/fixture/not-a-helper.zip')
for label,env in [('plain',plain),('production',production)]:
 print('Checking original userland suites with '+label+' environment',flush=True)
 for test in ('test_userland_audit.py','test_dyld_flow.py','test_root_media.py','test_original_root.py'):
  subprocess.run([sys.executable,str(device/'tests'/test)],check=True,env=env)
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExplicitGrowth))
if not result.wasSuccessful():raise SystemExit(1)
print('PASS: both userland test environments, real donor refusal and explicit growth argument across sudo boundary')
