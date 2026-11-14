#!/usr/bin/env python3
"""Reproduce the five known wrong bindings and exercise the new identity gate.

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
    assert hashlib.sha256(raw).hexdigest() == 'cc18aed64e75919aa68b5f8ddbe6ec93332f3dc2048e1d8872f9445174c578e3'
    result = audit(a.donor, a.known_bad, a.xnuprelink)
    bad = result['mismatches']
    assert len(bad) == 5 and {r['symbol'] for r in bad} == {'_vnop_strategy_desc'}
    try:
        require(a.donor, a.known_bad, a.xnuprelink)
    except ValueError as error:
        assert 'APFS vnode descriptor mismatch' in str(error)
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
    print('PASS: known-bad artifact rejected (5 sites); 56 reviewed identities resolve through actual matcher;')
    print('PASS: temporary corrected checker specimen passes 189 sites; single-site regression rejected.')
    print('No prelink rebuild or phone qualification performed.')


if __name__ == '__main__':
    main()
