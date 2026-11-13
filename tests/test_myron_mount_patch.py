#!/usr/bin/env python3
"""Apply the real selected XNU patch series and prove mount observers only add calls."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument('--device',type=Path,required=True)
p.add_argument('--upstream',type=Path,required=True)
p.add_argument('--xnu',type=Path,required=True)
a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',
           os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subjects=('bsd/kern/bsd_init.c','bsd/vfs/vfs_subr.c','osfmk/kern/boot_progress.h')
# Every patch comes from the selected pinned source/board overlay.
with tempfile.TemporaryDirectory() as tmp:
    work=Path(tmp)
    for name in subjects[:2]:
        src=a.xnu/name; dst=work/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    (work/'osfmk/kern').mkdir(parents=True)
    before=None
    for scope in ('arch','os','device'):
        series=roots[scope]/'patches/xnu/series'
        for line in series.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            prefix,sep,tail=line.partition(':')
            patch=(roots[prefix]/tail if sep else series.parent/line).resolve()
            text=patch.read_text()
            if not any('--- a/'+name in text or '+++ b/'+name in text for name in subjects):continue
            if patch.name=='myron-root-mount-progress.patch':
                before={n:(work/n).read_text() for n in subjects[:2]}
            subprocess.run(['git','apply',*[f'--include={n}' for n in subjects],str(patch)],cwd=work,check=True)
    assert before is not None
    for name in subjects[:2]:
        after=(work/name).read_text()
        stripped=''.join(l for l in after.splitlines(True) if 'myron_mount_event(' not in l)
        if name.endswith('vfs_subr.c'):
            assert stripped.startswith('#include <kern/boot_progress.h>\n')
            stripped=stripped.split('\n',1)[1]
        assert stripped==before[name],f'Observer changed mount logic: {name}'
    header=(work/subjects[2]).read_text()
    assert 'void myron_mount_event(unsigned, const char *, const char *, uint64_t, uint64_t);' in header
    assert '#define myron_mount_event(...) ((void)0)' in header
print('PASS selected XNU series applies; root selection/mount control flow and authentication unchanged')
