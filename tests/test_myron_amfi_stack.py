#!/usr/bin/env python3
"""Execute patched stack_init, preserve guards, and reject wrong import scopes.

The host harness checks stack geometry, not live AMFI execution. Original AMFI
conversion was also replayed offline with successful OSObject test doubles;
full donor/code/import identity is checked against the actual IPSW in CI.
"""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
import tempfile

p = argparse.ArgumentParser(description=__doc__)
for name in ('device', 'upstream', 'xnu'):
    p.add_argument('--' + name, type=Path, required=True)
p.add_argument('--cc', default='clang')
a = p.parse_args()
roots = dict(device=a.device.resolve(), arch=a.upstream.resolve()/'profiles/arch/arm64e',
             os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subject = 'osfmk/kern/stack.c'
with tempfile.TemporaryDirectory() as tmp:
    w = Path(tmp); target = w/subject; target.parent.mkdir(parents=True)
    before = (a.xnu/subject).read_text(); target.write_text(before)
    applied = []
    for scope in ('arch', 'os', 'device'):
        series = roots[scope]/'patches/xnu/series'
        for line in series.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'): continue
            prefix, sep, tail = line.partition(':')
            patch = (roots[prefix]/tail if sep else series.parent/line).resolve()
            if '+++ b/' + subject not in patch.read_text(): continue
            subprocess.run(['git', 'apply', '--include=' + subject, str(patch)], cwd=w, check=True)
            applied.append(patch.name)
    assert applied == ['myron-amfi-stack-alignment.patch'], applied
    after = target.read_text()
    # Allocation/free and both lower guards/upper guard remain byte-identical.
    marker = 'STARTUP(TUNABLES, STARTUP_RANK_MIDDLE, stack_init);'
    assert before.split(marker, 1)[1] == after.split(marker, 1)[1]
    assert 'kernel_stack_size + ptoa(3), stack_addr_mask,' in after
    assert 'stack += ptoa(2);' in after
    source = after[after.index('static inline vm_offset_t\nroundup_pow2'):after.index(marker)]
    source = source.replace('static vm_offset_t stack_alloc_internal(void);', '').replace('static void stack_free_stack(vm_offset_t);', '')
    shim = r'''
#include <stdint.h>
#include <assert.h>
#include <stdlib.h>
typedef unsigned long vm_offset_t;
#define SECURITY_READ_ONLY_LATE(t) t
static unsigned PAGE_SIZE;
static unsigned long KERNEL_STACK_SIZE;
static vm_offset_t stack_addr_mask, kernel_stack_mask, kernel_stack_size;
static unsigned override_pages;
#define atop(v) ((v) / PAGE_SIZE)
#define ptoa(v) ((unsigned long)(v) * PAGE_SIZE)
#define round_page(v) (((v) + PAGE_SIZE - 1) & ~((unsigned long)PAGE_SIZE - 1))
static int flsll(unsigned long x) { return x ? 64 - __builtin_clzl(x) : 0; }
static int PE_parse_boot_argn(const char *s, uint32_t *v, unsigned long n) {
 (void)s; (void)n; if (!override_pages) return 0; *v = override_pages; return 1;
}
#define panic(...) abort()
'''
    harness = r'''
int main(void) {
 unsigned tests = 0, old_false_low = 0;
 for (unsigned page = 4096; page <= 16384; page *= 4) {
  PAGE_SIZE = page; KERNEL_STACK_SIZE = 16384;
  for (unsigned pages = 0; pages <= 64; pages++) {
   override_pages = pages; stack_init();
   unsigned long allocation = kernel_stack_size + 3ul * page;
   unsigned long alignment = stack_addr_mask + 1;
   assert(alignment >= allocation && !(alignment & (alignment - 1)));
   assert(alignment / 2 < allocation);
   assert((1ul << unixnu_kernel_stack_shift) == alignment);
   assert(kernel_stack_mask == ~stack_addr_mask);
   // Any aligned allocation, at every ABI-aligned valid SP including top.
   unsigned long base = alignment * 3;
   for (unsigned long sp = base + 2ul * page; sp <= base + 2ul * page + kernel_stack_size; sp += 16) {
    unsigned long room = sp & ((1ul << unixnu_kernel_stack_shift) - 1);
    assert(room >= 2ul * page && room < alignment);
    assert(room >= 0x80); tests++;
    if (page == 4096 && (sp & (page - 1)) < 0x80) old_false_low++;
   }
  }
 }
 assert(tests > 10000 && old_false_low > 100);
 PAGE_SIZE = 4096; KERNEL_STACK_SIZE = 16384; override_pages = 0;
 stack_init(); assert(unixnu_kernel_stack_shift == 15);
 return 0;
}
'''
    command = [a.cc, '-std=c11', '-Werror=implicit-function-declaration', '-fsanitize=undefined',
               str(w/'test.c'), '-o', str(w/'test')]
    (w/'test.c').write_text(shim + source + harness)
    subprocess.run(command, check=True); subprocess.run([str(w/'test')], check=True, timeout=20)
    # Negative control: old stack-only alignment must fail the same assertions.
    (w/'test.c').write_text(shim + source.replace('roundup_pow2(kernel_stack_size + ptoa(3))',
                                               'roundup_pow2(kernel_stack_size)') + harness)
    subprocess.run(command, check=True)
    assert subprocess.run([str(w/'test')], capture_output=True, timeout=20).returncode != 0

spec = importlib.util.spec_from_file_location('amfi_stack', a.device/'audit_amfi_stack.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
record = json.loads((a.device/'fixtures/fileset-24A446-iphone12-1-symbols.json').read_text())
class MockImage:
    data = b''
    entries = {m.AMFI: (0, 0)}
    def __init__(self, *args): pass
    def section(self, address): return dict(name='__got')
    def symbols(self): return {0x1000: [m.SHIFT], 0x2000: [m.PAGE]}
    def fixups(self): return {m.SITE: (m.PAGE_ORIGINAL,)}
    def read(self, address, size):
        chunks = {m.CHECKS[0][0]: bytes.fromhex('e87bff90082146f9080140b9090080122821c81ae803282ae90300910801098a1f0102f1430c0054'),
                  m.CHECKS[1][0]: bytes.fromhex('4000805207000014')}
        return chunks[address][:size]
collection = MockImage(); compiled = MockImage()
assert m.check_fixture(record, collection, compiled, MockImage)['site'] == hex(m.SITE)
rejections = 0
for mode in ('missing', 'extra', 'wrong-site', 'wrong-target', 'global-page', 'wrong-donor', 'wrong-bytes', 'wrong-original', 'missing-symbol'):
    rec = copy.deepcopy(record); old = MockImage(); native = MockImage(); Image = MockImage
    if mode == 'missing': rec['sites'] = []
    if mode == 'extra': rec['sites'].append(copy.deepcopy(rec['sites'][0]))
    if mode == 'wrong-site': rec['sites'][0]['site'] = hex(m.SITE + 8)
    if mode == 'wrong-target': rec['sites'][0]['native_symbol'] = m.PAGE
    if mode == 'global-page':
        next(r for r in rec['data'] if r['native_symbol'] == m.PAGE)['native_symbol'] = m.SHIFT
    if mode == 'wrong-donor': rec['inputs']['kernelcache_sha256'] = '0' * 64
    if mode == 'wrong-original': old.fixups = lambda: {m.SITE: (123,)}
    if mode == 'missing-symbol': native.symbols = lambda: {0x2000: [m.PAGE]}
    if mode == 'wrong-bytes':
        class BadImage(MockImage):
            def read(self, address, size): return bytes(size)
        Image = BadImage
    try: m.check_fixture(rec, old, native, Image)
    except ValueError: rejections += 1
    else: raise AssertionError('Accepted ' + mode)
assert rejections == 9

# Final boot reader: synthetic Mach-O segment placement with real reviewed
# instruction bytes. Reject the old page binding and the wrong cache level.
def final_case():
    payload = bytearray(2048)
    struct.pack_into('<II', payload, 16, 4, 4 * 72)
    segments = [(0xfffffff007004000, 0, 320), (m.SITE, 512, 8),
                (m.CHECKS[0][0], 768, 40), (m.CHECKS[1][0], 1024, 8)]
    for i, (va, off, extent) in enumerate(segments):
        pos = 32 + 72 * i
        struct.pack_into('<II', payload, pos, 0x19, 72)
        struct.pack_into('<4Q', payload, pos + 24, va, extent, off, extent)
    defs = {m.SHIFT: segments[0][0] + 0x1000, m.PAGE: segments[0][0] + 0x2000}
    struct.pack_into('<Q', payload, 512, 0x1000)
    for off, (va, size, _) in zip((768, 1024), m.CHECKS):
        payload[off:off+size] = MockImage().read(va, size)
    return payload, defs
data, definitions = final_case()
assert m.require_final(data, definitions)['target'] == hex(definitions[m.SHIFT])
for mode in ('old-page', 'missing', 'alias', 'wrong-cache', 'changed-check', 'truncated'):
    data, definitions = final_case()
    if mode == 'old-page': struct.pack_into('<Q', data, 512, 0x2000)
    if mode == 'missing': definitions.pop(m.SHIFT)
    if mode == 'alias': definitions[m.SHIFT] = definitions[m.PAGE]
    if mode == 'wrong-cache': struct.pack_into('<Q', data, 512, 0x40001000)
    if mode == 'changed-check': data[768] ^= 1
    if mode == 'truncated': del data[1027:]
    try: m.require_final(data, definitions)
    except ValueError: rejections += 1
    else: raise AssertionError('Final boot accepted ' + mode)
assert rejections == 15
print('PASS actual stack_init across 130 geometries; guards preserved; old alignment rejected; 15 donor/import/final-boot negative controls')
