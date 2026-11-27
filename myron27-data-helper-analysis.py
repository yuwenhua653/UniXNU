#!/usr/bin/env python3
"""Bounded static inspection of the exact donor's launchd job sources.

Called while the original OS volume is hash-verified and mounted read-only.
No phone Data, original executable bytes or complete cache is published.
Static references do not establish which branch ran on the phone.
"""
import hashlib
import plistlib
import re
import struct

LIMIT = 32 * 1024 * 1024
TOKENS = ('LaunchDaemons', 'launchd.plist', 'xpcd_cache', 'com.apple.xpc.launchd',
          'bootstrap', 'cache')
JOBS = ('backboardd', 'containermanagerd', 'installd', 'iconservices', 'PosterBoard',
        'SpringBoard', 'data-grow')


def require(ok, why):
    if not ok:
        raise ValueError(why)


def cache_payload(raw):
    """Accept a plist, or the exact bounded __xpcd_cache Mach-O section."""
    require(len(raw) <= LIMIT, 'Cache exceeds analysis bound')
    if raw.startswith((b'bplist00', b'<?xml', b'<plist')):
        return raw
    if len(raw) < 32 or struct.unpack_from('<I', raw)[0] != 0xfeedfacf:
        return None
    _, cpu, _, kind, count, size, _, _ = struct.unpack_from('<8I', raw)
    require(cpu == 0x100000c and kind == 6 and 0 < count <= 4096 and
            size <= len(raw)-32, 'Invalid cache Mach-O header')
    pos = 32
    found = None
    for _ in range(count):
        require(pos+8 <= 32+size, 'Truncated cache command')
        cmd, length = struct.unpack_from('<II', raw, pos)
        require(length >= 8 and length % 8 == 0 and pos+length <= 32+size,
                'Invalid cache command')
        if cmd == 0x19:
            require(length >= 72, 'Short cache segment')
            _, va, vs, off, fs, _, _, n, _ = struct.unpack_from('<16s4Q4I', raw, pos+8)
            require(length == 72+80*n and fs <= vs and off+fs <= len(raw),
                    'Invalid cache segment')
            for i in range(n):
                name, _, addr, sz, fo, _, _, _, flags, _, _, _ = struct.unpack_from(
                    '<16s16sQQ8I', raw, pos+72+80*i)
                if name.rstrip(b'\0') != b'__xpcd_cache':
                    continue
                require(found is None and flags & 255 not in (1, 12, 18) and
                        va <= addr and addr+sz <= va+vs and
                        off <= fo and fo+sz <= off+fs and addr-va == fo-off,
                        'Invalid or duplicate cache section')
                found = raw[fo:fo+sz]
        pos += length
    require(pos == 32+size, 'Unconsumed cache commands')
    return found


def plist_summary(raw):
    payload = cache_payload(raw)
    if payload is None:
        return {'parsed': False, 'reason': 'no standalone plist/cache section'}
    root = plistlib.loads(payload)
    require(isinstance(root, dict), 'Cache root is not a dictionary')
    require(len(root) <= 8192, 'Cache dictionary exceeds bound')
    # Preserve structural counts and selected system-job definitions only.
    summary = dict(parsed=True, top_key_count=len(root),
                   has_launchdaemons_key='LaunchDaemons' in root, selected_jobs=[])
    pending = [(root, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        require(visited <= 100000 and depth <= 16, 'Cache traversal exceeds bound')
        if isinstance(item, dict):
            label = item.get('Label')
            if isinstance(label, str) and any(j.lower() in label.lower() for j in JOBS):
                selected = {k: item[k] for k in ('Label', 'Program', 'ProgramArguments',
                            'UserName', 'Disabled', 'RunAtLoad', 'LimitLoadToSessionType') if k in item}
                require(len(repr(selected)) < 8192, 'Selected job exceeds bound')
                if selected not in summary['selected_jobs']:
                    summary['selected_jobs'].append(selected)
                require(len(summary['selected_jobs']) <= 128, 'Too many selected jobs')
            pending.extend((v, depth+1) for v in item.values() if isinstance(v, (dict, list)))
        elif isinstance(item, list):
            pending.extend((v, depth+1) for v in item if isinstance(v, (dict, list)))
    summary['container_count'] = visited
    return summary


def inspect(mount, audit, trust, launch):
    binary = mount/'sbin/launchd'
    info = audit.macho(binary, trust, 2)
    raw = binary.read_bytes()
    exe = launch.Executable(raw, info)
    strings = sorted(set(s.decode('ascii') for s in re.findall(rb'[ -~]{4,512}', raw)
                         if any(t.encode() in s for t in TOKENS)))
    require(len(strings) <= 2048, 'Too many launchd references')
    # Existing decoder retains direct string references and imported-call names;
    # no guessed addresses, executable slide or binary patch is involved.
    functions = []
    skipped = 0
    for start in exe.starts:
        end = min([v for v in exe.starts if v > start]+[exe.high])
        if end-start > 65536:
            skipped += 1
            continue
        d = exe.describe(start)
        refs = [r for r in d['string_references'] if any(t in r['text'] for t in TOKENS)]
        if refs:
            functions.append(dict(start=d['start'], end=d['end'], sha256=d['sha256'],
                string_references=refs, imported_calls=[c for c in d['direct_and_indirect_calls']
                                                      if c['import_name']]))
    require(len(functions) <= 1024, 'Too many referenced functions')
    paths = ('System/Library/xpc/launchd.plist',
             'System/Library/Caches/com.apple.xpcd/xpcd_cache.dylib',
             'System/Library/LaunchDaemons', 'Library/LaunchDaemons')
    sources = []
    for relative in paths:
        path = mount/relative
        record = dict(path='/'+relative, exists=path.exists(), symlink=path.is_symlink())
        if path.is_dir() and not path.is_symlink():
            record['plist_count'] = sum(1 for _ in path.glob('*.plist'))
            record['selected_jobs'] = []
            for p in sorted(path.glob('*.plist')):
                if p.is_symlink() or not p.is_file() or not any(j.lower() in p.name.lower() for j in JOBS):
                    continue
                require(p.stat().st_size <= LIMIT, 'Daemon plist exceeds bound')
                record['selected_jobs'].append(dict(name=p.name, **plist_summary(p.read_bytes())))
        elif path.is_file() and not path.is_symlink():
            require(path.stat().st_size <= LIMIT, 'Job cache exceeds bound')
            data = path.read_bytes()
            record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            if data[:4] in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
                at, size = audit.arm_slice(data)
                data = data[at:at+size]
            record.update(plist_summary(data))
        sources.append(record)
    return dict(format=1, launchd_sha256=info['sha256'], code_slots_verified=True,
        paths=sources, matching_strings=strings, referenced_functions=functions,
        oversized_functions_skipped=skipped, phone_accessed=False,
        original_files_modified=False, helper_execution_proven=False,
        limitation='Static donor inspection only; cached jobs and string references do not prove live execution.')
