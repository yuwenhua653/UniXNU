#!/usr/bin/env python3
"""Check retained APFS vnode descriptors and I/O dispatch against the emitted kernel.

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
    return dict(donor_sha256=DONOR_SHA256, candidate_sha256=hashlib.sha256(built).hexdigest(),
                sites_checked=len(rows), descriptors_checked=len({r['symbol'] for r in rows}),
                function_sites_checked=len(function_rows),
                mismatches=[r for r in rows + function_rows if not r['passed']], rows=rows,
                function_rows=function_rows,
                runtime_qualified=False)


def require(donor, candidate, tool):
    result = audit(donor, candidate, tool)
    if result['mismatches']:
        raise ValueError('APFS vnode binding mismatch: ' + json.dumps(result['mismatches']))
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
