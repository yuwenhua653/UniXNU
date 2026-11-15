#!/usr/bin/env python3
"""Reproduce the iOS27 ObjC ISA/PAC width conflict using real QEMU instructions.

This is a synthetic EL0 program with its own page tables, not a phone/kernel
boot. QEMU executes PACDA, AUTDA, translation, exceptions and TCR transitions.
Public synthetic keys are used; no instruction emulation hooks are installed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clang', type=Path, required=True)
    p.add_argument('--ld', type=Path, help='Optional explicit ld.lld executable')
    p.add_argument('--qemu', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--compile-only', action='store_true')
    a = p.parse_args()
    if not a.compile_only and a.qemu is None:
        p.error('--qemu is required unless --compile-only is selected')
    a.out.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('myron_user_va_pac.S')
    link = a.out / 'link.ld'
    link.write_text('ENTRY(_start)\nSECTIONS { . = 0x40080000; '
                    '.text : { *(.text) } .data : { *(.data) } '
                    '.bss (NOLOAD) : { *(.bss) } }\n')
    cases = [('pass', [], 0), ('wrong_final_width', ['-DFINAL_T0SZ=26'], 1),
             ('pac_disabled', ['-DENABLE_PAC=0'], 1)]
    results = []
    for name, defines, expected in cases:
        out = a.out / name
        out.mkdir(exist_ok=True)
        elf = out / 'va-pac.elf'
        command = [str(a.clang.resolve()), '--target=aarch64-none-elf',
                   '-nostdlib', '-fuse-ld=lld', '-Wl,-T,' + str(link.resolve())]
        if a.ld is not None:
            command += ['--ld-path=' + str(a.ld.absolute())]
        command += defines + [str(source.resolve()), '-o', str(elf.resolve())]
        build = subprocess.run(command, capture_output=True, text=True)
        (out / 'compile.log').write_text(build.stdout + build.stderr)
        if build.returncode:
            raise RuntimeError('AArch64 compile failed: ' + (out / 'compile.log').read_text())
        result = dict(name=name, compiled=True,
                      elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest())
        if a.compile_only:
            result['execution'] = 'not_run'
            results.append(result)
            continue
        q = [str(a.qemu.absolute()), '-M', 'virt', '-cpu', 'max', '-m', '256M',
             '-nodefaults', '-nographic', '-monitor', 'none', '-serial', 'none',
             '-semihosting-config', 'enable=on,target=native', '-kernel', str(elf.resolve())]
        try:
            r = subprocess.run(q, capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired as exc:
            (out / 'output.log').write_bytes((exc.stdout or b'') + (exc.stderr or b''))
            raise RuntimeError(name + ': QEMU timed out; no passing result') from exc
        log = r.stdout + r.stderr
        (out / 'output.log').write_text(log)
        if r.returncode != expected:
            raise AssertionError(f'{name}: exit {r.returncode}, expected {expected}\n{log}')
        if expected == 0:
            assert 'PASS: real EL0 PAC' in log and 'FAIL:' not in log, log
            fields = {k: int(v, 16) for k, v in
                      re.findall(r'^([A-Z_]+)=([0-9a-f]{16})$', log, re.M)}
            assert set(fields) == {'OLD_SIGNED', 'OLD_MASKED', 'MODIFIER', 'OLD_FAR',
                                   'OLD_ESR', 'OLD_TCR', 'NEW_SIGNED', 'NEW_MASKED',
                                   'NEW_TCR', 'AUTH_TRAPS'}, fields
            target = 0x1e9d71f70
            mask = 0x7fffffffff8
            assert fields['OLD_MASKED'] == fields['OLD_SIGNED'] & mask
            assert fields['OLD_MASKED'] != target
            assert fields['OLD_MASKED'] & ((1 << 38) - 1) == target
            assert fields['OLD_FAR'] == fields['OLD_MASKED']
            assert fields['OLD_ESR'] >> 26 == 0x24
            assert fields['OLD_ESR'] & 0x3f <= 7
            assert fields['NEW_MASKED'] == fields['NEW_SIGNED'] & mask == target
            assert fields['OLD_TCR'] & 63 == 26 and fields['NEW_TCR'] & 63 == 21
            assert (fields['OLD_TCR'] >> 16) & 63 == (fields['NEW_TCR'] >> 16) & 63 == 26
            assert fields['OLD_TCR'] ^ fields['NEW_TCR'] == 26 ^ 21
            result.update(execution='passed', observations={k: hex(v) for k, v in fields.items()})
        else:
            assert 'FAIL: VA/PAC reproducer invariant' in log and 'PASS:' not in log, log
            result.update(execution='rejected_as_expected', returncode=r.returncode)
        results.append(result)
    report = dict(result='compile_only' if a.compile_only else 'passed', cases=results,
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  real_pac_instructions=True, instruction_hooks_used=False,
                  el0_and_mmu_executed=not a.compile_only,
                  kernel_geometry_unchanged=None if a.compile_only else True,
                  user_va_bits_before=38, user_va_bits_after=43,
                  kernel_va_bits=38, phone_tested=False,
                  limitations='Synthetic QEMU program, not XNU or Qualcomm hardware execution')
    if a.qemu is not None and not a.compile_only:
        report['qemu_version'] = subprocess.check_output(
            [str(a.qemu.absolute()), '--version'], text=True).splitlines()[0]
    (a.out / 'user-va-pac.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
