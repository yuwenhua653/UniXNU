#!/usr/bin/env python3
"""Exercise the exact qualified binary, corruption rejection, and FAT round trip."""
import argparse
import hashlib
from pathlib import Path
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import myron27_idle_compat as compat
from pyfatfs.PyFatFS import PyFatFS

def reject(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError('Invalid input was accepted')

p = argparse.ArgumentParser()
p.add_argument('--boot', type=Path, required=True)
a = p.parse_args()
boot = a.boot.read_bytes()
assert len(boot) == 95428608
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)/'payload.img'
    path.write_bytes(boot[0x302000:])
    with PyFatFS(str(path), read_only=True) as fs:
        inventory = {n: compat.sha(fs.readbytes(n)) for n in fs.walk.files()}
        kernel = fs.readbytes('EFI/UniXNU/Payloads/kernel.macho')
    derived, report = compat.patch_kernel(kernel)
    assert compat.sha(derived) == compat.OUTPUT_SHA
    assert [i for i,(x,y) in enumerate(zip(kernel,derived)) if x != y] == [compat.OFFSET]
    # The compiled consumer must still load this scalar and branch over WFE.
    # Pinned original native code: __TEXT_EXEC virtual/file offset mapping.
    command = 1474560+32
    sections = []
    for _ in range(struct.unpack_from('<I',kernel,1474560+16)[0]):
        kind, length = struct.unpack_from('<II',kernel,command)
        if kind == 0x19:
            va, _, off, size = struct.unpack_from('<4Q',kernel,command+24)
            target = 0xfffffff00a392e1c
            if va <= target < va+size:
                begin = off+target-va
                code = kernel[begin:begin+276]
                assert hashlib.sha256(code).hexdigest() == '51e31ce7cea0744b4407aaf1a839330a13d9591619609574a1e27b5260672ddd'
                assert derived[begin:begin+276] == code
                sections.append(begin)
        command += length
    assert len(sections) == 1
    reject(lambda: compat.patch_kernel(kernel[:-1]))
    reject(lambda: compat.patch_kernel(derived))  # no accidental double application
    reject(lambda: compat.patch_kernel(bytes([kernel[0]^1])+kernel[1:]))
    damaged = bytearray(kernel)
    struct.pack_into('<i',damaged,1477336+60,7)  # unexpectedly executable data
    reject(lambda: compat.mapped_scalar(damaged))
    damaged = bytearray(kernel)
    struct.pack_into('<Q',damaged,1477336+40,0)  # inconsistent file mapping
    reject(lambda: compat.mapped_scalar(damaged))
    with PyFatFS(str(path)) as fs:
        with fs.openbin('EFI/UniXNU/Payloads/kernel.macho','r+') as file:
            file.seek(compat.OFFSET)
            assert file.write(b'\0\0\0\0') == 4
    with PyFatFS(str(path),read_only=True) as fs:
        after = {n:compat.sha(fs.readbytes(n)) for n in fs.walk.files()}
        assert fs.readbytes('EFI/UniXNU/Payloads/kernel.macho') == derived
    inventory['/EFI/UniXNU/Payloads/kernel.macho'] = compat.OUTPUT_SHA
    assert inventory == after
    assert path.stat().st_size == 92274688
print('PASS: exact native consumer, one-byte derivative, five corruption/double-application guards, all FAT files and fixed size')
