#!/usr/bin/env python3
"""Negative controls for the emitted user-VA geometry/TCR verifier.

Small AArch64 byte fixtures exercise the verifier, not XNU runtime behavior.
The actual native kernel is checked separately by verify_native_artifact.py.
"""
import argparse
import importlib.util
from pathlib import Path
import struct


def load(device):
    spec = importlib.util.spec_from_file_location('native_va_checker', device / 'verify_native_artifact.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    data = bytearray(2048)
    segments = [(0x1000, 0, 1024), (0x2000, 1024, 1024)]
    executable = segments[:1]
    syms = dict(_gT0Sz=0x2000, _gT1Sz=0x2008, _pmap_pt_attr_4k=0x2040,
                _pmap_pt_attr_4k_kernel=0x20c0, _set_tcr=0x1300,
                _arm_vm_init=0x1000, _arm_init_cpu=0x1100, _arm_init_idle_cpu=0x1200)
    starts = [0x1000, 0x1100, 0x1200, 0x1300, 0x1310]
    # A 4K/4K final TCR, including a high bit requiring several MOVK instructions.
    tcr = (1 << 51) | (1 << 37) | (2 << 32) | (2 << 30) | (26 << 16) | 21
    struct.pack_into('<QQ', data, 1024, 21, 26)
    for address, root, mask in ((0x2040, 0, 0x7ffffffffff), (0x20c0, 1, 0x3fffffffff)):
        at = 1024 + address - 0x2000
        struct.pack_into('<III', data, at + 64, root, 1, 3)
        struct.pack_into('<5Q', data, at + 80, tcr, 4096, 4096, 12, mask)
    for start in starts[:3]:
        words = [0xd2800000 | ((tcr & 0xffff) << 5)]
        for shift in (16, 32, 48):
            words.append(0xf2800000 | ((shift // 16) << 21) | (((tcr >> shift) & 0xffff) << 5))
        site = start + len(words) * 4
        words.append(0x94000000 | (((0x1300 - site) // 4) & 0x3ffffff))
        words.append(0xd65f03c0)
        struct.pack_into('<' + 'I' * len(words), data, start - 0x1000, *words)
    struct.pack_into('<4I', data, 0x300, 0xd5182040, 0xd5033fdf, 0xd65f03c0, 0xd503201f)
    return data, segments, executable, syms, starts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True, type=Path)
    args = parser.parse_args()
    module = load(args.device)
    count = 0

    def rejected(label, mutate):
        nonlocal count
        case = fixture()
        mutate(*case)
        try:
            module.verify_user_va(*case)
        except ValueError:
            count += 1
            return
        raise AssertionError('Verifier accepted: ' + label)

    case = fixture()
    result = module.verify_user_va(*case)
    assert result['runtime_user_va_bits'] == 43 and result['kernel_va_bits'] == 38
    assert len(result['emitted_final_tcr_transitions']) == 3
    assert result['execution_verified'] is False and result['pointer_selection_verified'] is False
    rejected('old 38-bit user width', lambda d, *_: struct.pack_into('<Q', d, 1024, 26))
    rejected('kernel widened to 43 bits', lambda d, *_: struct.pack_into('<Q', d, 1032, 21))
    rejected('user still uses L1', lambda d, *_: struct.pack_into('<I', d, 1024 + 0x40 + 64, 1))
    rejected('kernel moved to L0', lambda d, *_: struct.pack_into('<I', d, 1024 + 0xc0 + 64, 0))
    rejected('kernel mask widened', lambda d, *_: struct.pack_into('<Q', d, 1024 + 0xc0 + 112, 0x7ffffffffff))
    rejected('user mask still 38 bits', lambda d, *_: struct.pack_into('<Q', d, 1024 + 0x40 + 112, 0x3fffffffff))
    rejected('page size changed', lambda d, *_: struct.pack_into('<Q', d, 1024 + 0x40 + 88, 16384))
    rejected('disabled TTBR0', lambda d, *_: d.__setitem__(1024 + 0x40 + 80, d[1024 + 0x40 + 80] | 0x80))
    rejected('setter has no actual MSR', lambda d, *_: struct.pack_into('<I', d, 0x300, 0xd503201f))
    rejected('setter omits ISB', lambda d, *_: struct.pack_into('<I', d, 0x304, 0xd503201f))
    rejected('old runtime T0SZ passed on CPU resume', lambda d, *_: struct.pack_into('<I', d, 0x200, 0xd2800340))
    rejected('missing CPU resume call', lambda d, *_: struct.pack_into('<I', d, 0x210, 0xd503201f))
    rejected('wrong call target', lambda d, *_: struct.pack_into('<I', d, 0x110, 0x94000000))
    rejected('unproved x0 load', lambda d, *_: struct.pack_into('<I', d, 0, 0xf9400020))
    rejected('intervening call clobbers x0', lambda d, *_: struct.pack_into('<I', d, 0x00c, 0x94000000))
    rejected('runtime call moved into another function', lambda d, s, e, y, f: f.insert(1, 0x1010))
    rejected('missing cold function boundary', lambda d, s, e, y, f: f.remove(0x1000))
    rejected('kernel attributes alias user attributes', lambda d, s, e, y, f: y.__setitem__('_pmap_pt_attr_4k_kernel', y['_pmap_pt_attr_4k']))
    rejected('missing compiled global', lambda d, s, e, y, f: y.pop('_gT0Sz'))
    rejected('truncated executable bytes', lambda d, s, e, y, f: d.__delitem__(slice(0x305, None)))

    def duplicate_call(d, *_):
        at = 0x18
        struct.pack_into('<I', d, at, 0x94000000 | ((0x1300 - (0x1000 + at)) // 4))
    rejected('duplicate final transition', duplicate_call)

    # Decode independently specified instruction encodings for alternate
    # immediate idioms and reject MOVK-only sequences without an initial value.
    assert module.logical_immediate(0xb2781fe0) == 0xff00  # orr x0,xzr,#0xff00
    assert module.immediate_x0_before_call(struct.pack('<2I', 0xb2781fe0, 0xf2c00020), [(0x1000, 0, 8)], 0x1000, 0x1008) == 0x10000ff00
    assert module.immediate_x0_before_call(struct.pack('<I', 0x92800000), [(0x1000, 0, 4)], 0x1000, 0x1004) == 0xffffffffffffffff
    assert module.immediate_x0_before_call(struct.pack('<2I', 0x528002a0, 0x72a00340), [(0x1000, 0, 8)], 0x1000, 0x1008) == 0x1a0015
    for raw in (struct.pack('<I', 0xf28002a0), struct.pack('<I', 0xd503201f)):
        try:
            module.immediate_x0_before_call(raw, [(0x1000, 0, len(raw))], 0x1000, 0x1000 + len(raw))
        except ValueError:
            count += 1
        else:
            raise AssertionError('Uninitialized immediate sequence accepted')

    assert module.decode_function_starts(bytes([4, 8, 0, 0]), (0, 4), 0x1000) == [0x1004, 0x100c]
    for raw in (bytes([0x80]), bytes([4]), bytes([0, 1]), bytes([3, 0]), bytes([0xff] * 10 + [0])):
        try:
            module.decode_function_starts(raw, (0, len(raw)), 0x1000)
        except ValueError:
            count += 1
        else:
            raise AssertionError('Invalid function-start data accepted')
    print(f'PASS native user-VA geometry gate: compiled scalar fixture, all 3 TCR calls, immediate decoder; {count} negative controls')


if __name__ == '__main__':
    main()
