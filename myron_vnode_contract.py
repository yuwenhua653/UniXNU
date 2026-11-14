#!/usr/bin/env python3
"""Check retained vnode dispatch and typed gate interfaces in the emitted kernel.

The donor has 64-byte descriptors; a compiled kernel can use a different
stride. Adjacent-address inference is not an identity proof. STRATEGY and
BWRITE wrappers also have indistinguishable masked instruction shapes.
This verifies chained imports, not runtime behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

DONOR_SHA256 = '813be26ab6bd1d8de211904eca413a1a2ebf79989f90c33a48ff0f2fcff99036'
APFS = 'com.apple.filesystems.apfs'
STRATEGY_ORIGINAL = 0xfffffff00a3b6830
STRATEGY_DESCRIPTOR = 0xfffffff00ac95568
STRATEGY_SITE = 0xfffffff0080e7b20


# Exact donor bodies and typed public interfaces reviewed against locks.c.
GATE_IMPORTS = [{'entry': 'com.apple.filesystems.apfs',
  'site': '0xfffffff0080e8318',
  'original': '0xfffffff00a1cd4f0',
  'original_size': 296,
  'original_sha256': '812195dd3a0f7d884e483c3a72daeadeadfbfa5e6bb3296b4aad01169412ca84',
  'symbol': '_lck_rw_gate_close'},
 {'entry': 'com.apple.filesystems.apfs',
  'site': '0xfffffff0080e8320',
  'original': '0xfffffff00a1cd110',
  'original_size': 324,
  'original_sha256': '5c817bd4cb3228a1f468b10da457a8b33b2ab34e4bef8059643acb91932fd196',
  'symbol': '_lck_rw_gate_destroy'},
 {'entry': 'com.apple.filesystems.apfs',
  'site': '0xfffffff0080e8328',
  'original': '0xfffffff00a1cd0c0',
  'original_size': 24,
  'original_sha256': '8b246cb2939429c963ed2a6e19e57f9032a83353bdbdb55131932d239b9b03c7',
  'symbol': '_lck_rw_gate_init'},
 {'entry': 'com.apple.filesystems.apfs',
  'site': '0xfffffff0080e8330',
  'original': '0xfffffff00a1cd618',
  'original_size': 8,
  'original_sha256': '29ea239478300e76bd87dfbd246bd8f168505208363b36b384152d7c9bd4729b',
  'symbol': '_lck_rw_gate_open'},
 {'entry': 'com.apple.filesystems.apfs',
  'site': '0xfffffff0080e8338',
  'original': '0xfffffff00a1cdc28',
  'original_size': 812,
  'original_sha256': 'd8f1d54c10a2e0ae36a8edd5b1583086c3cb59ba83eaf0d860df65844a0c30ef',
  'symbol': '_lck_rw_gate_wait'},
 {'entry': 'com.apple.security.AppleImage4',
  'site': '0xfffffff007e1d5c8',
  'original': '0xfffffff00a1ce528',
  'original_size': 56,
  'original_sha256': '77ad6667ae3bab8c2c381a1f44f7f217b902dd75305b1638e6aa4c4b0b227333',
  'symbol': '_lck_mtx_gate_alloc_init'},
 {'entry': 'com.apple.security.AppleImage4',
  'site': '0xfffffff007e1d5d0',
  'original': '0xfffffff00a1ce940',
  'original_size': 296,
  'original_sha256': 'eac1e77518e0bd59b8176e0166d275ca03a35c32eeba68b3d2cf36eb6d8a55c7',
  'symbol': '_lck_mtx_gate_close'},
 {'entry': 'com.apple.security.AppleImage4',
  'site': '0xfffffff007e1d5d8',
  'original': '0xfffffff00a1cea68',
  'original_size': 8,
  'original_sha256': '821972e3bc01425ea3c55d26429c974b319be43aebe97653c2b3f7a3d13ad594',
  'symbol': '_lck_mtx_gate_open'},
 {'entry': 'com.apple.security.AppleImage4',
  'site': '0xfffffff007e1d5e0',
  'original': '0xfffffff00a1cea7c',
  'original_size': 8,
  'original_sha256': '193731a983c9b9a8461c808567d3dfba660edbac3582394f5de8f890ba946920',
  'symbol': '_lck_mtx_gate_steal'},
 {'entry': 'com.apple.security.AppleImage4',
  'site': '0xfffffff007e1d5e8',
  'original': '0xfffffff00a1ce80c',
  'original_size': 308,
  'original_sha256': 'bce7bf563b36f6f177b9ce82f7965220deca246d6048a29af68fa50d32d532b0',
  'symbol': '_lck_mtx_gate_try_close'},
 {'entry': 'com.apple.security.AppleImage4',
  'site': '0xfffffff007e1d5f0',
  'original': '0xfffffff00a1cea84',
  'original_size': 712,
  'original_sha256': 'd2c798488088dac1483bf9b99a2668b77380b813f69cc1975eca1f62f4c24bcc',
  'symbol': '_lck_mtx_gate_wait'}]


def descriptor_name(kernel, fixups, address):
    field = fixups.get(address + 8)
    if field is None:
        return None
    try:
        name = kernel.cstring(field[0])
    except ValueError:
        return None
    return name if name and name.startswith('vnop_') else None


def audit(donor, candidate, tool):
    sys.path.insert(0, str(Path(tool).resolve()))
    from kc_image import Image, scan
    raw = Path(donor).read_bytes()
    if hashlib.sha256(raw).hexdigest() != DONOR_SHA256:
        raise ValueError('Vnode identities require the pinned iPhone12,1 24A446 donor')
    built = Path(candidate).read_bytes()
    old, new = Image(raw), Image(built)
    source = Image(raw, old.entries['com.apple.kernel'][1])
    native = Image(built, new.entries['com.apple.kernel'][1])
    old_apfs = Image(raw, old.entries[APFS][1])
    new_apfs = Image(built, new.entries[APFS][1])
    # The current emitter retains Apple kext virtual addresses unchanged.
    if old_apfs.mapped() != new_apfs.mapped():
        raise ValueError('Retained APFS layout changed; cannot compare same-address import sites')
    names = {}
    for address, symbols in native.symbols().items():
        for name in symbols:
            names.setdefault(name, set()).add(address)
    before, after = old.fixups(), new.fixups()
    rows = []
    for site, pointer in before.items():
        if not any(lo <= site < hi for lo, hi in old_apfs.mapped()):
            continue
        name = descriptor_name(source, before, pointer[0])
        if name is None:
            continue
        symbol = '_' + name + '_desc'
        found = names.get(symbol, set())
        expected = next(iter(found)) if len(found) == 1 else None
        actual = after.get(site, (None,))[0]
        target_name = descriptor_name(native, after, expected) if expected is not None else None
        rows.append(dict(site=hex(site), original=hex(pointer[0]), symbol=symbol,
                         expected=hex(expected) if expected is not None else None,
                         actual=hex(actual) if actual is not None else None,
                         passed=expected is not None and actual == expected and target_name == name))
    if len(rows) != 189 or len({r['symbol'] for r in rows}) != 56:
        raise ValueError('Incomplete descriptor inventory for pinned APFS: expected 189 sites / 56 names')
    # Prove the stripped donor wrapper's identity from its own descriptor,
    # independently of the prelink matcher's function-shape/name guesses.
    starts = source.function_starts()
    index = starts.index(STRATEGY_ORIGINAL)
    size = starts[index + 1] - STRATEGY_ORIGINAL
    refs = scan(source.read(STRATEGY_ORIGINAL, size), STRATEGY_ORIGINAL)[1]
    if size != 72 or not any(ref == STRATEGY_DESCRIPTOR for _, ref, _ in refs) or \
            descriptor_name(source, before, STRATEGY_DESCRIPTOR) != 'vnop_strategy':
        raise ValueError('Donor VNOP_STRATEGY semantic identity changed')
    sites = [site for site, ptr in before.items() if ptr[0] == STRATEGY_ORIGINAL
             and any(lo <= site < hi for lo, hi in old_apfs.mapped())]
    if sites != [STRATEGY_SITE]:
        raise ValueError('Donor APFS strategy import inventory changed')
    targets = names.get('_VNOP_STRATEGY', set())
    expected = next(iter(targets)) if len(targets) == 1 else None
    actual = after.get(STRATEGY_SITE, (None,))[0]
    function_rows = [dict(site=hex(STRATEGY_SITE), original=hex(STRATEGY_ORIGINAL),
                         symbol='_VNOP_STRATEGY',
                         expected=hex(expected) if expected is not None else None,
                         actual=hex(actual) if actual is not None else None,
                         passed=expected is not None and actual == expected)]
    gate_rows = []
    starts = source.function_starts()
    for spec in GATE_IMPORTS:
        entry = spec['entry']
        donor_entry = Image(raw, old.entries[entry][1])
        native_entry = Image(built, new.entries[entry][1])
        if donor_entry.mapped() != native_entry.mapped():
            raise ValueError('Gate consumer layout changed: ' + entry)
        site, original = int(spec['site'], 16), int(spec['original'], 16)
        index = starts.index(original)
        if starts[index + 1] - original != spec['original_size'] or \
                hashlib.sha256(source.read(original, spec['original_size'])).hexdigest() != spec['original_sha256']:
            raise ValueError('Reviewed gate function changed: ' + spec['symbol'])
        if before.get(site, (None,))[0] != original or not any(lo <= site < hi for lo, hi in donor_entry.mapped()):
            raise ValueError('Reviewed gate import changed: ' + spec['site'])
        found = names.get(spec['symbol'], set())
        expected = next(iter(found)) if len(found) == 1 else None
        actual = after.get(site, (None,))[0]
        gate_rows.append(dict(site=spec['site'], original=spec['original'], symbol=spec['symbol'],
                              entry=entry, expected=hex(expected) if expected is not None else None,
                              actual=hex(actual) if actual is not None else None,
                              passed=expected is not None and actual == expected))
    return dict(donor_sha256=DONOR_SHA256, candidate_sha256=hashlib.sha256(built).hexdigest(),
                sites_checked=len(rows), descriptors_checked=len({r['symbol'] for r in rows}),
                function_sites_checked=len(function_rows),
                mismatches=[r for r in rows + function_rows + gate_rows if not r['passed']], rows=rows,
                gate_sites_checked=len(gate_rows), gate_rows=gate_rows,
                function_rows=function_rows,
                runtime_qualified=False)


def require(donor, candidate, tool):
    result = audit(donor, candidate, tool)
    if result['mismatches']:
        raise ValueError('Retained vnode/gate binding mismatch: ' + json.dumps(result['mismatches']))
    return {k: v for k, v in result.items() if k != 'rows'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--donor', required=True, type=Path)
    p.add_argument('--candidate', required=True, type=Path)
    p.add_argument('--xnuprelink', required=True, type=Path)
    p.add_argument('--report', type=Path)
    a = p.parse_args()
    result = audit(a.donor, a.candidate, a.xnuprelink)
    if a.report:
        a.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))
    raise SystemExit(bool(result['mismatches']))
