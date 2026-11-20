"""Verify the production Data layout change on a private copy of a retained boot seed."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import struct
import sys
import tempfile
import zipfile


def unpack_seed(package, raw):
    with zipfile.ZipFile(package) as zipped:
        boot, = [name for name in zipped.namelist() if name.endswith('/root-startup.img')]
        manifest = json.loads(zipped.read(boot.rsplit('/', 1)[0] + '/deployment.json'))
        image = zipped.read(boot)
    if hashlib.sha256(image).hexdigest() != manifest['files']['root-startup.img']['sha256']:
        raise ValueError('Boot image differs from manifest')
    record = manifest['image_reports']['root-startup.img']
    digest = record['embedded_files']['EFI/UniXNU/Payloads/scratch-data.img']
    pos = record['fat_offset']
    while (pos := image.find(b'DBRDISK1', pos)) != -1:
        start = pos
        pos += 8
        if len(image) - start < 32:
            continue
        version, block, size, count = struct.unpack_from('<IIQQ', image, start+8)
        if not (version == 1 and block == 4096 and 0 < size <= 2**31 and 0 < count <= 65536):
            continue
        body = start + 32 + count * 16
        if body > len(image):
            continue
        runs = list(struct.iter_unpack('<QQ',image[start+32:body]))
        end = body + sum(length for _, length in runs)
        if end > len(image) or hashlib.sha256(image[start:end]).hexdigest() != digest:
            continue
        with raw.open('xb') as out:
            out.truncate(size)
            last = 0
            for offset, length in runs:
                if offset < last or not length or offset % block or length % block or offset + length > size:
                    raise ValueError('Invalid Data seed extent')
                out.seek(offset)
                out.write(image[body:body+length])
                body += length
                last = offset + length
        return digest
    raise ValueError('Matching Data seed missing from boot image')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.device.resolve()))
    import prepare_data_volume as volume
    import data_seed
    volume.check_host()
    with tempfile.TemporaryDirectory() as private:
        work = Path(private)
        image = work/'data.cdr'
        old_digest = unpack_seed(args.package, image)
        with volume.attached(image, work/'before', True) as before:
            old_uuid = before['uuid']
            missing = [p for p in volume.CONTAINER_DIRS if not (before['path']/p).is_dir()]
            if not missing:
                raise ValueError('Retained regression input already has all directories')
        with volume.attached(image, work/'write', False) as target:
            volume.ensure_container_layout(target['path'])
            volume.ensure_container_layout(target['path'])
        with volume.attached(image, work/'after', True) as after:
            if after['uuid'] != old_uuid:
                raise ValueError('Data UUID changed')
            for p in missing:
                directory = after['path']/p
                info = directory.lstat()
                if not stat.S_ISDIR(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode)) != (0,0,0o755):
                    raise ValueError('Wrong metadata for '+p)
            volume.run('diskutil','verifyVolume',after['device'])
        checked = data_seed.pack(image, work/'checked.dbr')
        if checked['transport_sha256'] == old_digest:
            raise ValueError('Data transport did not change')
        print('Verified the retained seed. Initially missing:', ', '.join(missing))
        print('PASS retained Data: APFS read-only remount, UUID, directory owners/modes and sparse repack')


if __name__ == '__main__':
    main()
