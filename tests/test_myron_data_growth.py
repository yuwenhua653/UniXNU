#!/usr/bin/env python3
"""Synthetic 4 GiB sparse-image checks; no physical disk or private data."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

p=argparse.ArgumentParser();p.add_argument('--reader-directory',type=Path,required=True);a,rest=p.parse_known_args()
sys.path[:0]=[str(a.reader_directory),str(Path(__file__).resolve().parents[1]/'myron-runtime')]
import data_growth as m

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.export=self.root/'input.zip';self.output=self.root/'NOT-FLASHABLE.raw'
        g=dict(first=1000,last=4000999,diskLast=5000000,partitionGuid='test',reserveBlocks=256,
               carrierOffset=(4000000-256)*4096,carrierCapacity=4096)
        layout={k:g[k] for k in ('first','last','diskLast','partitionGuid')};layout['partition_bytes']=4000000*4096
        self.d=dict(device='myron',partition='unixnu',device_bound=True,geometry=g,layout=layout,
                    files={'root-container.raw':{'bytes':1024**3}})
        first=m.old.geometry(self.d)
        marker=bytearray(4096);marker[:8]=b'MYRDATA1'
        struct.pack_into('<IIQQ',marker,8,1,2,first,m.old.WINDOW_BLOCKS+1)
        struct.pack_into('<I',marker,32,zlib.crc32(marker[:32]))
        header=bytearray(4096);header[:8]=b'SHNGDATA';struct.pack_into('<IIQ',header,8,1,64,m.old.PAGES)
        header[24:56]=bytes.fromhex(m.old.SEED);struct.pack_into('<I',header,60,zlib.crc32(header[:60]))
        bits=bytearray(32768);bits[0]=3;bits[-1]=128
        pages=b'A'*4096+b'B'*4096+b'C'*4096
        report=dict(read_only=True,device_writes=0,complete=True,seed_sha256=m.old.SEED,pages=m.old.PAGES,
                    marker_lba=first,present_pages=3,pages_sha256=hashlib.sha256(pages).hexdigest())
        self.entries={'marker.bin':marker,'overlay-header.bin':header,'bitmap.bin':bits,'pages.bin':pages,
                      'report.json':json.dumps(report).encode()}
    def make(self):
        with zipfile.ZipFile(self.export,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,data in self.entries.items():z.writestr(name,data)
    def test_sparse_clone_and_no_commit(self):
        self.make();original=self.export.read_bytes();plan=m.prepare(self.export,self.d,self.output)
        self.assertEqual(original,self.export.read_bytes());self.assertFalse(plan['flashable']);self.assertFalse(plan['apfs_resized'])
        self.assertEqual(plan['target_marker_lba']+m.BLOCKS,plan['source_marker_lba'])
        self.assertEqual(self.output.stat().st_size,m.BLOCKS*4096)
        with self.output.open('rb') as f:
            head=f.read(8192)
            self.assertEqual(struct.unpack_from('<I',head,12)[0],1)
            self.assertEqual(struct.unpack_from('<Q',head,4096+16)[0],m.PAGES)
            self.assertEqual(head[4096+24:4096+56].hex(),m.old.SEED)
            for i,byte in ((0,b'A'),(1,b'B'),(m.old.PAGES-1,b'C')):
                f.seek((2+m.BITMAP_BLOCKS+i)*4096);self.assertEqual(f.read(4096),byte*4096)
            f.seek((2+m.BITMAP_BLOCKS+m.old.PAGES)*4096);self.assertEqual(f.read(4096),bytes(4096))
        with self.assertRaisesRegex(ValueError,'Output exists'):m.prepare(self.export,self.d,self.output)
    def test_body_corruption_not_committed(self):
        self.entries['pages.bin']=b'X'+self.entries['pages.bin'][1:];self.make()
        with self.assertRaisesRegex(ValueError,'SHA256'):m.prepare(self.export,self.d,self.output)
        self.assertFalse(self.output.exists())
        with self.output.with_suffix('.raw.partial').open('rb') as f:self.assertEqual(struct.unpack_from('<I',f.read(4096),12)[0],1)
    def test_no_room(self):
        self.make();self.d['files']['root-container.raw']['bytes']=15*1024**3
        with self.assertRaises(ValueError):m.prepare(self.export,self.d,self.output)
        self.assertFalse(self.output.exists())
    def test_foreign_export(self):
        report=json.loads(self.entries['report.json']);report['marker_lba']+=1
        self.entries['report.json']=json.dumps(report).encode();self.make()
        with self.assertRaisesRegex(ValueError,'identity'):m.prepare(self.export,self.d,self.output)
    def test_bad_header_crc(self):
        self.entries['overlay-header.bin'][60]^=1;self.make()
        with self.assertRaisesRegex(ValueError,'CRC'):m.prepare(self.export,self.d,self.output)

unittest.main(argv=[sys.argv[0],*rest])
