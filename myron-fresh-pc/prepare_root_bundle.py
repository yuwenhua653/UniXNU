#!/usr/bin/env python3
"""Validate existing signed OS/SystemOS windows and emit private UFS inputs.

No keys are generated, no partition is created, no device is opened and no boot
mode is enabled. The root container and independent trusted key are inputs.
Native publication still requires separate crypto/root ABI integration.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import uuid

VR_BLOBS = {
    'src/verified_root.c': 'ca6344df261a18c53dbefc8e51e4037d276cff23',
    'tests/openssl_provider.c': 'd0c6691d4c75aac8098e24010753732d6a1e0044',
    'include/verified_root.h': 'ef89d334c557ebbd746b89fe1dfa20684accc32e',
}
GEOMETRY_KEYS = {'first', 'last', 'diskLast', 'carrierOffset', 'carrierCapacity',
                 'reserveBlocks', 'partitionGuid'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def check_geometry(g):
    require(set(g) == GEOMETRY_KEYS, 'Geometry fields must be explicit and exact')
    for name in GEOMETRY_KEYS - {'partitionGuid'}:
        require(type(g[name]) is int and 0 <= g[name] <= 0xffffffffffffffff,
                'Invalid geometry integer: ' + name)
    require(6 <= g['first'] <= g['last'] < g['diskLast'] <= 0xffffffff and
            g['diskLast'] - g['last'] >= 5, 'GPT/READ(10) geometry is out of bounds')
    blocks = g['last'] - g['first'] + 1
    reserve = g['reserveBlocks']
    require(0 < reserve <= 16384 * 256 and reserve % 256 == 0 and reserve < blocks,
            'Reserve must be integral MiB and smaller than the partition')
    offset, capacity, size = g['carrierOffset'], g['carrierCapacity'], blocks * 4096
    require(offset % 4096 == 0 and capacity % 4096 == 0 and
            4096 <= capacity <= 128 * 1024 * 1024 and
            (blocks - reserve) * 4096 <= offset < size and capacity <= size - offset,
            'Policy carrier must fit wholly inside the reserved tail')
    guid = uuid.UUID(g['partitionGuid'])
    require(guid.int != 0, 'Partition GUID cannot be zero')
    return (blocks - reserve) * 4096, guid.bytes_le


class View(C.Structure):
    _fields_ = [('hashes', C.c_void_p), ('image_bytes', C.c_uint64),
                ('block_count', C.c_uint64), ('generation', C.c_uint64),
                ('volume_uuid', C.c_ubyte * 16), ('image_sha256', C.c_ubyte * 32)]


def verifier(source, out, cc, openssl):
    for name, expected in VR_BLOBS.items():
        raw = (source / name).read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        require(actual == expected, 'Unreviewed VerifiedRoot source: ' + name)
    library = out / ('verified-root.dylib' if sys.platform == 'darwin' else 'verified-root.so')
    command = [cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-fPIC',
               '-dynamiclib' if sys.platform == 'darwin' else '-shared',
               '-I', str(source / 'include'), '-I', str(openssl / 'include'),
               str(source / 'src/verified_root.c'), str(source / 'tests/openssl_provider.c'),
               '-L', str(openssl / 'lib'), '-lcrypto', '-o', str(library)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    lib = C.CDLL(str(library))
    lib.vr_host_open.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p,
                                 C.c_uint64, C.POINTER(View)]
    lib.vr_host_open.restype = C.c_int
    return lib


def windows(header, image_size, usable):
    require(len(header) == 4096 and header[:8] == b'SHNGROOT', 'Root header missing')
    version, count, declared = struct.unpack_from('<IIQ', header, 8)
    require(version == 1 and count == 2 and declared == image_size and
            declared % 4096 == 0 and 4096 <= declared <= usable,
            'Require exactly OS/SystemOS within the non-reserved image area')
    require(hashlib.sha256(header[:4064]).digest() == header[4064:], 'Root header digest mismatch')
    result = {}
    for i in range(count):
        name, offset, size, sector, flags, digest = struct.unpack_from('<32sQQII32s', header, 24 + 128 * i)
        name = name.split(b'\0', 1)[0]
        require(name in (b'OS', b'SystemOS') and name not in result,
                'Missing, duplicated or unexpected root window')
        require(offset % 4096 == 0 and offset >= 4096 and size > 0 and size % 512 == 0 and
                offset + ((size + 4095) & ~4095) <= declared and (sector, flags) == (512, 1),
                'Invalid root window geometry or attributes')
        for previous in result.values():
            require(offset >= previous['end'] or previous['offset'] >= offset + ((size + 4095) & ~4095),
                    'Root windows overlap including physical block padding')
        result[name] = dict(offset=offset, size=size, end=offset + ((size + 4095) & ~4095), sha256=digest.hex())
    require(result[b'OS']['size'] != result[b'SystemOS']['size'],
            'Capacity-based native policy selection requires distinct image sizes')
    return result


def array(name, data, linkage='static const'):
    return f'{linkage} uint8_t {name}[{len(data)}] = {{' + ','.join(f'0x{x:02x}' for x in data) + '};\n'


def render_header(geometry, guid, root_hash, carrier_hash, records, key):
    """Emit fixed-size descriptors; policy capacity must never allocate BSS."""
    generated = ('// Private generated root inputs; not a boot authorization.\n#pragma once\n'
                 '#include "MyronPolicyCarrier.h"\n#include "VerifiedBlockPolicy.h"\n')
    fields = ('first', 'last', 'diskLast', 'carrierOffset', 'carrierCapacity', 'reserveBlocks')
    generated += 'static constexpr MyronRootGeometry myron_root_geometry = {' + ','.join(str(geometry[k]) + 'ULL' for k in fields) + '};\n'
    generated += array('myron_root_guid', guid)
    generated += array('myron_root_header_sha256', root_hash)
    generated += array('myron_carrier_header_sha256', carrier_hash)
    for i, item in enumerate(records):
        generated += array(f'myron_policy_sha_{i}', bytes.fromhex(item['sha256']))
    generated += 'static const MyronPolicyRegion myron_policy_regions[2] = {\n'
    for i, item in enumerate(records):
        generated += '{' + ','.join((str(item['offset']), str(item['bytes']), str(item['capacity']),
                                   'nullptr', f'myron_policy_sha_{i}')) + '},\n'
    generated += '};\nextern "C" {\n' + array('verified_root_key', key, 'extern const')
    generated += 'extern const uint64_t verified_root_policy_count = 2;\n'
    generated += '}\n'
    # Only descriptors live in the image. Policy bytes are allocated at boot.
    generated += 'static NativeVerifiedBlockPolicy myron_loaded_policies[2] = {};\n'
    generated += ('static inline const NativeVerifiedBlockPolicy &myronPolicyAt(uint64_t i) {\n'
                  '  return myron_loaded_policies[i];\n}\n')
    return generated


def prepare(root_image, policies, key_path, geometry, verified_root, out,
            cc='gcc', openssl=Path('/usr')):
    root_image, key_path, verified_root, out = map(lambda p: Path(p).resolve(),
                                                  (root_image, key_path, verified_root, out))
    require(not out.exists(), 'Use a fresh output directory')
    require(root_image.is_file() and key_path.is_file(), 'Use regular root image and key files')
    usable, guid = check_geometry(geometry)
    require(key_path.stat().st_size == 395, 'Independent trusted key must contain 395 bytes')
    key = key_path.read_bytes()
    with root_image.open('rb') as stream:
        header = stream.read(4096)
    layout = windows(header, root_image.stat().st_size, usable)
    require(set(policies) == {'OS', 'SystemOS'}, 'Exactly two named policy inputs are required')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='root-inputs-', dir=out.parent) as temporary:
        work = Path(temporary)
        lib = verifier(verified_root, work, cc, openssl)
        records, manifests, previous, identities = [], [], 4096, set()
        for name in ('OS', 'SystemOS'):
            path = Path(policies[name])
            require(path.is_file(), 'Use regular policy files')
            require(544 <= path.stat().st_size <= geometry['carrierCapacity'] - previous,
                    'Policy envelope exceeds carrier capacity')
            raw = path.read_bytes()
            view = View()
            status = lib.vr_host_open(raw, len(raw), key, 1, C.byref(view))
            require(status == 0, f'{name} signature/hash-table verification failed: {status}')
            entry = layout[name.encode()]
            identity = uuid.UUID(bytes=bytes(view.volume_uuid))
            require(identity.int and identity not in identities, 'Signed volume identities must be distinct and nonzero')
            identities.add(identity)
            require(view.image_bytes == entry['size'] and bytes(view.image_sha256).hex() == entry['sha256'],
                    name + ' signed capacity/image digest differs from the root window')
            digest = hashlib.sha256()
            with root_image.open('rb') as stream:
                stream.seek(entry['offset'])
                remaining, index = entry['size'], 0
                while remaining:
                    data = stream.read(min(4096, remaining))
                    require(len(data) == min(4096, remaining), 'Truncated root image')
                    require(hashlib.sha256(data).digest() == raw[544 + index * 32:576 + index * 32],
                            f'{name} block {index} differs from signed policy')
                    digest.update(data)
                    remaining -= len(data)
                    index += 1
            require(digest.digest() == bytes(view.image_sha256), name + ' complete image digest mismatch')
            capacity = (len(raw) + 4095) & ~4095
            require(previous + capacity <= geometry['carrierCapacity'], 'Rounded policy allocation exceeds carrier')
            records.append(dict(name=name, offset=previous, bytes=len(raw), capacity=capacity,
                sha256=hashlib.sha256(raw).hexdigest(), volume_uuid=str(identity).upper(),
                generation=view.generation, image_bytes=view.image_bytes, image_sha256=digest.hexdigest()))
            manifests.append(raw)
            previous += capacity
        carrier_header = bytearray(4096)
        struct.pack_into('<8sII', carrier_header, 0, b'MYRPOL01', 1, 2)
        for i, item in enumerate(records):
            struct.pack_into('<QQQ32s', carrier_header, 32 + i * 64,
                             item['offset'], item['bytes'], item['capacity'], bytes.fromhex(item['sha256']))
        with (work / 'policy-carrier.bin').open('wb') as stream:
            stream.write(carrier_header)
            for item, raw in zip(records, manifests):
                stream.write(raw)
                stream.write(bytes(item['capacity'] - len(raw)))
        generated = render_header(geometry, guid, hashlib.sha256(header).digest(),
                                  hashlib.sha256(carrier_header).digest(), records, key)
        (work / 'MyronRootPolicyData.h').write_text(generated)
        report = dict(format=1, geometry=geometry, policies=records,
            root_image_sha256=sha_file(root_image), root_image_bytes=root_image.stat().st_size,
            trusted_key_sha256=hashlib.sha256(key).hexdigest(), verifier_source_blobs=VR_BLOBS,
            outputs={name: sha_file(work / name) for name in ('MyronRootPolicyData.h', 'policy-carrier.bin')},
            verified_root_commit='974f043d0c71ba2e60331483a41c6c6d35274ee3',
            all_image_blocks_checked=True, native_root_enabled=False, phone_tested=False,
            limitations=['Container identity is owner-signed; inner APFS UUID must still be checked during native media publication.',
                        'This creates no GPT and performs no device writes or kernel linking.'])
        (work / 'root-bundle.json').write_text(json.dumps(report, indent=2) + '\n')
        # Only publish a complete bundle; failed verification leaves no usable output.
        for pattern in ('*.so', '*.dylib'):
            for path in work.glob(pattern): path.unlink()
        os.rename(work, out)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('root-image', 'os-policy', 'systemos-policy', 'trusted-key', 'geometry', 'verified-root', 'out'):
        p.add_argument('--' + name, required=True, type=Path)
    p.add_argument('--cc', default='clang' if sys.platform == 'darwin' else 'gcc')
    p.add_argument('--openssl-prefix', type=Path, default=Path('/usr'))
    a = p.parse_args()
    report = prepare(a.root_image, {'OS': a.os_policy, 'SystemOS': a.systemos_policy}, a.trusted_key,
                     json.loads(a.geometry.read_text()), a.verified_root, a.out, a.cc, a.openssl_prefix)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
