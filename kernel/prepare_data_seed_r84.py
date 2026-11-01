#!/usr/bin/env python3
"""macOS-only clean 21H461 Data fixture; never opens a phone or partition device.

Creates a NEW local APFS image from an already mounted, unchanged OS image.
Requires root to preserve iOS ownership. Does not install or select this image.
Reference: Typeun/myron-device scripts/seed-data-ram-size.py (d9b6be4).
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import stat
import subprocess
import uuid

LAUNCHD_SHA = '8cec9a3c44a443b08e977ccc5d577850316ad428c575dc01f09b018dbd5b6a25'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plist(command):
    return plistlib.loads(subprocess.check_output(command))


def require_readonly_mount(source):
    # statvfs reports the live mount, unlike guessed diskutil plist key names.
    # Missing information must never be interpreted as read-only.
    if not os.path.ismount(source):
        raise ValueError('Source must be the root of a mounted filesystem')
    flags = os.statvfs(source).f_flag
    if not flags & os.ST_RDONLY:
        raise ValueError('Require a read-only source OS mount (ST_RDONLY absent)')
    return flags


def check_source(source):
    version = plistlib.loads((source/'System/Library/CoreServices/SystemVersion.plist').read_bytes())
    if version.get('ProductBuildVersion') != '21H461' or sha(source/'sbin/launchd') != LAUNCHD_SHA:
        raise ValueError('Require the original 21H461 OS and exact launchd hash')
    var = source/'private/var'
    if var.is_symlink() or not var.is_dir():
        raise ValueError('Source private/var must be an actual directory')
    return var


def ensure_directory(root, relative, uid, gid, mode):
    # Reject symlinks at every component: never write through a seed link.
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f'Refuse runtime directory symlink: {relative}')
        current.mkdir(exist_ok=True)
    os.chown(current, uid, gid)
    os.chmod(current, mode)


def create(args):
    if platform.system() != 'Darwin':
        raise RuntimeError('APFS creation requires macOS hdiutil/diskutil; no output created')
    if os.geteuid() != 0:
        raise RuntimeError('Run on macOS as root to preserve iOS uid/gid and ACL metadata')
    if not 64 <= args.mib <= 2048:
        raise ValueError('Data fixture size must be 64..2048 MiB; memory budget must be checked before boot')
    source = args.os_mount.resolve(strict=True)
    source_flags = require_readonly_mount(source)
    var = check_source(source)
    packer_path = args.unixnu.resolve(strict=True)/'drivers/DarwinBoot/Test/packed_ramdisk.py'
    spec = importlib.util.spec_from_file_location('packed_ramdisk_r84', packer_path)
    packer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packer)
    output = args.output.resolve()
    if output == source or source in output.parents or output in source.parents:
        raise ValueError('Output must be separate from the source mount')
    output.mkdir(parents=True, exist_ok=False)
    image, target = output/'data.cdr', output/'mount'
    writable_image = output/'data.dmg'
    target.mkdir()
    subprocess.run(['hdiutil', 'create', '-size', f'{args.mib}m', '-layout', 'NONE',
                    '-fs', 'APFS', '-volname', 'MyronCleanData', '-type', 'UDIF', str(writable_image)], check=True)
    attached = plist(['hdiutil', 'attach', '-nobrowse', '-owners', 'on', '-mountpoint', str(target), '-plist', str(writable_image)])
    entities = attached['system-entities']
    device = next(e['dev-entry'] for e in entities if 'dev-entry' in e)
    try:
        volumes = [e for e in entities if e.get('mount-point') == str(target)]
        if len(volumes) != 1:
            raise ValueError('Expected exactly one newly created mounted volume')
        info = plist(['diskutil', 'info', '-plist', volumes[0]['dev-entry']])
        volume_uuid = str(uuid.UUID(info['VolumeUUID'])).upper()
        for child in var.iterdir():
            if child.name == 'staged_system_apps':
                continue
            dest = target/child.name
            if child.is_symlink():
                os.symlink(os.readlink(child), dest)
                metadata = child.lstat()
                os.chown(dest, metadata.st_uid, metadata.st_gid, follow_symlinks=False)
            else:
                subprocess.run(['/usr/bin/ditto', '--rsrc', '--extattr', '--acl', str(child), str(dest)], check=True)
        metadata = var.stat()
        os.chown(target, metadata.st_uid, metadata.st_gid)
        os.chmod(target, stat.S_IMODE(metadata.st_mode))
        ensure_directory(target, 'keybags', 0, 0, 0o700)
        ensure_directory(target, 'run', 0, 0, 0o755)
        ensure_directory(target, 'tmp', 0, 0, 0o1777)
        mobile = target/'mobile'
        if mobile.is_symlink() or not mobile.is_dir() or mobile.stat().st_uid != 501:
            raise ValueError('Source mobile directory must retain iOS mobile uid 501')
        ensure_directory(target, 'mobile/tmp', 501, mobile.stat().st_gid, 0o700)
        free_bytes = shutil.disk_usage(target).free
        if free_bytes < max(32*1024**2, args.mib*1024**2//2):
            raise ValueError('Insufficient initial free space; use a larger fixture')
        probe = target/'.r84-write-probe'
        with probe.open('xb') as stream:
            stream.write(b'myron-r84-data-write-probe\n')
            stream.flush()
            os.fsync(stream.fileno())
        if probe.read_bytes() != b'myron-r84-data-write-probe\n':
            raise ValueError('New image write/read check failed')
        probe.unlink()
        subprocess.run(['diskutil', 'verifyVolume', volumes[0]['dev-entry']], check=True)
    finally:
        subprocess.run(['hdiutil', 'detach', device], check=True)
    # UDTO is a conversion format, not a valid hdiutil create -type.
    subprocess.run(['hdiutil', 'convert', str(writable_image), '-format', 'UDTO',
                    '-o', str(image)], check=True)
    with image.open('rb') as stream:
        header = stream.read(4096)
    if image.stat().st_size != args.mib*1024**2 or header[32:36] != b'NXSB':
        raise ValueError('Expected exact-size raw APFS container')
    packed = output/'data.dbr'
    encoded = packer.pack(image, packed)
    if encoded['sha256'] != sha(image):
        raise ValueError('Packed image must reconstruct the complete raw SHA256')
    # Ensure source identity still matches; no phone operation is part of this tool.
    check_source(source)
    require_readonly_mount(source)
    report = dict(build='21H461', launchd_sha256=LAUNCHD_SHA, volume_uuid=volume_uuid,
                  source_mount_flags=source_flags,
                  initial_free_bytes=free_bytes, raw_bytes=image.stat().st_size,
                  packed=encoded, packer_sha256=sha(packer_path),
                  source='Original OS private/var excluding top-level staged_system_apps',
                  metadata_copy='ditto ownership, resource forks, extended attributes and ACLs',
                  persistent=False, keybag_created=False, phone_written=False,
                  kernel_integration_tested=False, memory_budget_qualified=False)
    (output/'seed.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--os-mount', type=Path, required=True)
    parser.add_argument('--unixnu', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mib', type=int, default=512)
    try:
        print(json.dumps(create(parser.parse_args()), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error


if __name__ == '__main__':
    main()
