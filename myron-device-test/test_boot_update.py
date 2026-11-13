"""Exercise update/restore decisions with synthetic images; never run a device tool."""
import copy
import shutil
import struct
import unittest
from unittest.mock import patch
import myron_boot_update as u
import myron_device_test as t
import test_companion as fixtures


class BootUpdateTests(unittest.TestCase):
    def setUp(self):
        fixtures.CompanionTests.setUp(self)
        self.m.update(format=1, device='myron', partition='unixnu', device_bound=True,
                      qualification_only=False, trusted_anchor_sha256='anchor',
                      root_bundle_sha256='bundle', history_binding_sha256='binding')
        t.save(self.package/'deployment.json', self.m)
        t.prepare(self.package, self.state, self.device)
        t.install(self.package, self.state, self.device)
        self.update = self.base/'update'; self.update.mkdir()
        header = bytearray(4096); header[:8] = b'ANDROID!'
        struct.pack_into('<I', header, 40, 4)
        (self.update/'root-startup.img').write_bytes(header)
        new = copy.deepcopy(self.m)
        new['files']['root-startup.img'] = dict(bytes=len(header), sha256=t.sha(self.update/'root-startup.img'))
        t.save(self.update/'deployment.json', new)
        for name, value in dict(MANIFEST_SHA=t.sha(self.update/'deployment.json'),
                                BOOT_BYTES=len(header), BOOT_SHA=t.sha(self.update/'root-startup.img'),
                                RETAINED={n:self.m['files'][n] for n in u.RETAINED}).items():
            p = patch.object(u, name, value); p.start(); self.addCleanup(p.stop)
        self.fb = fixtures.FakeFastboot()

    def reject(self):
        with self.assertRaises((ValueError, KeyError)):
            u.start(self.package, self.state, self.update, lambda b:self.fail('Must stop before fastboot'))
        self.assertFalse((self.state/'boot-update-attempt.json').exists())

    def edit_receipt(self, edit):
        path = self.state/'root-install.json'; r = t.load(path); edit(r); t.save(path, r)

    def test_update_only_boot_and_preserve_original_state(self):
        before = {p.name:t.sha(p) for p in self.state.iterdir() if p.is_file()}
        writes = list(self.device.writes)
        u.start(self.package, self.state, self.update, lambda b:self.fb)
        self.assertEqual(self.fb.calls, [('flash','boot_a','root-startup.img'), ('reboot',)])
        self.assertEqual(self.device.writes, writes)
        for name, digest in before.items():self.assertEqual(t.sha(self.state/name), digest)
        self.assertTrue(t.load(self.state/'boot-update-attempt.json')['reboot_completed'])

    def test_restore_independent_of_update_and_root_metadata(self):
        shutil.rmtree(self.package); shutil.rmtree(self.update)
        (self.state/'root-install.json').unlink()
        with patch('sys.argv', ['update', 'restore', '--state', str(self.state)]), \
             patch.object(t, 'confirm'), patch.object(u, 'fastboot', return_value=self.fb):
            u.main()
        self.assertEqual(self.fb.calls, [('flash','boot_a','boot_a.img'), ('reboot',)])

    def test_corrupt_backup(self):
        with (self.state/'boot_a.img').open('r+b') as f:f.write(b'bad')
        self.reject()

    def test_corrupt_boot_update(self):
        (self.update/'root-startup.img').write_bytes(b'bad')
        self.reject()

    def test_changed_new_manifest(self):
        (self.update/'deployment.json').write_text('{}')
        self.reject()

    def test_changed_original_manifest(self):
        (self.package/'deployment.json').write_text('{}')
        self.reject()

    def test_incomplete_install(self):
        self.edit_receipt(lambda r:r.update(complete=False)); self.reject()

    def test_missing_chunk(self):
        self.edit_receipt(lambda r:r['chunks'].pop()); self.reject()

    def test_wrong_chunk_range(self):
        self.edit_receipt(lambda r:r['chunks'][0].update(offset=4096)); self.reject()

    def test_wrong_receipt_identity(self):
        for key in ('serial', 'slot', 'manifest_sha256', 'capture_binding'):
            path=self.state/'root-install.json'; original=path.read_bytes()
            with self.subTest(key=key):
                self.edit_receipt(lambda r:r.update({key:'different'})); self.reject()
            path.write_bytes(original)

    def test_incompatible_retained_root_or_geometry(self):
        # Rebind a self-consistent old session to a different retained root/layout.
        for key in ('geometry', 'history_binding_sha256', 'files'):
            with self.subTest(key=key):
                old=copy.deepcopy(self.m)
                if key=='files':old['files']['policy-carrier.bin']['sha256']='0'*64
                elif key=='geometry':old['geometry']['carrierOffset']+=4096
                else:old[key]='other'
                t.save(self.package/'deployment.json',old)
                b=t.load(self.state/'backup.json'); b['manifest_sha256']=t.sha(self.package/'deployment.json')
                t.save(self.state/'backup.json',b)
                self.edit_receipt(lambda r:r.update(manifest_sha256=b['manifest_sha256']))
                self.reject()

    def test_flash_failure_does_not_reboot(self):
        with patch.object(self.fb, 'flash', side_effect=TimeoutError('Disconnected')):
            with self.assertRaises(TimeoutError):u.start(self.package,self.state,self.update,lambda b:self.fb)
        self.assertEqual(self.fb.calls, [])
        record=t.load(self.state/'boot-update-attempt.json')
        self.assertTrue(record['flash_started']); self.assertFalse(record['flash_completed'])

    def test_fastboot_identity_failure_before_attempt(self):
        def failed(b):raise ValueError('slot changed')
        with self.assertRaisesRegex(ValueError, 'slot changed'):
            u.start(self.package,self.state,self.update,failed)
        self.assertFalse((self.state/'boot-update-attempt.json').exists())


class FastbootGuards(unittest.TestCase):
    def test_live_guard_mismatches_rejected(self):
        backup=dict(serial='serial', slot='a', boot_name='boot_a', boot_bytes=100663296)
        values={'product':'myron', 'is-userspace':'no', 'unlocked':'yes',
                'current-slot':'a', 'partition-size:boot_a':'6000000'}
        for key, bad in [('product','other'), ('is-userspace','yes'), ('unlocked','no'),
                         ('current-slot','b'), ('partition-size:boot_a','1000')]:
            with self.subTest(key=key), patch.object(t,'invoke',return_value=b'serial fastboot\n'), \
                 patch.object(t.Fastboot,'get',side_effect=lambda n:bad if n==key else values[n]):
                with self.assertRaises(ValueError):t.Fastboot('unused',backup)
        for devices in (b'', b'other fastboot\n', b'serial fastboot\nother fastboot\n'):
            with patch.object(t,'invoke',return_value=devices):
                with self.assertRaises(ValueError):t.Fastboot('unused',backup)


if __name__ == '__main__':unittest.main()
