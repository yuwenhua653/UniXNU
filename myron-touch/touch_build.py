"""Compile the board digitizer against Apple's pinned IOHIDDevice public header."""
import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

FAMILY = 'com.apple.iokit.IOHIDFamily'
PUBLISHER = 'com.apple.iokit.IOHIDEventDriverSafeBoot'
VTABLE = '__ZTV14MyronDigitizer'


def check(value, reason):
    if not value:
        raise ValueError(reason)


def matching(image):
    from fileset_emit import prelink_info
    entries = prelink_info(image)[1]['_PrelinkInfoDictionary']
    entry, = [e for e in entries if e['CFBundleIdentifier'] == PUBLISHER]
    rule = entry['IOKitPersonalities']['HID Pointing/Consumer/System Control Driver']
    check(rule['CFBundleIdentifier'] == FAMILY and rule['IOClass'] == 'IOHIDEventDriver'
          and rule['IOProviderClass'] == 'IOHIDInterface'
          and {'DeviceUsagePage': 13} in rule['DeviceUsagePairs'], 'Missing digitizer matching rule')
    return hashlib.sha256(plistlib.dumps(entry['IOKitPersonalities'])).hexdigest()


def inspect_phone(donor, fixture, tool):
    sys.path.insert(0, str(tool))
    from kc_image import Image, scan
    raw = Path(donor).read_bytes()
    check(hashlib.sha256(raw).hexdigest() == fixture['kernelcache_sha256'], 'Wrong HID donor')
    image = Image(raw)
    family = Image(raw, image.entries[FAMILY][1])
    t = int(fixture['vtable'], 16)
    fix = image.fixups()
    check(len(fixture['slots']) == 207 and image.read(t-16, 16) == bytes(16)
          and t+207*8 not in fix, 'Wrong IOHIDDevice table extent')
    for i, (target, diversity) in enumerate(fixture['slots']):
        check(fix.get(t+8*i) == (int(target,16), 1, 0, int(diversity,16), 1),
              f'IOHIDDevice donor slot {i} differs')
    base = fixture['bindings']
    check(int(base['__ZTV11IOHIDDevice'],16) == t-16, 'Wrong base HID vtable')
    getter = fix[t+7*8][0]
    _, refs, _ = scan(image.read(getter, 16), getter)
    check(any(a == int(base['__ZN11IOHIDDevice10gMetaClassE'],16) and k == 'add'
              for _, a, k in refs), 'Wrong HID base metaclass')
    for name in ('__ZN11IOHIDDeviceC2EPK11OSMetaClass', '__ZN11IOHIDDeviceD2Ev'):
        check(int(base[name],16) in family.function_starts(), 'Invalid HID constructor/destructor')
    return matching(image)


def compile_touch(tree, here, out, builder, target, env, record, donor, native, mapping, tool, objcopy):
    from display_abi import object_slots
    from build_ufs_dormant import macho, initializers
    from display_build import check_object_imports, iphone_target_flags
    from audit_ufs_storage_abi import assembly, addresses_assembly
    source = here/'touch'
    out.mkdir(exist_ok=True)
    fixture = json.loads((source/'iphone12-1-hid-24A446.json').read_text())
    hid = here.parents[1]/'references/IOHIDFamily'
    rev = subprocess.check_output(['git','-C',hid,'rev-parse','HEAD'], text=True).strip()
    check(rev == 'e31e90a24c27ad6cbe981650d12a1a4124065b03', 'Wrong Apple HID header revision')
    includes = out/'headers'
    for original, sub in [('IOHIDFamily', 'hid'), ('IOHIDSystem/IOKit/hidsystem', 'hidsystem')]:
        dest = includes/'IOKit'/sub
        dest.mkdir(parents=True, exist_ok=True)
        for path in (hid/original).glob('*.h'):
            shutil.copyfile(path, dest/path.name)
    sdk = subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'], text=True).strip()
    geni = here.parents[1]/'references/QcomGeniSpi'
    flags = ['-I', str(geni), '-I', str(includes), '-I', str(tree/'.cache/xnu-work/osfmk'), '-idirafter',
             str(Path(sdk)/'System/Library/Frameworks/Kernel.framework/Versions/A/Headers')]
    objects = []
    recipe = tree/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'
    c_record = json.loads(recipe.read_text().strip().rstrip(','))
    for name, recipe in [(geni/'GeniSpi.c', c_record), ('MyronFT3683.c', c_record), ('MyronTouchStart.cpp', record), ('MyronDigitizer.cpp', record)]:
        obj = out/(Path(name).stem+'.o')
        cmd = builder.compile_command(recipe, source/name, obj, flags,
            ['-mgeneral-regs-only','-Wno-missing-field-initializers','-Wno-overloaded-virtual',
             '-Wno-unnecessary-virtual-specifier','-Wno-deprecated-enum-enum-conversion'])
        subprocess.run(cmd, cwd=recipe['directory'], env=env, check=True)
        target.check_object(obj.read_bytes(), str(name))
        check_object_imports(macho(obj.read_bytes(),1))
        objects.append(obj)
    obj = objects.pop()
    info, rows = object_slots(obj.read_bytes(), VTABLE, 207)
    bindings = {name: dict(address=addr,kind='data' if name in
            ('__ZTV11IOHIDDevice','__ZN11IOHIDDevice10gMetaClassE') else 'function')
            for name,addr in fixture['bindings'].items()}
    personality = None
    identities = {}
    if donor:
        personality = inspect_phone(donor, fixture, tool)
        from kc_image import Image
        kernel = Image(Path(native).read_bytes())
        pair = json.loads(Path(mapping).read_text())
        check(pair['inputs']['native_sha256'] == hashlib.sha256(kernel.data).hexdigest()
              and pair['inputs']['kernelcache_sha256'] == fixture['kernelcache_sha256'], 'Stale HID map')
        symbols = kernel.symbols()
        for key in ('functions','data'):
            identities.update({int(a,16):symbols.get(int(r['native'],16), []) for a,r in pair[key].items()})
    for row, (address, diversity) in zip(rows, fixture['slots']):
        name = row['name']
        check((row['auth'],row['key'],row['diversity'],row['address_diversity'])
              == (1,0,int(diversity,16),1), f'HID ABI mismatch at slot {row["slot"]}')
        if '11IOHIDDevice' in name:
            check(address != '0xfffffff00a9fa290', 'Unimplemented abstract HID slot')
            binding = dict(address=address,kind='function')
            check(bindings.setdefault(name,binding) == binding, 'Ambiguous HID slot')
        elif '14MyronDigitizer' not in name and donor:
            check(name in identities.get(int(address,16), []), f'Wrong inherited HID method {name}')
    imports = set(info['undefined'])
    check(all(n in bindings for n in imports if '11IOHIDDevice' in n), 'Unverified HID import')
    late = out/'MyronDigitizer.late.o'
    init = initializers(info)
    check(len([s for s in init if s['name'] in ('__mod_init_func','__init_offsets')]) == 1
          and '__GLOBAL__sub_I_MyronDigitizer.cpp' in info['defined'], 'Missing digitizer class initializer')
    subprocess.run([objcopy,*('--remove-section='+s['segment']+','+s['name'] for s in init),
                    '--globalize-symbol=__GLOBAL__sub_I_MyronDigitizer.cpp',obj,late],check=True,env=env)
    check(not initializers(macho(late.read_bytes(),1)), 'HID initializer must follow family load')
    objects.append(late)
    for part, text in [('bindings', assembly(bindings)), ('addresses', addresses_assembly(bindings))]:
        path = out/(part+'.S')
        path.write_text(text)
        obj = path.with_suffix('.o')
        subprocess.run(['xcrun','--sdk','iphoneos','clang',*iphone_target_flags(env),'-c',path,'-o',obj],check=True,env=env)
        target.check_object(obj.read_bytes(),part)
        objects.append(obj)
    contract = dict(bindings=bindings, methods=rows, vtable_symbol=VTABLE, donor_sha256=fixture['kernelcache_sha256'],
                    data_imports=[n for n,r in bindings.items() if r['kind']=='data' and n in imports],
                    personality_sha256=personality, owners=[FAMILY])
    keep = ('_geni_spi_transfer', '_geni_spi_read_info', '_myron_touch_start', '_myron_publish_digitizer', '_myron_touch_read_contacts', VTABLE,'__GLOBAL__sub_I_MyronDigitizer.cpp') + tuple(
        n+'.original' if r['kind']=='function' else n for n,r in bindings.items())
    return objects, keep, contract
