#!/usr/bin/env python3
import argparse,json,os,subprocess,tempfile,tomllib
import ui_seed
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True);p.add_argument('--ramblock',type=Path,required=True);p.add_argument('--cxx',default='c++');p.add_argument('--output',type=Path);a=p.parse_args()
here=Path(__file__).resolve().parent;device=a.device.resolve();ufs=device.parent/'sm8850/drivers/NativeUfs'
subprocess.run([__import__('sys').executable,str(here/'test_buttons.py'),'--cxx',a.cxx],check=True)
subprocess.run([__import__('sys').executable,str(here/'test_power.py'),'--cxx',a.cxx],check=True)
subprocess.run([__import__('sys').executable,str(here.parent/'tests/test_myron_log_worker.py'),
                '--device',str(device),'--cc',a.cxx],check=True)
with tempfile.TemporaryDirectory() as tmp:
 for name in ('test_runtime','test_store','test_data_growth','test_data_migration'):
  exe=Path(tmp)/name
  subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-sanitize-recover=all',
   '-I',here,'-I',here.parent/'myron-touch','-I',a.ramblock.resolve(),'-I',ufs,here/(name+'.cpp'),'-o',exe],check=True)
  subprocess.run([exe],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)
 for name in ui_seed.PATHS:
  file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'stale')
 keep=root/'mobile/Library/Preferences/com.apple.springboard.plist';keep.write_bytes(b'keep')
 # APFS host may be case-insensitive: MobileGestalt/mobilegestalt can name
 # the same inode; the iOS seed may be case-sensitive. Test both correctly.
 distinct={(os.stat(root/name).st_dev,os.stat(root/name).st_ino) for name in ui_seed.PATHS}
 assert len(ui_seed.clear(root))==len(distinct) and keep.read_bytes()==b'keep'
 assert not ui_seed.clear(root)
 (root/ui_seed.PATHS[1]).symlink_to(keep)
 try:ui_seed.clear(root)
 except ValueError:pass
 else:raise AssertionError('Symlink cache accepted')
board=tomllib.loads((device/'board.toml').read_text())
assert board['adt']['chosen']['u32']['display-scale']==board['adt']['product']['u32']['artwork-scale-factor']==3
assert board['adt']['product']['u32']['artwork-device-subtype']==2556
assert board['adt']['product']['string']['compatible-device-fallback']=='iPhone15,2'
report=dict(host_passed=True,hardware_tested=False,tests=['bounded UFS ranges and failure closure','durable overlay reopen and seed mismatch','4 GiB disjoint migration geometry and seed identity','pre-mount migration: 27 injected I/O failures, retries and fail-closed selection','power debounce, boot-held suppression and read timeout','3x paired presentation properties'],physical_framebuffer_changed=False)
if a.output:a.output.write_text(json.dumps(report,indent=2)+'\n')
print('PASS: Data geometry, actual store callbacks, overlay reopen, PMIC debounce; hardware untested')
