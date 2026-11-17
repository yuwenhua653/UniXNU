import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('analysis',Path(__file__).resolve().parents[1]/'myron27-launchd-analysis.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
B=0x100000000

def fixture():
    data=bytearray(0x900)
    sections=[]
    for name,at,size,flags,stride in [(b'__text',0x400,0x100,0x80000400,0),
                                     (b'__stubs',0x500,12,8,12),(b'__cstring',0x600,32,2,0)]:
        sections.append(struct.pack('<16s16sQQ8I',name,b'__TEXT',B+at,size,at,2,0,0,flags,0,stride,0))
    seg=struct.pack('<II16s4Q4I',0x19,72+240,b'__TEXT',B,0x900,0,0x900,7,5,3,0)+b''.join(sections)
    dys=[0]*18;dys[12:14]=[0x770,1]
    commands=(seg+struct.pack('<4I',0x26,16,0x700,5)+struct.pack('<6I',2,24,0x720,2,0x750,16)+
              struct.pack('<20I',0xb,80,*dys)+struct.pack('<II16s',0x1b,24,b'fixture-uuid-123'))
    data[:32]=struct.pack('<8I',0xfeedfacf,0x100000c,2,2,5,len(commands),0,0)
    data[32:32+len(commands)]=commands
    for pc,target in [(0x40c,0x500),(0x42c,0x400),(0x44c,0x420)]:
        struct.pack_into('<I',data,pc,0x94000000|(((target-pc)//4)&0x3ffffff))
    struct.pack_into('<2I',data,0x440,0x90000000,0x91180000)
    data[0x600:0x60d]=b'reboot reason'
    data[0x700:0x705]=b'\x80\x08\x20\x20\0'
    struct.pack_into('<IBBHQ',data,0x720,1,0xe,1,0,B+0x400)
    struct.pack_into('<IBBHQ',data,0x730,7,1,0,0,0)
    data[0x750:0x760]=b'\0_main\0_reboot\0\0\0'
    struct.pack_into('<I',data,0x770,1)
    info=dict(sha256=hashlib.sha256(data).hexdigest(),slice_offset=0,slice_bytes=len(data),
              code_directories=[dict(code_limit=len(data),original_trust_match=True)])
    return bytes(data),info

class Tests(unittest.TestCase):
    def test_relocated_return_addresses_and_call_chain(self):
        data,info=fixture();e=m.Executable(data,info)
        frames=tuple((B+n+0x6000,) for n in (0x410,0x430,0x450))
        cs=m.candidates(e,frames)
        self.assertEqual(len(cs),1)
        self.assertEqual(cs[0]['slide'],'0x6000')
        self.assertEqual(cs[0]['first_import'],'_reboot')
        self.assertEqual(cs[0]['matched_edges'],2)
        self.assertEqual(e.describe(B+0x440)['string_references'][0]['text'],'reboot reason')
        self.assertEqual(e.describe(B+0x400)['symbols'],['_main'])

    def test_wrong_return_address_and_ambiguity(self):
        data,info=fixture();e=m.Executable(data,info)
        frames=((B+0x410+0x6000,B+0x412+0x6000),(B+0x430+0x6000,),(B+0x450+0x6000,))
        # Unaligned transcription candidates must be rejected, not decoded.
        self.assertEqual(len(m.candidates(e,frames)),1)

    def test_unsigned_and_malformed_inputs(self):
        data,info=fixture()
        bad=bytearray(data);struct.pack_into('<I',bad,20,0xffffffff)
        with self.assertRaises(ValueError):m.Executable(bad,info)
        bad=bytearray(data);bad[0x704]=0x80
        with self.assertRaises(ValueError):m.Executable(bad,info)
        bad=bytearray(data);struct.pack_into('<I',bad,0x770,99)
        with self.assertRaises(ValueError):m.Executable(bad,info)
        with self.assertRaises(ValueError):m.Executable(data[:0x700],info)

    def test_executable_identity_change(self):
        data,info=fixture()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'launchd';p.write_bytes(data+b'x')
            with self.assertRaisesRegex(ValueError,'changed after audit'):m.inspect(p,info)

if __name__=='__main__':unittest.main()
