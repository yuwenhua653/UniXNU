#!/usr/bin/env python3
"""Assemble the fresh-PC helper with the exact checked build and Windows tools."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
import fresh_boot as helper

RUNTIME_SHA = '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'
TOOLS_SHA = '45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','runtime','platform-tools','vnode-report','output'):
        p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();source=Path(__file__).resolve().parent
    helper.verify_release(a.candidate)
    report=json.loads(a.vnode_report.read_text())
    continuous=json.loads((a.candidate/'continuous-report.json').read_text())
    assert report['candidate_sha256']==continuous['kernel_sha256']
    assert (report['sites_checked'],report['descriptors_checked'],report['mismatches'])==(189,56,[])
    for path,expected in ((a.runtime,RUNTIME_SHA),(a.platform_tools,TOOLS_SHA)):
        assert helper.io.sha(path)==expected
    with tempfile.TemporaryDirectory(prefix='myron-fresh-package-') as tmp:
        root=Path(tmp)/('myron-ios27-fresh-pc-'+str(helper.RUN));root.mkdir()
        app=root/'app';app.mkdir();payload=root/'payload';payload.mkdir();proof=root/'verification';proof.mkdir()
        for name in ('fresh_boot.py','device_io.py','device_layout.py','prepare_root_bundle.py'):
            shutil.copyfile(source/name,app/name)
        for name in ('START-IOS27.cmd','RESTORE-ANDROID.cmd','README-CN.txt'):
            text=(source/name).read_text().replace('\r\n','\n').replace('\n','\r\n')
            (root/name).write_bytes(text.encode('utf-8'))
        for name in ('deployment.json','continuous-report.json','root-startup.img'):
            shutil.copyfile(a.candidate/name,payload/name)
        shutil.copyfile(a.vnode_report,proof/'apfs-vnode-bindings.json')
        with zipfile.ZipFile(a.runtime) as z:
            assert z.testzip() is None
            assert all(not Path(i.filename).is_absolute() and '..' not in Path(i.filename).parts for i in z.infolist())
            z.extractall(root/'runtime')
        (root/'runtime/python313._pth').write_text('python313.zip\n.\n../app\n',encoding='ascii')
        with zipfile.ZipFile(a.platform_tools) as z:
            assert z.testzip() is None
            names=['adb.exe','fastboot.exe','AdbWinApi.dll','AdbWinUsbApi.dll',
                   'libwinpthread-1.dll','NOTICE.txt','source.properties']
            (root/'platform-tools').mkdir()
            for name in names:(root/'platform-tools'/name).write_bytes(z.read('platform-tools/'+name))
        checks=dict(run=helper.RUN,source_commit=continuous['assembly_commit'],
                    final_boot_sha256=helper.BOOT_SHA,kernel_sha256=continuous['kernel_sha256'],
                    apfs_vnode_sites=189,apfs_vnode_mismatches=0,buffer_hooks=9,
                    fresh_pc_simulated_tests=13,reused_transport_regression_tests=19,
                    requires_old_pc_files=False,requires_existing_phone_unixnu=True,
                    backup_source='fresh connected device, current Android slot, double-read SHA256',
                    root_check='fresh full read-only root and carrier SHA256 on recovery',
                    python_runtime_sha256=RUNTIME_SHA,platform_tools_archive_sha256=TOOLS_SHA,
                    phone_tested=False,desktop_reached=False,windows_runtime_executed_here=False)
        (proof/'build-checks.json').write_text(json.dumps(checks,indent=2)+'\n')
        files=sorted(x for x in root.rglob('*') if x.is_file())
        (root/'FILES-SHA256.txt').write_text(''.join(helper.io.sha(x)+'  '+x.relative_to(root).as_posix()+'\n' for x in files))
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(a.output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for path in sorted(x for x in root.rglob('*') if x.is_file()):z.write(path,root.name+'/'+path.relative_to(root).as_posix())
        with zipfile.ZipFile(a.output) as z:
            assert z.testzip() is None
            assert not any('/state/' in x or '/__pycache__/' in x for x in z.namelist())
            z.extractall(Path(tmp)/'readback')
        restored=Path(tmp)/'readback'/root.name
        for line in (restored/'FILES-SHA256.txt').read_text().splitlines():
            digest,relative=line.split('  ',1);assert helper.io.sha(restored/relative)==digest
        subprocess.run([sys.executable,str(restored/'app/fresh_boot.py'),'check'],check=True)
        assert not (restored/'state').exists()
        assert (restored/'runtime/python313._pth').read_text().splitlines()==['python313.zip','.','../app']
    print(json.dumps(dict(file=str(a.output.resolve()),bytes=a.output.stat().st_size,sha256=helper.io.sha(a.output)),indent=2))


if __name__=='__main__':main()
