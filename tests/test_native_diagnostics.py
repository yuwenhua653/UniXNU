"""Exercise missing-report failure evidence and bounded native replay capture."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', REPO/'myron27-collect-native-checks.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class DiagnosticsTests(unittest.TestCase):
    def test_preserves_prelink_traceback_and_only_source_built_replay_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            root = temp/'myron-private-native/myron-iphone27'
            selected = ['desktop/ufs-root-prelink.log', 'desktop/ufs-root-prelink-command.json',
                        'desktop/ufs-root-prelink.json', 'desktop/ufs/root/kernel/kernel.macho',
                        'out/myron/build/fileset-reference/mach.release.noctf',
                        'desktop/ufs/root/display/display-abi.json']
            rejected = ['desktop/prelinked-ufs-root/kernel.macho', 'desktop/ipsw/kernelcache.decompressed',
                        'private-userland/desktop/ufs-root-prelink.log',
                        'references/fileset-reference/mach.release.noctf',
                        'qualification/root-media/desktop/ufs-root-prelink.log',
                        'device-package/root-container.raw', 'desktop/secret.bin']
            for name in selected + rejected:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            output = temp/'checks'
            result = collector.collect(temp,output)
            self.assertEqual(result['errors'],[])
            prefix = 'myron-private-native/myron-iphone27/'
            self.assertEqual(set(result['files']),{prefix+name for name in selected})
            self.assertEqual(set(result['source_built_replay_inputs']),
                             {prefix+selected[3],prefix+selected[4]})
            for row in result['source_built_replay_inputs'].values():
                self.assertEqual(row,dict(bytes=7,sha256=hashlib.sha256(b'fixture').hexdigest()))

    def test_actual_stage_runner_prints_traceback_and_preserves_exit_status(self):
        delta = json.loads((REPO/'myron27-display-delta.json').read_text())
        source = delta['files']['device/myron27/prepare_desktop.py']['content']
        main = next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='main')
        runner = next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        module = ast.Module(body=[runner],type_ignores=[])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            scope = dict(out=directory,tree=directory,json=json,subprocess=subprocess)
            exec(compile(module,'prepare_desktop.py','exec'),scope)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(subprocess.CalledProcessError) as caught:
                    scope['run']('ufs-root-prelink',[sys.executable,'-c',
                        "raise ValueError('prelink failed before kernel.json')"])
            self.assertEqual(caught.exception.returncode,1)
            self.assertIn('ValueError: prelink failed before kernel.json',stdout.getvalue())
            self.assertIn('ufs-root-prelink.log',stdout.getvalue())
            self.assertFalse((directory/'kernel.json').exists())
            self.assertTrue((directory/'ufs-root-prelink-command.json').is_file())
            scope['run']('passing',[sys.executable,'-c','pass'])

if __name__ == '__main__':
    unittest.main()
