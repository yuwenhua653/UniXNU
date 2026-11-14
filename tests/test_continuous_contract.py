import struct
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from myron_continuous_contract import kernel_definitions, require_buffer_trace, BUFFER_TRACE_SYMBOLS, BUFFER_TRACE_MARKER
class ContractTests(unittest.TestCase):
    def sample(self,name=b'com.apple.kernel'):
        data=bytearray(512)
        struct.pack_into('<8I',data,0,0xfeedfacf,0x100000c,2,12,1,56,0,0)
        struct.pack_into('<IIQQII',data,32,0x80000035,56,0x1000,128,32,0)
        data[64:64+len(name)]=name
        struct.pack_into('<8I',data,128,0xfeedfacf,0x100000c,2,2,1,24,0,0)
        struct.pack_into('<6I',data,160,2,24,256,1,288,40)
        struct.pack_into('<IBBHQ',data,256,1,0xf,1,0,0x2000)
        data[289:309]=b'_boot_progress_init\0'
        return data
    def test_reads_member_without_outer_symtab(self):
        self.assertEqual(kernel_definitions(self.sample()),{'_boot_progress_init':0x2000})
    def test_rejects_other_member(self):
        with self.assertRaises(ValueError):kernel_definitions(self.sample(b'com.apple.other'))
    def test_rejects_truncated_table(self):
        raw=self.sample();struct.pack_into('<I',raw,168,500)
        with self.assertRaises(ValueError):kernel_definitions(raw)
    def test_rejects_unterminated_name(self):
        raw=self.sample();struct.pack_into('<I',raw,180,8);raw[289:296]=b'abcdefg'
        with self.assertRaises(ValueError):kernel_definitions(raw)
    def buffer_sample(self, missing=None, marker=True):
        names=sorted(BUFFER_TRACE_SYMBOLS-{missing})
        strings=b'\0';rows=[]
        for i,name in enumerate(names):
            rows.append((len(strings),0xf,1,0,0x3000+4*i))
            strings+=name.encode()+b'\0'
        string_offset=256+16*len(rows)
        data=bytearray(string_offset+len(strings)+len(BUFFER_TRACE_MARKER)+1)
        data[:184]=self.sample()[:184]
        struct.pack_into('<6I',data,160,2,24,256,len(rows),string_offset,len(strings))
        for i,row in enumerate(rows):struct.pack_into('<IBBHQ',data,256+16*i,*row)
        data[string_offset:string_offset+len(strings)]=strings
        if marker:data[-len(BUFFER_TRACE_MARKER)-1:-1]=BUFFER_TRACE_MARKER
        return data
    def test_buffer_hooks_required_in_final_nested_kernel(self):
        self.assertEqual(set(require_buffer_trace(self.buffer_sample())),BUFFER_TRACE_SYMBOLS)
        for name in BUFFER_TRACE_SYMBOLS:
            with self.subTest(name=name),self.assertRaises(ValueError):
                require_buffer_trace(self.buffer_sample(missing=name))
    def test_rejects_old_trace_even_with_correct_symbol_names(self):
        with self.assertRaises(ValueError):require_buffer_trace(self.buffer_sample(marker=False))
        with self.assertRaises(ValueError):require_buffer_trace(self.sample())
if __name__=='__main__':unittest.main()
