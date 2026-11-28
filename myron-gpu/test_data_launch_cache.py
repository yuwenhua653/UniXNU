#!/usr/bin/env python3
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from data_launch_cache import add_job, verify_delta, build, daemon, load_archive, LABEL, JOB_PATH, ADDON_PATH


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
        for mutate in ('job', 'framework', 'owner', 'extra', 'bool-type', 'owner-type'):
            result = add_job(self.root)
            if mutate == 'job': result['LaunchDaemons'].pop(next(iter(self.root['LaunchDaemons'])))
            if mutate == 'framework': result['Frameworks']['keep'][0] = 3
            if mutate == 'owner': result['LaunchDaemons'][JOB_PATH]['KeepAlive'] = True
            if mutate == 'extra': result['extra'] = True
            if mutate == 'bool-type': result['Other']['flag'] = 1
            if mutate == 'owner-type': result['LaunchDaemons'][JOB_PATH]['RunAtLoad'] = 1
            with self.assertRaises(ValueError): verify_delta(self.root, result)

    def test_collision_and_wrong_shapes(self):
        for bad in ([], {}, {'LaunchDaemons': []}, {'LaunchDaemons': {'relative': {}}},
                    {'LaunchDaemons': {JOB_PATH: daemon()}},
                    {'LaunchDaemons': {'/different.plist': {'Label': LABEL}}}):
            with self.assertRaises(ValueError): add_job(bad)

    def test_unpinned_input_rejected(self):
        with self.assertRaises(ValueError): build(plistlib.dumps(self.root))

    def test_archive_readback_and_tampering(self):
        original = plistlib.dumps(self.root)
        with patch('data_launch_cache.ORIGINAL_SHA256', hashlib.sha256(original).hexdigest()), \
             patch('data_launch_cache.ORIGINAL_BYTES', len(original)), tempfile.TemporaryDirectory() as tmp:
            merged, report = build(original)
            report['source_commit'] = 'a'*40
            archive = Path(tmp)/'cache.zip'
            for case in ('good', 'changed-job', 'changed-report', 'source', 'inventory'):
                candidate = merged
                record = copy.deepcopy(report)
                if case == 'changed-job':
                    root = plistlib.loads(merged)
                    root['LaunchDaemons'][JOB_PATH]['KeepAlive'] = True
                    candidate = plistlib.dumps(root, fmt=plistlib.FMT_BINARY)
                if case == 'changed-report': record['original_entries_preserved'] = False
                if case == 'source': record['source_commit'] = 'b'*40
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('original-launchd.plist', original)
                    z.writestr('launchd.plist', candidate)
                    z.writestr('cache-build.json', json.dumps(record))
                    if case == 'inventory': z.writestr('unexpected', b'')
                identity = dict(artifact_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), commit='a'*40)
                if case == 'good':
                    self.assertEqual(load_archive(archive, identity), {ADDON_PATH: (0o644, merged)})
                else:
                    with self.assertRaises(ValueError): load_archive(archive, identity)
            identity['artifact_sha256'] = '0'*64
            with self.assertRaises(ValueError): load_archive(archive, identity)


if __name__ == '__main__': unittest.main()
