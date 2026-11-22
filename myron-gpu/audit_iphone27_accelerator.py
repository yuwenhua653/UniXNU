#!/usr/bin/env python3
"""Audit the iPhone12,1 24A446 IOAcceleratorES in a final myron fileset.

This emits bindings, not a device or a hardware-success claim. The original
addresses belong to this donor only. Native IOService symbols are resolved
again on each build, including the authenticated chained-fixup metadata.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

META = 0xfffffff00af6ac58
VTABLE = 0xfffffff007fea6a0
CTOR = (0xfffffff009924850, 0xfffffff009924888)
DTOR = 0xfffffff0099248c0
GET_META = 0xfffffff009924930
INIT = 0xfffffff00992962c


def require(ok, message):
    if not ok:
        raise ValueError(message)


def audit(data, image_type):
    image = image_type(data)
    native = image_type(data, image.entries['com.apple.kernel'][1])
    names = {name: addr for addr, group in native.symbols().items() for name in group}
    fixups = image.fixups()
    entries = 168
    parent = names['__ZTV9IOService'] + 16
    differences = []
    for slot in range(entries):
        site = VTABLE + 16 + slot * 8
        a, b = fixups[site], fixups[parent + slot * 8]
        require(a[1:] == b[1:], f'Vtable slot {slot}: PAC contract differs')
        if a[0] != b[0]:
            differences.append(slot)
    require(differences == [0, 1, 7], 'Unexpected operational override')
    require(image.read(VTABLE + 16 + entries * 8, 8) == bytes(8), 'Vtable extent')
    require(fixups[VTABLE + 16][0] == DTOR + 8, 'Destructor alias')
    require(fixups[VTABLE + 16 + 8][0] == DTOR + 16, 'Deleting destructor')
    require(fixups[VTABLE + 16 + 7 * 8][0] == GET_META, 'Metaclass getter')
    require(image.read(0xfffffff00784224d, 16) == b'IOAcceleratorES\0', 'Class name')
    # The complete constructor bodies, including BTI, PAC and the real parent
    # call; an address or ABI change fails closed rather than guessing a stub.
    code = {
        CTOR[0]: '5f2403d57f2303d5fd7bbfa9fd030091c84d00943036ffd010821a9110420091f10300aa31b4f9f2300ac1da100000f9fd7bc1a8ff0f5fd6',
        CTOR[1]: '5f2403d57f2303d5fd7bbfa9fd030091ba4d00943036ffd010821a9110420091f10300aa31b4f9f2300ac1da100000f9fd7bc1a8ff0f5fd6',
        DTOR: '5f2403d5b34d00145f2403d5b14d0014',
        GET_META: '5f2403d520b200d000603191c0035fd6',
        INIT: '7f2303d5f44fbea9fd7b01a9fd43009113b200b073623191c1f8feb0213409912236ffb042cc46f9e00313aa03118052e9380094',
        0xfffffff009937f80: 'b135fff031422991300240f9110a1fd7b135fff031622991300240f9110a1fd7',
    }
    for addr, expected in code.items():
        expected = bytes.fromhex(expected)
        require(image.read(addr, len(expected)) == expected, f'Original code changed at {addr:#x}')
    for site, symbol in [
        (0xfffffff007feea50, '__ZN9IOServiceC2EPK11OSMetaClass'),
        (0xfffffff007feea58, '__ZN9IOServiceD2Ev'),
    ]:
        require(fixups[site] == (names[symbol], 1, 0, 0, 1), f'Authenticated parent import: {symbol}')
    require(fixups[0xfffffff007feed98] == (names['__ZN9IOService10gMetaClassE'], 0, None, None, None), 'Real parent metaclass')
    return dict(
        final_kernel_sha256=hashlib.sha256(data).hexdigest(),
        target='iPhone12,1/24A446', collection_slide='0x0',
        metaclass=hex(META), instance_bytes=136, virtual_entries=entries,
        operational_overrides=[], metadata_overrides=differences,
        protected_compatible_constructor_aliases=[hex(x) for x in CTOR],
        nondeleting_destructor=hex(DTOR), get_meta_class=hex(GET_META),
        vtable=hex(VTABLE), native_parent_vtable=hex(parent - 16),
        original_code_sha256={hex(a): hashlib.sha256(bytes.fromhex(s)).hexdigest() for a, s in code.items()},
        native_parent_imports_checked=True, authenticated_vtable_entries_checked=entries,
        accelerator_instantiated=False, gpu_hardware_tested=False, metal_runtime_tested=False,
    )


def negative_controls(data, image_type):
    image = image_type(data)
    # Real binary mutations: reject a changed constructor, a corrupted class
    # size, and an operational vtable entry replaced by the destructor slot.
    cases = [(CTOR[0], b'\0\0\0\0'), (INIT + 44, bytes(4)),
             (VTABLE + 16 + 2 * 8, image.read(VTABLE + 16, 8))]
    for addr, replacement in cases:
        changed = bytearray(data)
        offset = image.offset(addr, len(replacement))
        changed[offset:offset + len(replacement)] = replacement
        try:
            audit(bytes(changed), image_type)
        except (ValueError, KeyError):
            continue
        raise ValueError(f'Negative control accepted {addr:#x}')
    return len(cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--kernel-sha256', required=True, help='Digest from the matching package manifest')
    parser.add_argument('--xnuprelink', type=Path, required=True, help='Directory containing kc_image.py')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--negative-controls', action='store_true')
    args = parser.parse_args()
    data = args.kernel.read_bytes()
    require(hashlib.sha256(data).hexdigest() == args.kernel_sha256.lower(), 'Final kernel digest mismatch')
    sys.path.insert(0, str(args.xnuprelink.resolve()))
    from kc_image import Image
    report = audit(data, Image)
    if args.negative_controls:
        report['binary_negative_controls_passed'] = negative_controls(data, Image)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: iPhone27 IOAcceleratorES, 136 bytes, 168 PAC-compatible slots; hardware untested')


if __name__ == '__main__':
    main()
