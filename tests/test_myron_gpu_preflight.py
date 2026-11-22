#!/usr/bin/env python3
"""Check preflight provider ordering; object fixtures do not claim a native build."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

parser = argparse.ArgumentParser()
parser.add_argument('--device', type=Path, required=True)
args, rest = parser.parse_known_args()
sys.path[:0] = [str(args.device.resolve()/p) for p in ('', 'gpu', 'display')]
import root_runtime as runtime
import gpu_build


def info(defined=(), undefined=()):
    return dict(defined=dict.fromkeys(defined, 0), external_defined=set(defined),
                undefined=set(undefined), sections=[])


class GpuPreflight(unittest.TestCase):
    def run_preflight(self, enabled=True, missing_entry=False, missing_dependency=False, compile_error=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tree, out = root/'tree', root/'out'
            out.mkdir()
            kernel = root/'kernel/kernel.macho'
            kernel.parent.mkdir()
            kernel.write_bytes(b'kernel')
            objects = {b'kernel': info({'_kernel_api'})}
            events = []
            def obj(name, value):
                path = out/name
                path.write_bytes(name.encode())
                objects[name.encode()] = value
                return path
            def compile_unit(command, directory, output, env, target):
                name = output.stem
                required = {'_myron_start_data', '_native_ram_block_volume_seed', '__ZTV14NativeRamBlock'}
                value = info(required if name == 'MyronUfsProbe' else (),
                             {'_myron_gpu_start'} if name == 'MyronStorageBoot' and enabled else ())
                obj(output.name, value)
                return value
            def support(*a):
                return [], obj('bsd.o', info()), []
            def other(*a):
                return obj('support.o', info()), {}
            def gpu(*a):
                events.append('gpu')
                if compile_error:
                    raise ValueError('injected native GPU compiler failure')
                symbols = set() if missing_entry else {'_myron_gpu_start'}
                needs = {'_unprovided_gpu_api'} if missing_dependency else {'_kernel_api'}
                return [obj('gpu.o', info(symbols, needs))], (), {'fixture': True}
            contract = runtime.root_import_contract
            def imports(*a):
                events.append('imports')
                return contract(*a)
            builder = mock.Mock()
            with contextlib.ExitStack() as stack:
                for name, value in [('compile_unit', compile_unit), ('compile_support', support),
                                    ('compile_systemos', other), ('compile_manifest', other),
                                    ('compile_shared_cache', other), ('root_import_contract', imports),
                                    ('macho', lambda data, kind: objects[data])]:
                    stack.enter_context(mock.patch.object(runtime, name, side_effect=value))
                stack.enter_context(mock.patch('display_build.compile_display', return_value=([], (), {}, {})))
                stack.enter_context(mock.patch.object(gpu_build, 'compile_gpu', side_effect=gpu))
                env = {'MYRON_GPU_NATIVE': '1' if enabled else '0'}
                error = None
                try:
                    runtime.compile_preflight(tree, root, out, args.device.resolve(),
                        {'directory': str(root)}, builder, None, env, [], [])
                except ValueError as exc:
                    error = str(exc)
            return error, json.loads((out/'root-preflight.json').read_text()), events

    def test_enabled_provider_precedes_import_check(self):
        error, report, events = self.run_preflight()
        self.assertIsNone(error)
        self.assertEqual(events, ['gpu', 'imports'])
        self.assertTrue(report['passed'])
        self.assertFalse(report['kernel_linked'])

    def test_disabled_gpu_does_not_compile(self):
        error, report, events = self.run_preflight(enabled=False)
        self.assertIsNone(error)
        self.assertEqual(events, ['imports'])

    def test_missing_entry_is_not_allowlisted(self):
        error, report, _ = self.run_preflight(missing_entry=True)
        self.assertIn('_myron_gpu_start', error)
        self.assertFalse(report['passed'])

    def test_gpu_dependencies_are_also_checked(self):
        error, report, _ = self.run_preflight(missing_dependency=True)
        self.assertIn('_unprovided_gpu_api', error)
        self.assertFalse(report['passed'])

    def test_compile_failure_cannot_pass_import_check(self):
        error, report, events = self.run_preflight(compile_error=True)
        self.assertIn('injected native GPU compiler failure', error)
        self.assertFalse(report['passed'])
        self.assertEqual(events, ['gpu'])

    def test_native_compile_checks_later_units_but_never_returns_partial_set(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recipe = root/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'
            recipe.parent.mkdir(parents=True)
            record = {'directory': str(root)}
            recipe.write_text(json.dumps(record))
            out = root/'gpu-out'
            compiled = []
            def command(rec, source, output, *rest):
                return ['compiler', str(source), '-o', str(output)]
            def run(cmd, **kw):
                source, output = Path(cmd[1]), Path(cmd[3])
                compiled.append(source.name)
                failed = source.name in ('NativeAdrenoCpu.cpp', 'MyronHfi.c')
                if failed:
                    kw['stdout'].write('injected compiler error: '+source.name)
                else:
                    output.write_bytes(b'object')
                return SimpleNamespace(returncode=int(failed))
            builder = SimpleNamespace(compile_command=command)
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(gpu_build, 'firmware_inputs', return_value={}))
                stack.enter_context(mock.patch.object(gpu_build, 'stage', return_value={}))
                stack.enter_context(mock.patch.object(gpu_build, 'sha', return_value='fixture-sha'))
                stack.enter_context(mock.patch.object(gpu_build.subprocess, 'check_output', return_value=str(root)))
                stack.enter_context(mock.patch.object(gpu_build.subprocess, 'run', side_effect=run))
                stack.enter_context(mock.patch('build_ufs_dormant.macho', return_value=info()))
                stack.enter_context(mock.patch('display_build.check_object_imports'))
                with self.assertRaisesRegex(ValueError, 'GPU native compilation failed') as caught:
                    gpu_build.compile_gpu(root, args.device.resolve(), out, builder, mock.Mock(),
                        {'MYRON_GPU_NATIVE': '1', 'MYRON_GPU_FIRMWARE': str(root)}, record)
            self.assertIn('NativeAdrenoCpu.cpp', str(caught.exception))
            self.assertIn('MyronHfi.c', str(caught.exception))
            self.assertIn('AdrenoPM4.c', compiled)
            self.assertEqual(len(compiled), len(gpu_build.CPP)+7)
            report = json.loads((out/'gpu-build.json').read_text())
            self.assertEqual(len(report['failures']), 2)
            self.assertFalse(report['native_objects_compiled'])
            self.assertFalse((out/'MyronGpuStart.cpp').exists())


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *rest])
