#!/usr/bin/env python3
"""Exercise seed identity and app budgeting before a native build."""
import argparse
import ast
import hashlib
import json
import re
import plistlib
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True);p.add_argument('--seed',type=Path)
a,rest=p.parse_known_args();sys.path.insert(0,str(a.device.resolve()))
import staged_apps as apps
import reuse_data_seed as seed
import prepare_data_volume as volume

class Upgrade(unittest.TestCase):
    def test_actual_migration_preserves_user_preferences_and_propagates_errors(self):
        fixture=Path(__file__).parent/'fixtures'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=root/'plan.json'
            plan.write_text(json.dumps(dict(build='24A446',selected=['Calculator.app'],allocation_bytes=6<<20)))
            code=apps.source((fixture/'myron-staged-apps-upstream.c').read_text(),plan)
            start=code.index('static int\nmyron_apps_request_migration(')
            end=code.index('static void\nnative_staged_apps_prepare(',start)
            function=re.sub(r'\b(proc_t|user_addr_t|vfs_context_t|vnode_t|unlink_args|unlink)\b',
                            r'test_\1',code[start:end]).replace('(caddr_t)','(char *)')
            expected=plistlib.dumps(volume.desktop_preferences()['com.apple.migration'],fmt=plistlib.FMT_BINARY)
            source=(fixture/'myron-app-migration-host.c').read_text().replace('/* GENERATED_FUNCTION */',function)
            source=source.replace('EXPECTED_BYTES',','.join(map(str,expected)))
            (root/'test.c').write_text(source)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True)

    def test_payload_argument_reaches_actual_app_copy_guard(self):
        # Use the generated payload argument and the generated production guard,
        # rather than separately reimplementing an enable flag in this test.
        tree=ast.parse((a.device/'boot_assets.py').read_text())
        values={n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
        arg,=[v for v in values if v.startswith('staged-apps=')]
        upstream=(Path(__file__).parent/'fixtures/myron-staged-apps-upstream.c').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=root/'plan.json'
            plan.write_text(json.dumps(dict(build='24A446',selected=['Calculator.app'],allocation_bytes=6<<20)))
            code=apps.source(upstream,plan)
            start=code.index('static void\nnative_staged_apps_prepare(')
            end=code.index('\tvfs_context_t ctx =',start)
            guard=code[start:end]+'    (void)p;(void)scratch;(void)data_mount;++entered;\n}\n'
            # Darwin already defines user_addr_t (with a different C spelling).
            # Namespace only fixture types; exercise the production guard unchanged.
            guard=re.sub(r'\b(proc_t|user_addr_t|mount_t)\b',r'test_\1',guard)
            shim='''#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <assert.h>
typedef void *test_proc_t; typedef uintptr_t test_user_addr_t; typedef void *test_mount_t;
static unsigned entered;static const char *bootarg;
static int PE_parse_boot_argn(const char *name,void *out,int size){
 size_t n=strlen(name);if(size!=4 || strncmp(bootarg,name,n) || bootarg[n]!='=')return 0;
 *(uint32_t*)out=(uint32_t)atoi(bootarg+n+1);return 1;
}
'''+guard+'''int main(int argc,char **argv){
 assert(argc==3);bootarg=argv[1];native_staged_apps_prepare(0,0,0);
 assert(entered==(unsigned)atoi(argv[2]));return 0;
}
'''
            src=root/'guard.c';src.write_text(shim);exe=root/'guard'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
            for value,expected in [(arg,'1'),('','0'),('staged-apps=0','0'),('staged-apps=2','0'),('sheng-staged-apps=1','0')]:
                subprocess.run([str(exe),value,expected],check=True)
            empty=apps.source(upstream,root/'absent-plan.json')
            start=empty.index('static void\nnative_staged_apps_prepare(')
            end=empty.index('\tvfs_context_t ctx =',start)
            empty_guard=empty[start:end]+'    (void)p;(void)scratch;(void)data_mount;++entered;\n}\n'
            empty_guard=re.sub(r'\b(proc_t|user_addr_t|mount_t)\b',r'test_\1',empty_guard)
            src.write_text(shim.replace(guard,empty_guard))
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe),arg,'0'],check=True)

    def test_budget_skips_oversized_tree_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'apps';src.mkdir()
            for name in ('MobileNotes.app','Big.app','Small.app','Linked.app'):
                (src/name).mkdir();(src/name/'signed-code').write_bytes(b'original')
            (src/'Linked.app/link').symlink_to(root)
            sizes={'MobileNotes.app':20<<20,'Big.app':2<<30,'Small.app':40<<20,'Linked.app':1}
            with patch.object(volume,'tree_usage',side_effect=lambda path,**kw:dict(allocation_estimate=sizes[path.name])):
                plan=apps.plan(src,root/'plan.json')
            self.assertEqual(plan['selected'],['MobileNotes.app','Small.app'])
            self.assertEqual(plan['allocation_bytes'],60<<20)
            self.assertFalse(plan['all_selected'])
            self.assertEqual((src/'MobileNotes.app/signed-code').read_bytes(),b'original')
    def test_empty_and_oversized_source_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'apps';src.mkdir()
            with self.assertRaises(ValueError):apps.plan(src,root/'plan.json')
            (src/'Big.app').mkdir()
            with patch.object(volume,'tree_usage',return_value=dict(allocation_estimate=apps.BUDGET+1)):
                with self.assertRaises(ValueError):apps.plan(src,root/'plan.json')
    def test_exact_upstream_transform_is_fail_closed(self):
        upstream=(Path(__file__).parent/'fixtures/myron-staged-apps-upstream.c').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            plan=Path(tmp)/'plan.json';plan.write_text(json.dumps(dict(build='24A446',selected=['MobileNotes.app'],allocation_bytes=20<<20)))
            code=apps.source(upstream,plan)
            self.assertIn('!strcmp(name,"MobileNotes.app")',code)
            self.assertIn('space->f_bavail <= 0',code)
            self.assertIn('mach_vm_allocate_kernel(map,&scratch,4096',code)
            self.assertIn('mach_vm_deallocate(map,scratch,4096)',code)
            self.assertIn('memcmp(bytes,expected,sizeof expected)',code)
            self.assertIn('VNOP_FSYNC(marker, MNT_WAIT, ctx)',code)
            with self.assertRaises(ValueError):apps.source(upstream.replace('O_CREAT | O_TRUNC','O_CREAT',1).replace('const uint32_t chunk = 1024 * 1024','const uint32_t chunk = 4096'),plan)
            plan.write_text(json.dumps(dict(build='24A446',selected=['../escape'],allocation_bytes=0)))
            with self.assertRaises(ValueError):apps.source(upstream,plan)
    def test_foreign_seed_never_creates_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);foreign=root/'foreign';foreign.write_bytes(bytes(4096))
            with self.assertRaises(ValueError):seed.unpack(foreign,root/'raw')
            self.assertFalse((root/'raw').exists())
    @unittest.skipUnless(a.seed,'exact retained package input required')
    def test_real_seed_roundtrip_and_bit_flip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);report=seed.unpack(a.seed,root/'raw')
            self.assertEqual(report['logical_sha256'],seed.LOGICAL)
            with (root/'raw').open('rb') as stream:
                self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),seed.LOGICAL)
            bad=bytearray(a.seed.read_bytes());bad[-1]^=1;(root/'bad').write_bytes(bad)
            with self.assertRaises(ValueError):seed.unpack(root/'bad',root/'bad-raw')
            self.assertFalse((root/'bad-raw').exists())

if __name__=='__main__':unittest.main(argv=[sys.argv[0],*rest])
