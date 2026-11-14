import contextlib
import copy
import io as streams
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import fresh_boot as f

# Point this at the extracted, hash-pinned CI candidate; no handset is used.
PACKAGE = Path(os.environ['MYRON_TEST_CANDIDATE'])


class FakeRecovery:
    serial = 'testphone'
    slot = 'a'
    def __init__(self, manifest, data):
        self.m = manifest; self.data = data; self.hashes = []; self.bad_root = False
        self.bad_layout = False; self.change_read = False; self.calls = 0
    def capture(self, directory):
        Path(directory).mkdir(parents=True)
        disk = copy.deepcopy(self.m['layout'])
        if self.bad_layout: disk['first'] += 1
        return disk, 'f'*64, '/dev/block/sda35'
    def boot(self): return 'boot_a', '/dev/block/sde16', len(self.data)
    def read(self, path, offset, size):
        self.calls += 1
        result = self.data[offset:offset+size]
        if self.change_read and self.calls > 6: result = bytes([result[0]^1])+result[1:]
        return result
    def hash_region(self, path, offset, size):
        self.hashes.append((path, offset, size))
        if self.bad_root: return '0'*64
        row = next(x for x in self.m['root_writes'] if x['partition_offset'] == offset)
        return self.m['files'][row['file']]['sha256']


class FakeAndroid:
    serial = 'testphone'; slot = 'a'
    def shell(self, *args): return 'fake/known-working/android'
    def reboot_recovery(self): self.rebooted = True


class FakeFastboot:
    def __init__(self): self.commands = []; self.fail = False
    def flash(self, name, path):
        self.commands.append(('flash',name,str(path)))
        if self.fail: raise ValueError('simulated flash failure')
    def reboot(self): self.commands.append(('reboot',))


class FreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = f.verify_release(PACKAGE)
        data = bytearray(96*1024**2); data[:8] = b'ANDROID!'; struct.pack_into('<I',data,40,4)
        data[4096:4110] = b'ANDROID_KERNEL'
        cls.boot = bytes(data)
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)/'state'
        self.device = FakeRecovery(self.manifest, self.boot)
        self.sink = contextlib.redirect_stdout(streams.StringIO()); self.sink.__enter__()
        self.addCleanup(self.sink.__exit__,None,None,None)
    def observed(self):
        a=FakeAndroid();f.observe_android(PACKAGE,self.state,a);self.assertTrue(a.rebooted)
    def prepared(self):
        self.observed();f.prepare(PACKAGE,self.state,self.device)
    def test_fresh_session_backups_and_root_regions(self):
        self.prepared();b=f.ready(PACKAGE,self.state)
        self.assertEqual(b['boot_sha256'],f.io.sha(self.state/'boot_a.img'))
        self.assertEqual(len(self.device.hashes),2)
        self.assertEqual(self.device.hashes[0][2],15092154368)
        self.assertFalse((self.state/'root-install.json').exists())
        fb=FakeFastboot();f.start(PACKAGE,self.state,lambda b:fb)
        self.assertEqual([c[:2] for c in fb.commands],[('flash','boot_a'),('reboot',)])
    def test_missing_android_observation_blocks_backup(self):
        with self.assertRaises(ValueError):f.prepare(PACKAGE,self.state,self.device)
        self.assertFalse(self.state.exists())
    def test_foreign_phone_and_slot_block_before_read(self):
        self.observed()
        for field,value in [('serial','other'),('slot','b')]:
            d=FakeRecovery(self.manifest,self.boot);setattr(d,field,value)
            with self.assertRaises(ValueError):f.prepare(PACKAGE,self.state,d)
            self.assertEqual(d.calls,0)
    def test_layout_mismatch_blocks_boot_backup(self):
        self.observed();self.device.bad_layout=True
        with self.assertRaises(ValueError):f.prepare(PACKAGE,self.state,self.device)
        self.assertFalse((self.state/'backup.json').exists())
    def test_changed_second_read_retains_partial_but_not_valid_backup(self):
        self.observed();self.device.change_read=True
        with self.assertRaises(ValueError):f.prepare(PACKAGE,self.state,self.device)
        self.assertTrue((self.state/'boot_a.img.partial').exists())
        self.assertFalse((self.state/'backup.json').exists())
    def test_ios_boot_cannot_be_used_as_android_backup(self):
        self.observed();self.device.data=self.boot[:8192]+b'UniXNU'+self.boot[8198:]
        with self.assertRaisesRegex(ValueError,'iOS/UniXNU'):f.prepare(PACKAGE,self.state,self.device)
        self.assertFalse((self.state/'backup.json').exists())
    def test_root_mismatch_retains_backup_and_blocks_start(self):
        self.observed();self.device.bad_root=True
        with self.assertRaises(ValueError):f.prepare(PACKAGE,self.state,self.device)
        f.backup_state(self.state)
        fb=FakeFastboot()
        with self.assertRaises(ValueError):f.start(PACKAGE,self.state,lambda b:fb)
        self.assertEqual(fb.commands,[])
    def test_restore_does_not_read_release_or_root_receipt(self):
        self.prepared();(self.state/'root-check.json').unlink();fb=FakeFastboot()
        with patch.object(f,'verify_release',side_effect=AssertionError('must not read payload')):
            f.restore(self.state,lambda b:fb)
        self.assertEqual(fb.commands[0],('flash','boot_a',str(self.state/'boot_a.img')))
    def test_corrupt_backup_blocks_restore_before_fastboot(self):
        self.prepared()
        with (self.state/'boot_a.img').open('r+b') as fp:fp.write(b'BROKEN!!')
        fb=FakeFastboot()
        with self.assertRaises(ValueError):f.restore(self.state,lambda b:fb)
        self.assertEqual(fb.commands,[])
    def test_receipt_from_other_session_blocks_start(self):
        self.prepared();r=f.io.load(self.state/'root-check.json');r['serial']='other';f.io.save(self.state/'root-check.json',r)
        fb=FakeFastboot()
        with self.assertRaises(ValueError):f.start(PACKAGE,self.state,lambda b:fb)
        self.assertEqual(fb.commands,[])
    def test_flash_failure_keeps_backup_and_records_incomplete_attempt(self):
        self.prepared();fb=FakeFastboot();fb.fail=True
        with self.assertRaises(ValueError):f.start(PACKAGE,self.state,lambda b:fb)
        r=f.io.load(self.state/'boot-attempt.json');self.assertTrue(r['flash_started']);self.assertFalse(r['flash_completed'])
        self.assertEqual(len(fb.commands),1);f.backup_state(self.state)
    def test_new_observation_cannot_replace_existing_backup(self):
        self.prepared();before=f.io.sha(self.state/'boot_a.img')
        with self.assertRaises(ValueError):f.observe_android(PACKAGE,self.state,FakeAndroid())
        self.assertEqual(f.io.sha(self.state/'boot_a.img'),before)
    def test_fastboot_wrong_slot_is_rejected(self):
        self.prepared();b=f.backup_state(self.state)
        def variable(self,name):
            return {'product':'myron','is-userspace':'no','unlocked':'yes','current-slot':'b'}[name]
        with patch.object(f.io,'invoke',return_value=b'testphone fastboot\n'),patch.object(f.io.Fastboot,'get',variable):
            with self.assertRaisesRegex(ValueError,'slot changed'):f.io.Fastboot('fake-fastboot',b)

    def previous_session(self):
        self.prepared()
        for name in ('backup.json','root-check.json'):
            p=self.state/name;r=f.io.load(p)
            r['run']=43544518065;r['manifest_sha256']=f.BACKUP_MANIFESTS[43544518065]
            f.io.save(p,r)

    def test_previous_fresh_pc_backup_and_receipt_work_without_relabeling(self):
        self.previous_session()
        before={p.name:p.read_bytes() for p in self.state.iterdir() if p.is_file()}
        fb=FakeFastboot();f.start(PACKAGE,self.state,lambda b:fb)
        self.assertEqual(fb.commands[0][1],'boot_a')
        for name,data in before.items():self.assertEqual((self.state/name).read_bytes(),data)
        (self.state/'root-check.json').unlink()
        f.restore(self.state,lambda b:fb)
        self.assertEqual(fb.commands[-2][2],str(self.state/'boot_a.img'))

    def test_unrecognized_backup_run_cannot_flash_or_restore(self):
        self.previous_session();p=self.state/'backup.json';b=f.io.load(p);b['run']=43395897855;f.io.save(p,b)
        fb=FakeFastboot()
        for op in (lambda:f.start(PACKAGE,self.state,lambda b:fb),lambda:f.restore(self.state,lambda b:fb)):
            with self.assertRaises(ValueError):op()
        self.assertEqual(fb.commands,[])

    def test_previous_receipt_with_changed_root_blocks_start(self):
        self.previous_session();p=self.state/'root-check.json';r=f.io.load(p);r['verified'][0]['sha256']='0'*64;f.io.save(p,r)
        fb=FakeFastboot()
        with self.assertRaises(ValueError):f.start(PACKAGE,self.state,lambda b:fb)
        self.assertEqual(fb.commands,[])

    def test_previous_receipt_cannot_mix_run_or_manifest(self):
        self.previous_session();p=self.state/'root-check.json';original=f.io.load(p)
        for key,value in [('run',f.RUN),('manifest_sha256',f.MANIFEST_SHA)]:
            r=copy.deepcopy(original);r[key]=value;f.io.save(p,r)
            with self.assertRaises(ValueError):f.ready(PACKAGE,self.state)


if __name__ == '__main__': unittest.main(verbosity=2)
