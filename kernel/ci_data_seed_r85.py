#!/usr/bin/env python3
"""On macOS, fetch only pinned 21H461 OS.dmg and produce a clean RAM Data seed."""
import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
from types import SimpleNamespace
from prepare_data_seed_r84 import create, sha

URL='https://updates.cdn-apple.com/2025SpringFCS/fullrestores/122-77166/DCA6CFE8-90E9-4B92-880D-3DE171798E40/iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw'
OS_FILE='044-76040-038.dmg'
OS_SHA='3f99b859c9728379110b66657c7b15285bcb1925ad8b5726542e2cdcf8b1028d'
MANIFEST_SHA='199fb5de41c26d86c080b4e8e402c40309c5f42e7bda18c210451b09bcb49bf7'
PACKER_SHA='efb5fac21ae94dcb1aecd47da2b73a7112b487e43692ac6396858552d27a0e48'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unixnu',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if platform.system()!='Darwin' or os.geteuid()!=0:
        raise SystemExit('Run on macOS as root; no download or output created')
    unixnu=args.unixnu.resolve(strict=True);out=args.out.resolve()
    if sha(unixnu/'drivers/DarwinBoot/Test/packed_ramdisk.py')!=PACKER_SHA:
        raise SystemExit('Expected pinned DBRDISK1 packer')
    # Exercise actual host APFS/ownership/conversion/packing before a 5 GiB fetch.
    from test_data_seed_r84 import macos_smoke
    macos_smoke(unixnu)
    out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(unixnu/'scripts'))
    from unixnu.ipsw import Ipsw
    import hashlib
    config=dict(url=URL,product='iPad7,1',version='17.7.11',build='21H461',
                device_class='j120ap',chip_id=32785,board_id=12,sha256={OS_FILE:OS_SHA})
    source=Ipsw(SimpleNamespace(board={'ipsw':config},out_root=out),spec=URL)
    if hashlib.sha256(source.zip.read('BuildManifest.plist')).hexdigest()!=MANIFEST_SHA:
        raise SystemExit('Original BuildManifest hash mismatch')
    if source.member('OS')!=OS_FILE:
        raise SystemExit('Original OS component differs')
    image=source.extract('OS')
    if image.stat().st_size!=5157406069 or sha(image)!=OS_SHA:
        raise SystemExit('Complete original OS.dmg hash/size mismatch')
    source.zip.close();source.stream.close()
    print('PASS: complete original OS.dmg size and SHA256', flush=True)
    mount=out/'os-mount';mount.mkdir()
    attached=plistlib.loads(subprocess.check_output(['hdiutil','attach','-readonly','-nobrowse',
        '-owners','on','-mountpoint',str(mount),'-plist',str(image)]))
    device=next(e['dev-entry'] for e in attached['system-entities'] if 'dev-entry' in e)
    try:
        entities=[e for e in attached['system-entities'] if e.get('mount-point')==str(mount)]
        if len(entities)!=1:raise ValueError('Expected one original read-only OS volume')
        report=create(SimpleNamespace(os_mount=mount,unixnu=unixnu,output=out/'seed',mib=512))
    finally:
        subprocess.run(['hdiutil','detach',device],check=True)
    (out/'ci-report.json').write_text(json.dumps(dict(original_os_sha256=OS_SHA,
        manifest_sha256=MANIFEST_SHA,seed=report,full_ipsw_downloaded=False,
        phone_written=False,boot_tested=False),indent=2)+'\n')
    print('PASS: local macOS seed created and verified; no phone or XNU boot tested')


if __name__=='__main__':main()
