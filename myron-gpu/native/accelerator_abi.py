"""Bind the ordinary native subclass to retained iPhone IOGPUFamily.

Use the same BTI adapters, zero-slide prelink and final PAC/GOT checks as the
working display/HID drivers. Never import an iPad accelerator binding table.
"""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
VTABLE = '__ZTV14AGXAccelerator'


def require(value, reason):
    if not value: raise ValueError(reason)


def inspect(image, fixture):
    table = int(fixture['vtable'], 16)
    require(image.read(table, 16) == bytes(16) and
            image.read(table+16+168*8, 8) == bytes(8), 'Accelerator vtable extent')
    for address, code in fixture['checks'].items():
        require(image.read(int(address,16),len(bytes.fromhex(code))).hex() == code,
                'Retained IOGPUFamily code changed: '+address)
    fix = image.fixups()
    for slot, pac in enumerate(fixture['pac']):
        require(tuple(pac) == fix[table+16+8*slot][1:], 'Retained accelerator PAC changed')
    family = type(image)(image.data, image.entries[fixture['family']][1])
    for row in fixture['bindings'].values():
        address = int(row['address'],16)
        if row['kind'] == 'function':
            require(address in family.function_starts(), 'Accelerator entry outside retained family')
    return fix


def audit_object(obj, donor=None, native=None, mapping=None, tool=None):
    from display_abi import object_slots
    from display_build import check_object_imports
    fixture = json.loads((HERE/'accelerator-iphone27.json').read_text())
    info, rows = object_slots(Path(obj).read_bytes(), VTABLE, 168)
    check_object_imports(info)
    bindings = fixture['bindings']
    require({n for n in info['undefined'] if '15IOAcceleratorES' in n} == set(bindings),
            'Unexpected original accelerator imports')
    for row, pac in zip(rows, fixture['pac']):
        require([row[k] for k in ('auth','key','diversity','address_diversity')] == pac,
                'Native accelerator PAC mismatch at slot '+str(row['slot']))
    if donor is not None:
        require(native is not None and mapping is not None and tool is not None,
                'Full accelerator audit needs donor/native/identity map')
        sys.path.insert(0,str(tool))
        from kc_image import Image
        raw = Path(donor).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == fixture['donor_sha256'], 'Wrong accelerator donor')
        image, kernel = Image(raw), Image(Path(native).read_bytes())
        require(image.base == kernel.base, 'Accelerator requires zero slide')
        fix = inspect(image, fixture)
        pair = json.loads(Path(mapping).read_text())
        require(pair['inputs']['native_sha256'] == hashlib.sha256(kernel.data).hexdigest() and
                pair['inputs']['kernelcache_sha256'] == fixture['donor_sha256'], 'Stale accelerator map')
        symbols = kernel.symbols()
        identities = {int(a,16): symbols.get(int(r['native'],16), [])
                      for kind in ('functions','data') for a,r in pair[kind].items()}
        table = int(fixture['vtable'],16)+16
        for row in rows:
            name, slot = row['name'], row['slot']
            if '14AGXAccelerator' in name:
                require(slot in (0,1,7) or '13newUserClient' in name,
                        'Unexpected accelerator override: '+name)
            else:
                require(name in identities.get(fix[table+8*slot][0], []),
                        'Wrong inherited accelerator method: '+name)
    return dict(bindings=bindings,methods=rows,vtable_symbol=VTABLE,
                donor_sha256=fixture['donor_sha256'],donor_checked=donor is not None,
                data_imports=[n for n,r in bindings.items() if r['kind']=='data'],
                owners=[fixture['family']],fixture_sha256=hashlib.sha256(
                    (HERE/'accelerator-iphone27.json').read_bytes()).hexdigest())
