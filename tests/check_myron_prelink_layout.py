#!/usr/bin/env python3
"""Apply the exact board prelink series and exercise layout rejection cases."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True, type=Path)
    parser.add_argument('--xnuprelink', required=True, type=Path)
    args = parser.parse_args()
    tool = args.xnuprelink.resolve()
    revision = subprocess.check_output(['git', '-C', str(tool), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != 'b74ed7c74a07f0eb5f81089c660905ecc4cabb7f':
        raise SystemExit('Unexpected XnuPrelink revision')
    patches = sorted((args.device/'patches/xnuprelink').glob('*.patch'))
    if not patches or patches[-1].name != 'zzzzz-constant-marker.patch':
        raise SystemExit('Missing final constant-marker patch')
    for patch in patches:
        command = ['git', '-C', str(tool), 'apply']
        if subprocess.run(command + ['--reverse', '--check', str(patch.resolve())], capture_output=True).returncode:
            subprocess.run(command + ['--check', str(patch.resolve())], check=True)
            subprocess.run(command + [str(patch.resolve())], check=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'test_fileset_layout', '-v'], cwd=tool, check=True)


if __name__ == '__main__':
    main()
