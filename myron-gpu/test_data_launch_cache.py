#!/usr/bin/env python3
import copy
import plistlib
import unittest
from data_launch_cache import add_job, verify_delta, build, daemon, LABEL, JOB_PATH


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.root = {'LaunchDaemons': {
            '/System/Library/LaunchDaemons/com.apple.keep.plist': {
                'Label': 'com.apple.keep', 'RunAtLoad': False,
                'MachServices': {'com.apple.keep': {'ResetAtClose': True}},
                'Opaque': b'original'}},
            'Frameworks': {'keep': [1, 2, 'original']}, 'Other': {'flag': True}}

    def test_roundtrip_preserves_original(self):
        before = copy.deepcopy(self.root)
        result = add_job(self.root)
        for form in (plistlib.FMT_BINARY, plistlib.FMT_XML):
            verify_delta(self.root, plistlib.loads(plistlib.dumps(result, fmt=form)))
        self.assertEqual(self.root, before)
        self.assertEqual(result['LaunchDaemons'][JOB_PATH], daemon())

    def test_changed_original_or_owner_rejected(self):
        for mutate in ('job', 'framework', 'owner', 'extra'):
            result = add_job(self.root)
            if mutate == 'job': result['LaunchDaemons'].pop(next(iter(self.root['LaunchDaemons'])))
            if mutate == 'framework': result['Frameworks']['keep'][0] = 3
            if mutate == 'owner': result['LaunchDaemons'][JOB_PATH]['KeepAlive'] = True
            if mutate == 'extra': result['extra'] = True
            with self.assertRaises(ValueError): verify_delta(self.root, result)

    def test_collision_and_wrong_shapes(self):
        for bad in ([], {}, {'LaunchDaemons': []}, {'LaunchDaemons': {'relative': {}}},
                    {'LaunchDaemons': {JOB_PATH: daemon()}},
                    {'LaunchDaemons': {'/different.plist': {'Label': LABEL}}}):
            with self.assertRaises(ValueError): add_job(bad)

    def test_unpinned_input_rejected(self):
        with self.assertRaises(ValueError): build(plistlib.dumps(self.root))


if __name__ == '__main__': unittest.main()
