#!/usr/bin/env python3
"""Host checks for fail-closed inputs; does not claim macOS APFS validation."""
import argparse
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import prepare_data_seed_r84 as seed


class SeedSafety(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
