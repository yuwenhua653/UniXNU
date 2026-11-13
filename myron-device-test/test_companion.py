"""Host-only deployment state-machine tests. No real adb/fastboot/device calls."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import myron_device_test as t


class FakeRecovery:
    serial='testserial';slot='a'
    def __init__(self,m):
        self.m=m;self.writes=[];self.blocks={};self.corrupt=False;self.changed=False
        self.bootdata=b'ANDROID!'+bytes(16*1024**2-8)
    def capture(self,path):
        Path(path).mkdir()
        disk=copy.deepcopy(self.m['layout'])
        if self.changed:disk['partitionGuid']='changed'
        return disk,'gpt-binding','/dev/block/sda35'
    def boot(self):return 'boot_a','/dev/block/sde11',len(self.bootdata)
    def read(self,path,off,size):
        if path=='/dev/block/sde11':return self.bootdata[off:off+size]
        return self.blocks.get((off,size),bytes(size))
    def write(self,path,off,data,host):
        self.writes.append((path,off,len(data)))
        self.blocks[(off,len(data))]=bytes(len(data)) if self.corrupt else data
    def shell(self,*args):return ''


class FakeFastboot:
    def __init__(self):self.calls=[]
    def flash(self,name,path):self.calls.append(('flash',name,Path(path).name))
    def reboot(self):self.calls.append(('reboot',))


class CompanionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.base=Path(tmp.name)
        self.package=self.base/'package';self.package.mkdir();self.state=self.base/'state'
        for name,data in [('root-container.raw',b'A'*8192),('policy-carrier.bin',b'P'*4096),
                          ('root.img',b'ANDROID!'+bytes(4096-8)),('root-startup.img',b'ANDROID!'+bytes(4096-8))]:
            (self.package/name).write_bytes(data)
        disk=dict(first=100000,last=100000+32*1024**3//4096-1,diskLast=100000+32*1024**3//4096+100,
                  partitionGuid='c9f65538-0989-4306-b9a3-3c6db52ea120',partition_index=35,partition_bytes=32*1024**3,
                  disk_guid='c9f65538-0989-4306-b9a3-3c6db52ea121')
        geo=t.layout.allocate(disk,8192,4096)
        self.m=dict(layout=disk,geometry=geo,files={n:dict(bytes=(self.package/n).stat().st_size,sha256=t.sha(self.package/n)) for n in t.FILES},
                    root_writes=[dict(file='root-container.raw',partition_offset=0,bytes=8192),
                                 dict(file='policy-carrier.bin',partition_offset=geo['carrierOffset'],bytes=4096)])
        t.save(self.package/'deployment.json',self.m)
        self.device=FakeRecovery(self.m)
        p=patch.object(t,'verify',return_value=self.m);p.start();self.addCleanup(p.stop)
    def prepare(self):t.prepare(self.package,self.state,self.device)
    def test_full_install_start_and_restore_is_bounded(self):
        self.prepare();self.assertEqual(self.device.writes,[])
        t.install(self.package,self.state,self.device)
        self.assertEqual(self.device.writes,[('/dev/block/sda35',0,8192),('/dev/block/sda35',self.m['geometry']['carrierOffset'],4096)])
        self.assertTrue(t.load(self.state/'root-install.json')['complete'])
        fb=FakeFastboot();t.start(self.package,self.state,lambda b:fb)
        self.assertEqual(fb.calls,[('flash','boot_a','root-startup.img'),('reboot',)])
        # Restore deliberately has no package or root-install dependency.
        (self.package/'deployment.json').unlink();(self.state/'root-install.json').unlink()
        fb=FakeFastboot();t.restore(self.state,lambda b:fb)
        self.assertEqual(fb.calls,[('flash','boot_a','boot_a.img'),('reboot',)])
    def test_recovery_disconnect_stops_with_backup_and_no_completed_receipt(self):
        self.prepare()
        with patch.object(self.device,'write',side_effect=TimeoutError('Disconnected')):
            with self.assertRaises(TimeoutError):t.install(self.package,self.state,self.device)
        self.assertFalse(t.load(self.state/'root-install.json')['complete'])
        self.assertTrue((self.state/'boot_a.img').is_file())
    def test_failed_readback_prevents_start(self):
        self.prepare();self.device.corrupt=True
        with self.assertRaisesRegex(ValueError,'Readback'):t.install(self.package,self.state,self.device)
        with self.assertRaisesRegex(ValueError,'incomplete'):t.start(self.package,self.state,lambda b:self.fail('must not flash'))
    def test_retry_reads_verified_chunks_and_does_not_rewrite(self):
        self.prepare();t.install(self.package,self.state,self.device);count=len(self.device.writes)
        t.install(self.package,self.state,self.device)
        self.assertEqual(len(self.device.writes),count)
    def test_changed_gpt_or_slot_stops_before_write(self):
        self.prepare();self.device.changed=True
        with self.assertRaisesRegex(ValueError,'GPT'):t.install(self.package,self.state,self.device)
        self.device.changed=False;self.device.slot='b'
        with self.assertRaisesRegex(ValueError,'slot'):t.install(self.package,self.state,self.device)
        self.assertEqual(self.device.writes,[])
    def test_existing_state_never_overwritten(self):
        self.prepare();digest=t.sha(self.state/'boot_a.img')
        with self.assertRaisesRegex(ValueError,'existing state'):self.prepare()
        self.assertEqual(t.sha(self.state/'boot_a.img'),digest)
    def test_changed_backup_prevents_install_and_restore(self):
        self.prepare()
        with (self.state/'boot_a.img').open('r+b') as f:f.write(b'BAD!')
        for operation in (lambda:t.install(self.package,self.state,self.device),lambda:t.restore(self.state,lambda b:self.fail('no flash'))):
            with self.assertRaisesRegex(ValueError,'backup changed'):operation()
        self.assertEqual(self.device.writes,[])
    def test_changed_live_android_boot_prevents_install(self):
        self.prepare();self.device.bootdata=b'X'+self.device.bootdata[1:]
        with self.assertRaisesRegex(ValueError,'Android boot differs'):t.install(self.package,self.state,self.device)
        self.assertEqual(self.device.writes,[])
    def test_changed_manifest_prevents_install(self):
        self.prepare();(self.package/'deployment.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Package differs'):t.install(self.package,self.state,self.device)
        self.assertEqual(self.device.writes,[])
    def test_gpt_change_between_chunks_stops(self):
        self.prepare();write=self.device.write
        def mutate(*args):write(*args);self.device.changed=True
        with patch.object(self.device,'write',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'GPT'):t.install(self.package,self.state,self.device)
        self.assertEqual(len(self.device.writes),1)
        self.assertFalse(t.load(self.state/'root-install.json')['complete'])


class CommandTests(unittest.TestCase):
    def test_fastboot_flash_uses_exact_serial_and_slot(self):
        f=t.Fastboot.__new__(t.Fastboot);f.exe='fastboot';f.serial='serial'
        with patch.object(t,'invoke') as call:
            f.flash('boot_a',Path('state/boot_a.img'))
            self.assertEqual(call.call_args.args[0],['fastboot','-s','serial','flash','boot_a',str(Path('state/boot_a.img'))])
            for name in ('boot','userdata','unixnu','boot_c'):
                with self.assertRaises(ValueError):f.flash(name,Path('anything'))
    def test_wrong_archive_refused_before_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fake.zip';p.write_bytes(b'not approved')
            with self.assertRaisesRegex(ValueError,'approved'):t.unpack(p,Path(d)/'package')
            self.assertFalse((Path(d)/'package').exists())


class BinaryReadTests(unittest.TestCase):
    def test_exact_bytes_preserved(self):
        data=bytes(range(256))*16
        self.assertEqual(t.layout.read_blocks(lambda *args:data,'/dev/block/sda',1,1),data)

    def test_truncated_contaminated_and_failed_full_reads_rejected(self):
        for data in (bytes(4095),bytes(4096)+b'1+0 records out\n',
                     bytes(4096)+b'MYRON_READ_FAILED',b'MYRON_READ_FAILED'):
            with self.subTest(size=len(data)),self.assertRaisesRegex(ValueError,'expected 4096 bytes'):
                t.layout.read_blocks(lambda *args:data,'/dev/block/sda',1,1)

    def test_invalid_arguments_never_execute(self):
        for path,skip,count in [('/dev/block/sda;echo bad',0,1),('/dev/block/sda',-1,1),
                                ('/dev/block/sda',0,16385),('/dev/block/sda',0,True)]:
            with self.assertRaises(ValueError):
                t.layout.read_blocks(lambda *args:self.fail('must not execute'),path,skip,count)

    def test_boot_read_uses_clean_transport(self):
        r=t.Recovery.__new__(t.Recovery)
        with patch.object(r,'call',return_value=bytes(4096)) as call:
            self.assertEqual(r.read('/dev/block/sde11',4096,4096),bytes(4096))
            self.assertIn('2>/dev/null || printf MYRON_READ_FAILED',call.call_args.args[1])
            self.assertEqual(call.call_args.kwargs,{'timeout':300})

    def test_real_dd_with_merged_remote_streams(self):
        import shlex,shutil,subprocess
        if not shutil.which('sh') or not shutil.which('dd'):
            self.skipTest('POSIX shell transport integration test')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'disk.bin';data=bytes(range(256))*32;path.write_bytes(data)
            def remote(*args):
                self.assertEqual(args[0],'exec-out')
                command=args[1].replace('/dev/block/sda',shlex.quote(str(path)))
                return subprocess.run(['sh','-c',command],stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT,check=True).stdout
            old=subprocess.run(['sh','-c','dd if='+shlex.quote(str(path))+' bs=4096 count=1'],
                               stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True).stdout
            self.assertGreater(len(old),4096)
            self.assertEqual(t.layout.read_blocks(remote,'/dev/block/sda',1,1),data[4096:])
            with self.assertRaisesRegex(ValueError,'received 0 bytes'):
                t.layout.read_blocks(remote,'/dev/block/sda',2,1)
            path.unlink()
            with self.assertRaisesRegex(ValueError,'dd_failed=True'):
                t.layout.read_blocks(remote,'/dev/block/sda',0,1)


class ArchiveTests(unittest.TestCase):
    def test_actual_unpack_and_hash_checks(self):
        import struct,zipfile
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);raw=b'R'*8192;root_hash=hashlib.sha256(raw).hexdigest()
            header=bytearray(4096);header[:8]=b'ANDROID!';struct.pack_into('<I',header,40,4)
            data={'root-container.raw':raw,'policy-carrier.bin':b'P'*4096,
                  'root.img':bytes(header),'root-startup.img':bytes(header)}
            disk=dict(first=100000,last=100000+32*1024**3//4096-1,diskLast=100000+32*1024**3//4096+100,
                partitionGuid='c9f65538-0989-4306-b9a3-3c6db52ea120',partition_index=35,
                partition_bytes=32*1024**3,disk_guid='c9f65538-0989-4306-b9a3-3c6db52ea121')
            geo=t.layout.allocate(disk,8192,4096)
            manifest=dict(format=1,device='myron',partition='unixnu',device_bound=True,qualification_only=False,
                device_writes=0,requires_live_gpt_check=True,requires_fresh_android_boot_backup=True,
                files={n:dict(bytes=len(v),sha256=hashlib.sha256(v).hexdigest()) for n,v in data.items()},
                layout=disk,geometry=geo,root_writes=[dict(file='root-container.raw',partition_offset=0,bytes=8192),
                dict(file='policy-carrier.bin',partition_offset=geo['carrierOffset'],bytes=4096)])
            archive=base/'input.zip'
            with zipfile.ZipFile(archive,'w') as z:
                for n,v in data.items():z.writestr(n,v)
                z.writestr('deployment.json',json.dumps(manifest))
            with patch.object(t,'ARCHIVE_SHA',t.sha(archive)),patch.object(t,'ROOT_SHA',root_hash),patch.object(t,'ROOT_BYTES',8192):
                t.unpack(archive,base/'out')
                self.assertEqual(t.verify(base/'out'),manifest)
                (base/'out/root.img').write_bytes(b'X'*4096)
                with self.assertRaisesRegex(ValueError,'Changed package file'):t.verify(base/'out')
    def test_extra_archive_path_rejected(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);archive=base/'input.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside',b'bad')
            with patch.object(t,'ARCHIVE_SHA',t.sha(archive)):
                with self.assertRaisesRegex(ValueError,'paths'):t.unpack(archive,base/'out')
            self.assertFalse((base/'out').exists())


if __name__=='__main__':unittest.main()
