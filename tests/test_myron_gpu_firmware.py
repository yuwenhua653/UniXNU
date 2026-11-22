#!/usr/bin/env python3
"""Reject corrupted or writable linked GPU firmware; no device execution."""
import hashlib
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'myron-gpu/native'))
from gpu_firmware_audit import verify


def fixture():
    raw = bytearray(0x6000)
    struct.pack_into('<i', raw, 60, 1)
    symbols, pins = {}, {}
    for i, kind in enumerate(('gmu', 'sqe', 'aqe', 'zap'), 1):
        at = i*0x1000
        payload = bytes([i])*16
        raw[at:at+16] = payload
        struct.pack_into('<Q', raw, at+16, len(payload))
        symbols[at] = ['_myron_'+kind+'_firmware']
        symbols[at+16] = ['_myron_'+kind+'_firmware_size']
        pins['gen80200_'+kind+'.bin'] = dict(bytes=16,sha256=hashlib.sha256(payload).hexdigest())
    image = SimpleNamespace(data=raw, symbols=lambda:symbols,
        sections=[dict(segment='__TEXT',name='__myron_gpu',va=0x1000,size=0x4000)],
        segments=[dict(name='__TEXT',command_offset=0)], read=lambda a,n:bytes(raw[a:a+n]))
    return image,pins,symbols


class FirmwareAudit(unittest.TestCase):
    def test_all_four_firmware_payloads(self):
        image,pins,_=fixture()
        report=verify(image,pins)
        self.assertEqual(len(report['firmware']),4)
        self.assertTrue(report['read_only'])
        self.assertFalse(report['hardware_tested'])

    def test_rejects_hash_size_and_mapping_errors(self):
        for failure in ('hash','size','writable','section','overlap','outside'):
            with self.subTest(failure=failure):
                image,pins,symbols=fixture()
                if failure=='hash':image.data[0x1000]^=1
                if failure=='size':image.data[0x1010]^=1
                if failure=='writable':struct.pack_into('<i',image.data,60,3)
                if failure=='section':image.sections[0]['segment']='__DATA_CONST'
                if failure=='overlap':symbols[0x1000]+=symbols.pop(0x2000)
                if failure=='outside':image.sections[0]['size']=0x3000
                with self.assertRaises(ValueError):verify(image,pins)


if __name__=='__main__':unittest.main()
