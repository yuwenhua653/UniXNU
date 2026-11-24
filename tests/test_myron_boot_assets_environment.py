#!/usr/bin/env python3
"""Run reconstructed boot-asset tests with plain and production-like environments."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--device',type=Path,required=True)
p.add_argument('--darwinboot',type=Path,required=True)
a=p.parse_args()
command=[sys.executable,str(a.device/'tests/test_boot_assets.py'),
         '--darwinboot',str(a.darwinboot),'-v']
plain=dict(os.environ)
for name in ('MYRON_GPU_NATIVE','MYRON_PACKED_KERNEL','MYRON_METAL_ARTIFACT'):
    plain.pop(name,None)
with tempfile.TemporaryDirectory(prefix='myron-boot-env-') as tmp:
    # Deliberately absent: fixture tests must not open the build's real archive.
    archive=Path(tmp)/'not-a-test-input.zip'
    production=dict(plain,MYRON_GPU_NATIVE='1',MYRON_PACKED_KERNEL='1',
                    MYRON_METAL_ARTIFACT=str(archive))
    for label,environment in [('plain',plain),('production',production)]:
        print('Checking boot assets with '+label+' environment',flush=True)
        subprocess.run(command,check=True,env=environment)
    assert not archive.exists()
print('PASS: boot fixtures isolate build inputs; explicit Metal requests retain audit guards')
