"""Fresh Data desktop provisioning; APFS ownership is also tested on macOS."""
import argparse
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

p = argparse.ArgumentParser(add_help=False)
p.add_argument('--device', type=Path, required=True)
args, rest = p.parse_known_args()
sys.path.insert(0, str(args.device.resolve()))
import prepare_data_volume as volume


class DesktopSeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefs = self.root/'mobile/Library/Preferences'
        self.prefs.mkdir(parents=True)
        self.owners = {}
        original_stat = Path.stat

        def mock_stat(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path in self.owners:
                fields = list(result)
                fields[4:6] = self.owners[path]
                result = os.stat_result(fields)
            return result

        self.chown = self.enterContext(patch.object(volume.os, 'chown',
            side_effect=lambda path, uid, gid: self.owners.__setitem__(Path(path), (uid, gid))))
        self.enterContext(patch.object(Path, 'stat', mock_stat))

    def read(self, domain):
        return plistlib.loads((self.prefs/(domain+'.plist')).read_bytes())

    def test_completed_setup_preserves_unrelated_values_and_native_watchdogs(self):
        file = self.prefs/'com.apple.springboard.plist'
        file.write_bytes(plistlib.dumps({'unrelated': 'keep', 'BKNoWatchdogs': False}))
        first = volume.set_desktop_preferences(self.root)
        self.assertEqual(volume.set_desktop_preferences(self.root), first)
        self.assertTrue(first['skip_setup'])
        self.assertFalse(first['phone_tested'])
        self.assertEqual(first['build'], '24A446')
        buddy = self.read('com.apple.purplebuddy')
        self.assertIs(buddy['SetupDone'], True)
        self.assertIs(buddy['SetupFinishedAllSteps'], True)
        self.assertIs(buddy['daemonizeNeedsToRun'], False)
        self.assertEqual(buddy['SetupVersion'], 11)
        spring = self.read('com.apple.springboard')
        self.assertEqual(spring['unrelated'], 'keep')
        self.assertIs(spring['BKNoWatchdogs'], False)
        self.assertNotIn('FBLaunchWatchdogExceptions', spring)
        self.assertTrue(all(spring[k] is True for k in (
            'SBDisableAutoDim', 'SBDontDimOrLockOnAC', 'SBDisableIdleSleep')))
        migration = self.read('com.apple.migration')
        self.assertEqual(migration['LastSystemVersion'], '24A446')
        self.assertEqual(migration['DMUserDataDisposition'],
            {'SyntheticDidUpgrade': False, 'buildVersion': '24A446'})
        for file in self.prefs.iterdir():
            self.assertEqual(self.owners[file], (501, 501))
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_missing_wrong_type_old_build_or_tampered_prefs_are_rejected(self):
        volume.set_desktop_preferences(self.root)
        path = self.prefs/'com.apple.purplebuddy.plist'
        original = path.read_bytes()
        for value in (1, 'true', False, None):
            content = plistlib.loads(original)
            if value is None:
                del content['SetupDone']
            else:
                content['SetupDone'] = value
            path.write_bytes(plistlib.dumps(content))
            with self.assertRaisesRegex(ValueError, 'desktop seed values'):
                volume.check_desktop_preferences(self.root)
        path.write_bytes(original)
        self.owners[path] = (0, 0)
        with self.assertRaisesRegex(ValueError, 'ownership'):
            volume.check_desktop_preferences(self.root)
        with patch.object(volume, 'BUILD', '21H461'):
            with self.assertRaisesRegex(ValueError, '24A446'):
                volume.set_desktop_preferences(self.root)

    def test_symlinks_and_non_dictionary_never_modify_outside_file(self):
        outside = self.root/'outside'
        outside.write_bytes(b'keep')
        path = self.prefs/'com.apple.purplebuddy.plist'
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'preferences file'):
            volume.set_desktop_preferences(self.root)
        self.assertEqual(outside.read_bytes(), b'keep')
        path.unlink()
        path.write_bytes(plistlib.dumps(['bad']))
        with self.assertRaisesRegex(ValueError, 'dictionary'):
            volume.set_desktop_preferences(self.root)
        path.unlink()
        self.prefs.rmdir()
        self.prefs.symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, 'directory'):
            volume.set_desktop_preferences(self.root)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *rest])
