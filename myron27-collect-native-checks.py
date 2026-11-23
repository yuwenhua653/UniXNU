#!/usr/bin/env python3
"""Stage build diagnostics without traversing mounted/private root images."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

EXCLUDED = {'private-userland', 'root-media', 'device-package', '.cache', '.git',
            'references', 'refer', 'node_modules', 'myron-private-inputs'}
NAMES = {'system-apps-plan.json', 'setup-seed-check.json', 'desktop-integration.json', 'native-link.log', 'build-report.json',
         'root-preflight.json', 'display-abi.json', 'display-build.json',
         'storage-abi.json', 'ram-storage-abi.json', 'gpu-build.json',
         'gpu-native-host.json', 'gpu-portable.json'}

def replay_input(relative):
    """Only source-built native kernels/LTO references, never donor images."""
    parts = relative.parts
    if tuple(parts[-5:]) == ('desktop','ufs','root','kernel','kernel.macho'):
        return True
    return ('out' in parts and relative.parent.name == 'fileset-reference'
            and relative.name.endswith('.noctf'))
def collect(temp, output):
    temp, output = Path(temp), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    saved, errors, replay = [], [], {}
    def onerror(error): errors.append(str(error))
    for name in ('myron-iphone27', 'myron-private-native'):
        root=temp/name
        if not root.is_dir() or root.is_symlink(): continue
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            parent=Path(directory)
            dirs[:]=sorted(d for d in dirs if d not in EXCLUDED and not (parent/d).is_symlink())
            for name in sorted(files):
                path=parent/name
                if path.is_symlink(): continue
                relative=path.relative_to(temp)
                is_replay = replay_input(relative)
                selected=(name in NAMES or name.endswith(('compile.log','preflight.log')) or
                          (parent.name == 'desktop' and
                           (name.endswith('.log') or '-prelink' in name and name.endswith('.json'))) or
                          (name.endswith('.log') and parent.name in ('logs','reports')) or is_replay)
                if not selected: continue
                try:
                    if not path.is_file() or path.stat().st_size > (256 if is_replay else 64)*1024*1024: continue
                    dest=output/relative;dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(path,dest);saved.append(relative.as_posix())
                    if is_replay:
                        with dest.open('rb') as stream:
                            digest = hashlib.file_digest(stream,'sha256').hexdigest()
                        replay[relative.as_posix()] = dict(bytes=dest.stat().st_size,
                            sha256=digest)
                except OSError as error: onerror(error)
    result=dict(files=saved,errors=errors,excluded_directories=sorted(EXCLUDED),
                source_built_replay_inputs=replay)
    (output/'collection.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'Diagnostic files staged: {len(saved)}; collection warnings: {len(errors)}')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--temp',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();collect(a.temp,a.output)

