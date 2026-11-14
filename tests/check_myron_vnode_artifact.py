#!/usr/bin/env python3
"""Reproduce the known descriptor and I/O-dispatch misbindings and exercise the new identity gate.

Uses the real, pinned donor and previously tested fileset. Corrected bytes below
exist only as a temporary checker specimen, never as a boot package.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from myron_vnode_contract import audit, require, DONOR_SHA256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--donor', type=Path, required=True)
    p.add_argument('--known-bad', type=Path, required=True)
    p.add_argument('--xnuprelink', type=Path, required=True)
    p.add_argument('--device', type=Path, required=True)
    a = p.parse_args()
    raw = a.known_bad.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest in {'cc18aed64e75919aa68b5f8ddbe6ec93332f3dc2048e1d8872f9445174c578e3',
                      '76c9bba9ef6fb3b574770f84d2f5e1923433551ec32e2b04728b95c9f9980ed1',
                      '547c79f1c48f02aa60968c4fa7cf07cab728e507bae20538724700f2e8ba2a2d'}
    result = audit(a.donor, a.known_bad, a.xnuprelink)
    bad = result['mismatches']
    expected = 7 if digest.startswith('cc18') else (2 if digest.startswith('76c9') else 1)
    assert len(bad) == expected
    assert sum(r['symbol'] == '_VNOP_STRATEGY' for r in bad) == (0 if digest.startswith('547c') else 1)
    assert sum(r['symbol'] == '_lck_rw_gate_close' for r in bad) == 1
    assert result['gate_sites_checked'] == 11
    try:
        require(a.donor, a.known_bad, a.xnuprelink)
    except ValueError as error:
        assert 'Retained vnode/gate binding mismatch' in str(error)
    else:
        raise AssertionError('Old broken artifact was accepted')

    from kc_image import Image
    from fileset_match import Matcher
    collection = Image(raw)
    native = Image(raw, collection.entries['com.apple.kernel'][1])
    fixture = json.loads((a.device/'fixtures/fileset-24A446-iphone12-1-symbols.json').read_text())
    assert fixture['inputs']['kernelcache_sha256'] == DONOR_SHA256
    matcher = Matcher.__new__(Matcher)
    matcher.native = SimpleNamespace(symbol_names=native.symbols())
    matcher.reviewed_records = lambda inputs: iter([fixture])
    known = {}
    matcher.reviewed_data(fixture['inputs'], known)
    # All descriptor imports must have exact zero-addend names, even when the
    # reference build's data-object ordering or sizes differ.
    identities = {r['original']: r for r in fixture['data']}
    for row in result['rows']:
        record = identities[row['original']]
        assert record['native_symbol'] == row['symbol'] and record.get('addend', 0) == 0
        assert known[int(row['original'], 16)] == (int(row['expected'], 16), 'reviewed')

    donor_raw = a.donor.read_bytes()
    donor_outer = Image(donor_raw)
    donor_kernel = Image(donor_raw, donor_outer.entries['com.apple.kernel'][1])
    wrappers = [r for r in fixture['functions'] if r['native_symbol'] in ('_VNOP_STRATEGY', '_VNOP_BWRITE') or '_gate_' in r['native_symbol']]
    assert len(wrappers) == 13
    matcher.original = SimpleNamespace(image=donor_kernel, functions={
        int(r['original'], 16): dict(end=int(r['original'], 16)+r['original_size']) for r in wrappers})
    matcher.native.named_functions = {name: addr for addr, names in native.symbols().items() for name in names}
    matcher.pairs, matcher.reverse, matcher.how, matcher.conflicts = {}, {}, {}, []
    matcher.reviewed_records = lambda inputs: iter([dict(functions=wrappers)])
    assert matcher.anchor_reviewed(fixture['inputs']) == 13
    assert matcher.pairs[0xfffffff00a1cd4f0] == matcher.native.named_functions['_lck_rw_gate_close']
    assert matcher.pairs[0xfffffff00a1cd4f0] != matcher.native.named_functions['_gate_close']
    assert matcher.pairs[0xfffffff00a3b6830] == matcher.native.named_functions['_VNOP_STRATEGY']
    assert matcher.pairs[0xfffffff00a3b6878] == matcher.native.named_functions['_VNOP_BWRITE']

    specimen = bytearray(raw)
    for row in bad:
        site = int(row['site'], 16)
        offset = collection.offset(site, 8)
        word, = struct.unpack_from('<Q', specimen, offset)
        old = int(row['actual'], 16) - collection.base
        new = int(row['expected'], 16) - collection.base
        assert word & 0x3fffffff == old and 0 <= new < 0x40000000
        struct.pack_into('<Q', specimen, offset, (word & ~0x3fffffff) | new)
    with tempfile.TemporaryDirectory(prefix='vnode-check-only-') as temp:
        candidate = Path(temp)/'checker-specimen.macho'
        candidate.write_bytes(specimen)
        checked = require(a.donor, candidate, a.xnuprelink)
        assert checked['sites_checked'] == 189 and checked['descriptors_checked'] == 56
        # One remaining bad site must still block the entire output.
        offset = collection.offset(int(bad[-1]['site'], 16), 8)
        specimen[offset:offset+8] = raw[offset:offset+8]
        candidate.write_bytes(specimen)
        assert len(audit(a.donor, candidate, a.xnuprelink)['mismatches']) == 1
    print(f'PASS: known-bad artifact rejected ({expected} sites); 56 descriptors and 13 typed dispatch/gate interfaces resolve through actual matcher;')
    print('PASS: temporary corrected checker specimen passes 189 sites; single-site regression rejected.')
    print('No prelink rebuild or phone qualification performed.')


if __name__ == '__main__':
    main()
