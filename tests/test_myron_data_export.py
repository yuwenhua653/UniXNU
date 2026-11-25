#!/usr/bin/env python3
"""Exercise the real exporter against a read-only sparse block peer."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

p=argparse.ArgumentParser();p.add_argument('--reader-directory',type=Path,required=True);args,rest=p.parse_known_args()
sys.path.insert(0,str(args.reader_directory))
spec=importlib.util.spec_from_file_location('exporter',Path(__file__).resolve().parents[1]/'myron-runtime/export_data.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Peer:
    def __init__(self):
        self.g=dict(first=1000,last=1000999,diskLast=2000000,partitionGuid='test',reserveBlocks=256,
            carrierOffset=(1000000-256)*4096,carrierCapacity=4096)
        self.layout_value={k:self.g[k] for k in ('first','last','diskLast','partitionGuid')}
        self.layout_value['partition_bytes']=1000000*4096
        self.d=dict(device='myron',partition='unixnu',device_bound=True,geometry=self.g,layout=self.layout_value,
            files={'root-container.raw':{'bytes':4096}})
        self.first=m.geometry(self.d);self.reads=[];self.flip=False;self.short=False
        self.marker=bytearray(4096);self.marker[:8]=b'MYRDATA1'
        struct.pack_into('<IIQQ',self.marker,8,1,2,self.first,m.WINDOW_BLOCKS+1)
        struct.pack_into('<I',self.marker,32,zlib.crc32(self.marker[:32]))
        self.header=bytearray(4096);self.header[:8]=b'SHNGDATA'
        struct.pack_into('<IIQ',self.header,8,1,64,m.PAGES)
        self.header[24:56]=bytes.fromhex(m.SEED);self.crc()
        self.bitmap=bytearray(32768);self.bitmap[0]=3;self.bitmap[-1]=128
    def crc(self):struct.pack_into('<I',self.header,60,zlib.crc32(self.header[:60]))
    def layout(self):return self.layout_value,(b'primary',b'backup')
    def read(self,lba,n):
        assert self.first<=lba and lba+n<=self.first+m.WINDOW_BLOCKS+1 and 0<n<=128
        self.reads.append((lba,n))
        if lba==self.first:return bytes(self.marker)
        if lba==self.first+1:return bytes(self.header)
        if lba==self.first+2:
            data=bytes(self.bitmap)
            if self.flip and self.reads.count((lba,n))>1:data=b'X'+data[1:]
            return data
        index=lba-self.first-2-m.BITMAP_BLOCKS
        data=b''.join(bytes([65+(i%3)])*4096 for i in range(index,index+n))
        return data[:-1] if self.short else data

class Tests(unittest.TestCase):
    def run_export(self,peer):
        return m.capture(peer,peer.d,self.out)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.out=Path(self.tmp.name)/'data.zip'
    def test_sparse_export(self):
        peer=Peer();self.run_export(peer)
        with zipfile.ZipFile(self.out) as z:
            self.assertIsNone(z.testzip());report=json.loads(z.read('report.json'));data=z.read('pages.bin')
            self.assertEqual(len(data),3*4096);self.assertEqual(data,b'A'*4096+b'B'*4096+b'A'*4096)
            self.assertEqual(report['pages_sha256'],hashlib.sha256(data).hexdigest())
            self.assertTrue(report['complete']);self.assertEqual(report['device_writes'],0)
        self.assertEqual(len(peer.reads),8)
    def test_foreign_seed(self):
        peer=Peer();peer.header[24]^=1;peer.crc()
        with self.assertRaisesRegex(ValueError,'different seed'):self.run_export(peer)
        self.assertEqual(len(peer.reads),3);self.assertFalse(self.out.exists())
    def test_corrupt_marker(self):
        peer=Peer();peer.marker[32]^=1
        with self.assertRaisesRegex(ValueError,'marker CRC'):self.run_export(peer)
    def test_mutated_bitmap_keeps_partial(self):
        peer=Peer();peer.flip=True
        with self.assertRaisesRegex(ValueError,'metadata changed'):self.run_export(peer)
        self.assertFalse(self.out.exists());self.assertTrue(self.out.with_suffix('.zip.partial').exists())
    def test_short_body(self):
        peer=Peer();peer.short=True
        with self.assertRaisesRegex(ValueError,'Short Data'):self.run_export(peer)
        self.assertFalse(self.out.exists())
    def test_root_overlap(self):
        peer=Peer();peer.d['files']['root-container.raw']['bytes']=(peer.first-peer.g['first'])*4096
        with self.assertRaisesRegex(ValueError,'overlaps'):self.run_export(peer)
        self.assertFalse(peer.reads)

unittest.main(argv=[sys.argv[0],*rest])
