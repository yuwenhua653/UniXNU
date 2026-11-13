#!/usr/bin/env python3
"""Stage build diagnostics without traversing mounted/private root images."""
import argparse
import json
import os
from pathlib import Path
import shutil

EXCLUDED = {'private-userland', 'root-media', 'device-package', '.cache', '.git',
            'references', 'refer', 'node_modules', 'myron-private-inputs'}
NAMES = {'desktop-integration.json', 'native-link.log', 'build-report.json'}
def collect(temp, output):
    temp, output = Path(temp), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    saved, errors = [], []
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
                selected=(name in NAMES or name.endswith(('compile.log','preflight.log')) or
                          (name.endswith('.log') and parent.name in ('logs','reports')))
                if not selected: continue
                try:
                    if not path.is_file() or path.stat().st_size > 64*1024*1024: continue
                    dest=output/relative;dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(path,dest);saved.append(relative.as_posix())
                except OSError as error: onerror(error)
    result=dict(files=saved,errors=errors,excluded_directories=sorted(EXCLUDED))
    (output/'collection.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'Diagnostic files staged: {len(saved)}; collection warnings: {len(errors)}')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--temp',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();collect(a.temp,a.output)
