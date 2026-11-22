#!/usr/bin/env python3
"""Exercise portable myron GPU components; never touches hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cc', default='cc')
    p.add_argument('--firmware', type=Path, help='Local extracted 3.0.306 directory; all four pins are required')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    firmware_pins = json.loads((HERE / 'firmware-3.0.306.json').read_text())['files']
    if a.firmware:
        for name, info in firmware_pins.items():
            data = (a.firmware / name).read_bytes()
            if len(data) != info['bytes'] or hashlib.sha256(data).hexdigest() != info['sha256']:
                raise SystemExit('Firmware mismatch: ' + name)
    results = {}
    # Upstream fake hardware lives for the test process. Disable leak reporting
    # for those retained fixtures; ASan bounds and UBSan checks remain active.
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0')
    with tempfile.TemporaryDirectory(prefix='myron-gpu-host-') as tmp:
        for component in ('GpuBoard', 'CmdDb', 'Gmu', 'Hfi'):
            files = [HERE / ('Myron' + component + 'Tests.c')]
            if component != 'GpuBoard':
                files.append(HERE / ('Myron' + component + '.c'))
            binary = Path(tmp) / component
            command = [a.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                       '-fno-sanitize-recover=all', *map(str, files), '-o', str(binary)]
            subprocess.run(command, check=True)
            args = [str(binary)]
            if component == 'Gmu' and a.firmware:
                args.append(str((a.firmware / 'gen80200_gmu.bin').resolve()))
            results[component] = subprocess.check_output(args, env=env, text=True).strip()
            if a.firmware:
                results[component] = results[component].replace(str(a.firmware.resolve()), '<firmware>')
    report = dict(host_tests=results, firmware_pins_verified=bool(a.firmware), hardware_tested=False,
                  files_sha256={x.name: hashlib.sha256(x.read_bytes()).hexdigest()
                                for x in sorted(HERE.glob('Myron*')) if x.suffix in ('.c', '.h')})
    a.output.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: four portable component suites; GPU runtime remains untested')


if __name__ == '__main__':
    main()
