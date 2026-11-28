#!/usr/bin/env python3
"""Compile/sign the iOS27 helper; never execute it against a host disk."""
import argparse,hashlib,json,plistlib,subprocess,sys
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent/'myron-gpu'))
from build_userspace import audit_image
from audit_userspace_artifact import image
def run(cmd):subprocess.run(list(map(str,cmd)),check=True)
out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
test=out/'host-check'
for source in ('test_apfs_growth.c','test_apfs_transaction.c'):
    run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',here/source,'-o',test])
    run([test]);test.unlink()
run([sys.executable,here/'test_apfs_journal.py'])
run([sys.executable,here/'test_data_earlyboot.py'])
sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
binary=out/'myron-data-grow'
run(['xcrun','--sdk','iphoneos','clang','-target','arm64e-apple-ios27.0','-isysroot',sdk,
     '-O2','-Wall','-Wextra','-Werror','-fobjc-arc',here/'myron-data-grow.m',
     '-framework','Foundation','-o',binary])
entitlements={'platform-application':True,'com.apple.private.security.no-container':True,
    'com.apple.private.security.no-sandbox':True,'com.apple.private.security.disk-device-access':True,
    'com.apple.security.iokit-user-client-class':['AppleAPFSUserClient']}
ent=out/'entitlements.plist';ent.write_bytes(plistlib.dumps(entitlements))
run(['codesign','--force','--sign','-','--pagesize','4096','--identifier','org.unixnu.myron.data-grow',
     '--entitlements',ent,binary])
actual=plistlib.loads(subprocess.check_output(['codesign','-d','--entitlements',':-',binary],stderr=subprocess.DEVNULL))
assert actual==entitlements
report=audit_image(binary,2);independent=image(binary.read_bytes(),2,{},identifier='org.unixnu.myron.data-grow',entitlements=entitlements)
assert all(independent[k]==v for k,v in report.items())
early=out/'HorizonSetup'
run(['xcrun','--sdk','iphoneos','clang','-target','arm64e-apple-ios27.0','-isysroot',sdk,
     '-std=c11','-O2','-Wall','-Wextra','-Werror',here/'myron-data-earlyboot.c','-o',early])
early_entitlements={k:True for k in ('platform-application','com.apple.private.security.no-container',
                                    'com.apple.private.security.no-sandbox')}
early_ent=out/'earlyboot-entitlements.plist';early_ent.write_bytes(plistlib.dumps(early_entitlements))
run(['codesign','--force','--sign','-','--pagesize','4096','--identifier','com.apple.HorizonSetup',
     '--entitlements',early_ent,early])
early_report=audit_image(early,2)
independent=image(early.read_bytes(),2,{},identifier='com.apple.HorizonSetup',entitlements=early_entitlements)
assert all(independent[k]==v for k,v in early_report.items())
early_report.update(identifier='com.apple.HorizonSetup',entitlements=early_entitlements,
                    published_path='/usr/libexec/HorizonSetup',boot_task='restore-datapartition')
report.update(format=2,compiled=True,hardware_tested=False,apfs_resized=False,installed=False,
    entitlements=entitlements,earlyboot=early_report,
    source_sha256={name:hashlib.sha256((here/name).read_bytes()).hexdigest()
        for name in ('myron-data-grow.m','MyronAPFSGrow.h','MyronAPFSTransaction.h',
                     'test_apfs_growth.c','test_apfs_transaction.c','test_apfs_journal.py',
                     'myron-data-earlyboot.c','test_data_earlyboot.py','build_data_helper.py')})
(out/'build.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: signed arm64e iOS27 helper and early adapter; not executed, installed or qualified on phone')
