#!/usr/bin/env python3
"""Host checks for fail-closed inputs; does not claim macOS APFS validation."""
import argparse
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import os
import plistlib
import subprocess
import prepare_data_seed_r84 as seed


class SeedSafety(unittest.TestCase):
    def test_readonly_mount_without_diskutil_readonly_keys(self):
        with patch.object(seed.os.path, 'ismount', return_value=True), patch.object(seed.os, 'statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            self.assertEqual(seed.require_readonly_mount(Path('/fixture')), os.ST_RDONLY)

    def test_reject_writable_or_non_mount_source(self):
        for mounted, flags in ((True, 0), (False, os.ST_RDONLY)):
            with self.subTest(mounted=mounted), patch.object(seed.os.path, 'ismount', return_value=mounted), patch.object(seed.os, 'statvfs', return_value=SimpleNamespace(f_flag=flags)):
                with self.assertRaises(ValueError):
                    seed.require_readonly_mount(Path('/fixture'))

    def test_unsupported_host_creates_nothing(self):
        with tempfile.TemporaryDirectory() as work, patch.object(seed.platform, 'system', return_value='Linux'):
            output = Path(work)/'out'
            with self.assertRaisesRegex(RuntimeError, 'macOS'):
                seed.create(argparse.Namespace(output=output))
            self.assertFalse(output.exists())

    def test_non_root_creates_nothing(self):
        with patch.object(seed.platform, 'system', return_value='Darwin'), patch.object(seed.os, 'geteuid', return_value=501):
            with self.assertRaisesRegex(RuntimeError, 'root'):
                seed.create(argparse.Namespace())

    def test_size_before_source_or_output(self):
        with patch.object(seed.platform, 'system', return_value='Darwin'), patch.object(seed.os, 'geteuid', return_value=0):
            for mib in (32, 63, 2049):
                with self.subTest(mib=mib), self.assertRaisesRegex(ValueError, '64..2048'):
                    seed.create(argparse.Namespace(mib=mib))

    def test_symlink_runtime_directory(self):
        with tempfile.TemporaryDirectory() as work:
            base = Path(work); root = base/'root'; outside = base/'outside'
            root.mkdir(); outside.mkdir(); (root/'mobile').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                seed.ensure_directory(root, 'mobile/tmp', 501, 501, 0o700)
            self.assertFalse((outside/'tmp').exists())


def macos_smoke(unixnu):
    """Real, temporary APFS round trip; only OS identity uses a synthetic fixture."""
    if seed.platform.system() != 'Darwin' or os.geteuid() != 0:
        raise RuntimeError('macOS root required for APFS smoke test')
    print('Preflight: real APFS create, read-only guard, copy, convert and pack', flush=True)
    with tempfile.TemporaryDirectory(prefix='myron-seed-smoke-') as work:
        base = Path(work).resolve()
        image = base/'source.dmg'; mount = base/'source'; mount.mkdir()
        subprocess.run(['hdiutil', 'create', '-size', '128m', '-layout', 'NONE',
                        '-fs', 'APFS', '-type', 'UDIF', str(image)], check=True)

        def attach(path, target, readonly=False):
            args = ['hdiutil', 'attach', '-nobrowse', '-owners', 'on',
                    '-mountpoint', str(target), '-plist']
            if readonly:
                args.append('-readonly')
            result = seed.plist([*args, str(path)])
            return next(e['dev-entry'] for e in result['system-entities'] if 'dev-entry' in e)

        device = attach(image, mount)
        try:
            try:
                seed.require_readonly_mount(mount)
            except ValueError:
                pass
            else:
                raise AssertionError('Writable APFS source accepted')
            var = mount/'private/var'; var.mkdir(parents=True)
            (var/'mobile').mkdir(); os.chown(var/'mobile', 501, 501)
            (var/'fixture').write_bytes(b'myron-apfs-roundtrip\n')
            os.chmod(var/'fixture', 0o640)
            os.setxattr(var/'fixture', 'com.myron.seed-test', b'preserve-xattr')
            (var/'fixture-link').symlink_to('fixture')
            (var/'staged_system_apps').mkdir()
        finally:
            subprocess.run(['hdiutil', 'detach', device], check=True)
        device = attach(image, mount, readonly=True)
        try:
            seed.require_readonly_mount(mount)
            # Production never skips identity checks. This test alone substitutes
            # its local synthetic source for Apple's immutable OS identity.
            with patch.object(seed, 'check_source', return_value=mount/'private/var'):
                report = seed.create(SimpleNamespace(os_mount=mount, unixnu=unixnu,
                                                     output=base/'result', mib=128))
        finally:
            subprocess.run(['hdiutil', 'detach', device], check=True)
        readback = base/'readback'; readback.mkdir()
        device = attach(base/'result/data.cdr', readback, readonly=True)
        try:
            assert (readback/'fixture').read_bytes() == b'myron-apfs-roundtrip\n'
            assert (readback/'fixture').stat().st_mode & 0o777 == 0o640
            assert os.getxattr(readback/'fixture', 'com.myron.seed-test') == b'preserve-xattr'
            assert os.readlink(readback/'fixture-link') == 'fixture'
            assert (readback/'mobile/tmp').stat().st_uid == 501
            assert (readback/'tmp').stat().st_mode & 0o7777 == 0o1777
            assert not (readback/'staged_system_apps').exists()
            assert report['raw_bytes'] == 128*1024**2
        finally:
            subprocess.run(['hdiutil', 'detach', device], check=True)
    print('PASS: real macOS APFS smoke test, metadata and packed SHA256', flush=True)


if __name__ == '__main__':
    unittest.main()
