import struct
import ast
import json
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from myron_continuous_contract import kernel_definitions, require_buffer_trace, BUFFER_TRACE_SYMBOLS, BUFFER_TRACE_MARKER, require_exit_trace, EXIT_TRACE_SYMBOLS, EXIT_TRACE_MARKER
from myron_continuous_contract import require_lockdown_state, LOCKDOWN_STATE_SYMBOLS, REBOOT_TRACE_MARKER, CONSOLE_ROUTE_MARKER, SHUTDOWN_LOG_MARKER, SHUTDOWN_LOG_REASON_MARKERS, SHUTDOWN_LOG_SYMBOLS
from myron_continuous_contract import require_cpu_display, DISPLAY_SYMBOLS
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
    def buffer_sample(self, missing=None, marker=True, symbols=BUFFER_TRACE_SYMBOLS, text=BUFFER_TRACE_MARKER+b"\0"+REBOOT_TRACE_MARKER+b"\0"+CONSOLE_ROUTE_MARKER+b"\0"+b"\0".join(SHUTDOWN_LOG_REASON_MARKERS)):
        names=sorted(symbols-{missing})
        strings=b'\0';rows=[]
        for i,name in enumerate(names):
            rows.append((len(strings),0xf,1,0,0x3000+4*i))
            strings+=name.encode()+b'\0'
        string_offset=256+16*len(rows)
        data=bytearray(string_offset+len(strings)+len(text)+1)
        data[:184]=self.sample()[:184]
        struct.pack_into('<6I',data,160,2,24,256,len(rows),string_offset,len(strings))
        for i,row in enumerate(rows):struct.pack_into('<IBBHQ',data,256+16*i,*row)
        data[string_offset:string_offset+len(strings)]=strings
        if marker:data[-len(text)-1:-1]=text
        return data
    def test_buffer_hooks_required_in_final_nested_kernel(self):
        self.assertEqual(set(require_buffer_trace(self.buffer_sample())),BUFFER_TRACE_SYMBOLS)
        for name in BUFFER_TRACE_SYMBOLS:
            with self.subTest(name=name),self.assertRaises(ValueError):
                require_buffer_trace(self.buffer_sample(missing=name))
    def test_rejects_old_trace_even_with_correct_symbol_names(self):
        with self.assertRaises(ValueError):require_buffer_trace(self.buffer_sample(marker=False))
        with self.assertRaises(ValueError):require_buffer_trace(self.sample())
        with self.assertRaises(ValueError):require_buffer_trace(self.buffer_sample(text=BUFFER_TRACE_MARKER))
        with self.assertRaises(ValueError):require_buffer_trace(self.buffer_sample(text=REBOOT_TRACE_MARKER))
        with self.assertRaises(ValueError):require_buffer_trace(self.buffer_sample(text=BUFFER_TRACE_MARKER+b"\0"+REBOOT_TRACE_MARKER))
    def test_accepts_inlined_heading_with_real_recorder(self):
        raw=self.buffer_sample()
        self.assertNotIn(SHUTDOWN_LOG_MARKER, raw)
        self.assertEqual(set(require_buffer_trace(raw)), BUFFER_TRACE_SYMBOLS)
    def test_reason_strings_and_retained_state_are_mandatory(self):
        text=BUFFER_TRACE_MARKER+b"\0"+REBOOT_TRACE_MARKER+b"\0"+CONSOLE_ROUTE_MARKER+b"\0"+b"\0".join(SHUTDOWN_LOG_REASON_MARKERS)
        for marker in (CONSOLE_ROUTE_MARKER, *SHUTDOWN_LOG_REASON_MARKERS):
            with self.subTest(marker=marker),self.assertRaisesRegex(ValueError,'markers='):
                require_buffer_trace(self.buffer_sample(text=text.replace(marker,b'X'*len(marker))))
        # A heading appended to an old kernel must not qualify a new recorder.
        old=self.buffer_sample(symbols=BUFFER_TRACE_SYMBOLS-SHUTDOWN_LOG_SYMBOLS,
                               text=text+b"\0"+SHUTDOWN_LOG_MARKER)
        with self.assertRaisesRegex(ValueError, '_shutdown_log_match'):
            require_buffer_trace(old)
    def test_log_driver_is_checked_only_after_its_link_stage(self):
        # The early native kernel contains the recorder but not the later UFS object.
        # Inspect the actual early verifier definition, not a duplicated symbol list.
        root=Path(__file__).resolve().parents[1]
        delta=json.loads((root/'myron27-reboot-delta.json').read_text())
        source=delta['files']['device/myron27/verify_native_artifact.py']['content']
        verify=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='verify')
        assignments=[n for n in ast.walk(verify) if isinstance(n,ast.Assign) and
                     any(isinstance(t,ast.Name) and t.id=='required' for t in n.targets)]
        self.assertEqual(len(assignments),1)
        expression=ast.Expression(body=assignments[0].value)
        native=eval(compile(expression,'native-required','eval'),{'__builtins__':{},'USER_VA_SYMBOLS':frozenset()})
        driver={'_myron_log_state','_myron_log_rounds','_myron_log_errors','_myron_log_first_lba'}
        self.assertFalse(native & driver, 'UFS log driver is not linked in native-prelink-input')
        self.assertIn('_myron_boot_log_snapshot',native)
        self.assertTrue(driver <= BUFFER_TRACE_SYMBOLS)
        # The final product must still refuse every missing driver definition.
        for name in driver:
            with self.subTest(name=name),self.assertRaises(ValueError):
                require_buffer_trace(self.buffer_sample(missing=name))

    def test_exit_trace_required_in_final_nested_kernel(self):
        sample=lambda **kw:self.buffer_sample(symbols=EXIT_TRACE_SYMBOLS,text=EXIT_TRACE_MARKER,**kw)
        self.assertEqual(set(require_exit_trace(sample())),EXIT_TRACE_SYMBOLS)
        for name in EXIT_TRACE_SYMBOLS:
            with self.subTest(name=name),self.assertRaises(ValueError):require_exit_trace(sample(missing=name))
        with self.assertRaises(ValueError):require_exit_trace(sample(marker=False))
        with self.assertRaises(ValueError):require_exit_trace(self.buffer_sample())
    def test_public_lockdown_state_requires_oid_and_handler(self):
        sample=lambda **kw:self.buffer_sample(symbols=LOCKDOWN_STATE_SYMBOLS,**kw)
        self.assertEqual(set(require_lockdown_state(sample())),LOCKDOWN_STATE_SYMBOLS)
        for name in LOCKDOWN_STATE_SYMBOLS:
            with self.subTest(name=name),self.assertRaises(ValueError):require_lockdown_state(sample(missing=name))
        # A diagnostic string is not an implemented sysctl registration.
        with self.assertRaises(ValueError):require_lockdown_state(self.buffer_sample(text=b'lockdown_mode_state_public'))
    def test_cpu_display_requires_backend_and_real_handoff(self):
        sample=lambda **kw:self.buffer_sample(symbols=DISPLAY_SYMBOLS,**kw)
        self.assertEqual(set(require_cpu_display(sample())),DISPLAY_SYMBOLS)
        for name in DISPLAY_SYMBOLS:
            with self.subTest(name=name),self.assertRaises(ValueError):require_cpu_display(sample(missing=name))
        with self.assertRaises(ValueError):require_cpu_display(self.buffer_sample(text=b'myron GOP display registered'))
if __name__=='__main__':unittest.main()


