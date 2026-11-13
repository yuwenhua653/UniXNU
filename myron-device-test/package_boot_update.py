#!/usr/bin/env python3
"""Assemble only the pinned diagnostic boot plus isolated host tools."""
import argparse
from pathlib import Path
import zipfile
import myron_boot_update as u


def package(update, output):
    update, output = Path(update), Path(output)
    u.verify_release(update)
    source = Path(__file__).resolve().parent
    prefix = 'boot-update-'+str(u.RUN)+'/'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name in ('UPDATE-BOOT.cmd', 'UPDATE-BOOT-README-CN.txt'):
            data=(source/name).read_text(encoding='utf-8').replace('\r\n','\n').replace('\n','\r\n')
            z.writestr(name,data.encode('utf-8'))
        for name in ('myron_boot_update.py','myron_device_test.py','device_layout.py','prepare_root_bundle.py'):
            z.write(source/name,prefix+name)
        for name in ('deployment.json','root-startup.img'):
            z.write(update/name,prefix+name)
    with zipfile.ZipFile(output) as z:
        u.t.require(z.testzip() is None, 'Output ZIP integrity failed')
    print(str(output)+': '+str(output.stat().st_size)+' bytes SHA256 '+u.t.sha(output))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); package(a.input,a.output)
