#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import plistlib
import struct
import unittest

spec = importlib.util.spec_from_file_location('helper_analysis',
    Path(__file__).resolve().parents[1]/'myron27-data-helper-analysis.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def macho(payload):
    off = 32+72+80
    va = 0x100000000
    return (struct.pack('<8I', 0xfeedfacf, 0x100000c, 2, 6, 1, 152, 0, 0) +
            struct.pack('<II16s4Q4I', 0x19, 152, b'__TEXT', va, off+len(payload),
                        0, off+len(payload), 5, 5, 1, 0) +
            struct.pack('<16s16sQQ8I', b'__xpcd_cache', b'__TEXT', va+off,
                        len(payload), off, 0, 0, 0, 0, 0, 0, 0) + payload)


class TestAnalysis(unittest.TestCase):
    def setUp(self):
        self.root = {'LaunchDaemons': {
            '/System/Library/LaunchDaemons/com.apple.backboardd.plist': {
                'Label': 'com.apple.backboardd', 'UserName': 'mobile',
                'ProgramArguments': ['/usr/libexec/backboardd'], 'Unselected': 'omit'},
            '/System/Library/LaunchDaemons/com.apple.other.plist': {
                'Label': 'com.apple.other', 'Unselected': 'omit'}}}

    def test_xml_and_binary_cache(self):
        for form in (plistlib.FMT_XML, plistlib.FMT_BINARY):
            raw = plistlib.dumps(self.root, fmt=form)
            for data in (raw, macho(raw)):
                report = analysis.plist_summary(data)
                self.assertTrue(report['has_launchdaemons_key'])
                self.assertEqual(len(report['selected_jobs']), 1)
                self.assertEqual(report['selected_jobs'][0]['UserName'], 'mobile')
                self.assertNotIn('Unselected', repr(report))

    def test_absent_section_does_not_claim_execution(self):
        self.assertFalse(analysis.plist_summary(b'not a standalone cache')['parsed'])
        data = macho(plistlib.dumps(self.root)).replace(b'__xpcd_cache'.ljust(16,b'\0'), b'__other'.ljust(16,b'\0'))
        self.assertFalse(analysis.plist_summary(data)['parsed'])

    def test_truncation_and_wrong_section_range(self):
        data = macho(plistlib.dumps(self.root))
        for end in (32, 40, 103, 150, len(data)-1):
            with self.assertRaises(ValueError):
                analysis.cache_payload(data[:end])
        damaged = bytearray(data)
        struct.pack_into('<I', damaged, 32+72+48, len(data)+4096)
        with self.assertRaises(ValueError):
            analysis.cache_payload(damaged)

    def test_zero_fill_section_refused(self):
        data = bytearray(macho(plistlib.dumps(self.root)))
        struct.pack_into('<I', data, 32+72+64, 1)
        with self.assertRaises(ValueError):
            analysis.cache_payload(data)

    def test_traversal_bound(self):
        root = current = {}
        for _ in range(20):
            current['nested'] = {}
            current = current['nested']
        with self.assertRaises(ValueError):
            analysis.plist_summary(plistlib.dumps(root))


if __name__ == '__main__':
    unittest.main()
