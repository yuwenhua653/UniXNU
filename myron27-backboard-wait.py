"""Attribute the two executable return sites retained by the Myron process sampler."""
import hashlib
import re
import struct
import subprocess
from pathlib import Path


def inspect(path, info, analysis):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != info['sha256']:
        raise ValueError('Backboard executable differs from the audited file')
    data = data[info['slice_offset']:][:info['slice_bytes']]
    exe = analysis.Executable(data, info)
    # Sampler publishes the executable's Mach header from dyld_all_image_infos.
    # Use image-relative addresses only. Shared-cache offsets are independent.
    executable_base = next(seg[0] for seg in segments(data) if seg[3] == '__TEXT')
    offsets = {'group_wait_return': 0x21084, 'previous_home_wait_return': 0x227f8, 'run_loop_return': 0x18aa0}
    functions = {}
    for name, delta in offsets.items():
        site = executable_base + delta - 4
        owner = exe.owner(site)
        call = exe.call(site)
        if owner is None or not call:
            raise ValueError(f'Expected executable call preceding {name}')
        functions[name] = dict(site=hex(site), owner=hex(owner),
                               direct_import=exe.stubs.get(call['target']))
    wait = int(functions['group_wait_return']['owner'], 16)
    targets = {wait}
    # A global block stores an invoke pointer in constant data. Include its
    # literal address when looking for its enclosing method's references.
    for va, size, off, segname in segments(data):
        if segname not in ('__DATA_CONST','__AUTH_CONST','__DATA','__AUTH'):
            continue
        for pos in range(16,(size & ~7),8):
            word, = struct.unpack_from('<Q',data,off+pos)
            if word == wait or (not (word >> 62 & 1) and (word & 0xffffffff) == wait-executable_base):
                targets.add(va + pos - 16)
    parents = set()
    for pc in range(exe.low,exe.high,4):
        w = exe.word(pc)
        dst = None
        imm = analysis.signed((w >> 5 & 0x7ffff) << 2 | (w >> 29 & 3),21)
        if w & 0x9f000000 == 0x10000000:
            dst = pc + imm
        elif w & 0x9f000000 == 0x90000000 and pc+4 < exe.high:
            add = exe.word(pc+4)
            if add & 0xffc00000 == 0x91000000 and (add >> 5 & 31) == (w & 31):
                dst = (pc & ~4095) + (imm << 12) + (add >> 10 & 4095)
        if dst in targets and exe.owner(pc) is not None:
            parents.add(exe.owner(pc))
    if len(parents)>32:
        raise ValueError('Ambiguous block references')
    chosen = sorted(parents | {int(v['owner'],16) for v in functions.values()})
    listing = subprocess.check_output(['/usr/bin/otool','-arch','arm64e','-tvV',str(path)],text=True)
    selected = {addr:[] for addr in chosen}
    for line in listing.splitlines():
        m = re.match(r'^\s*([0-9a-fA-F]{16})\s+(.+)',line)
        if not m:continue
        pc = int(m[1],16)
        own = exe.owner(pc)
        if own in selected and (';' in m[2] or m[2].startswith(('bl\t','b\t','bl ','b '))):
            selected[own].append(dict(offset=hex(pc-own),detail=m[2][:450]))
    objc = subprocess.check_output(['/usr/bin/otool','-arch','arm64e','-ov',str(path)],text=True)
    selectors = {}
    last_name = None
    for line in objc.splitlines():
        field = line.strip().split(None, 2)
        if not field:continue
        if field[0] == 'name':
            last_name = field[2] if len(field) == 3 else None
        if field[0] == 'imp' and len(field) > 1 and last_name:
            try: addr = int(field[1],16)
            except ValueError:continue
            if addr in selected:selectors[hex(addr)] = last_name
    at = subprocess.run(['/usr/bin/atos','-arch','arm64e','-o',str(path),*[hex(f) for f in chosen]],
                        capture_output=True,text=True)
    # These references belong to this exact executable and its one observed parent.
    metadata = {}
    if parents == {executable_base + 0x20f6c} and info['sha256'] == 'fbba7fd2925990dd859b24629ecab5cdbf6f2fac8c1c357ec0f9e412ded75559':
        metadata = wait_metadata(data, executable_base, next(iter(parents)),
                                 [executable_base + off for off in (0x90238, 0x901f8, 0x90218)])
    return dict(wait_metadata=metadata,executable_sha256=info['sha256'],uuid=exe.uuid,sites=functions,
                symbolic_names=at.stdout.splitlines(),objc_method_names=selectors,static_parent_candidates=[hex(p) for p in sorted(parents)],
                functions={hex(f):selected[f][:180] for f in chosen})


def segments(data):
    count, = struct.unpack_from('<I',data,16)
    at = 32
    for _ in range(count):
        cmd, size = struct.unpack_from('<II',data,at)
        if cmd == 0x19:
            name = data[at+8:at+24].rstrip(b'\0').decode()
            va, _, off, length = struct.unpack_from('<4Q',data,at+24)
            if off+length>len(data):raise ValueError('Unbacked segment')
            yield va,length,off,name
        at += size


def wait_metadata(data, base, parent, literal_addresses):
    """Read name/selector references only from bounded, file-backed sections."""
    sections = []
    at = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, at)
        if cmd == 0x19:
            for i in range(struct.unpack_from('<I', data, at + 64)[0]):
                entry = at + 72 + 80 * i
                name = data[entry:entry + 16].split(b'\0')[0].decode()
                va, length, offset = struct.unpack_from('<QQI', data, entry + 32)
                if offset and offset + length <= len(data):
                    sections.append((name, va, length, offset))
        at += size

    def locate(addr, count, names):
        for name, low, size, off in sections:
            if name in names and low <= addr and addr + count <= low + size:
                return off + addr - low
        return None

    def pointer_options(word):
        # Absolute pointer, or a chained rebase encoded as an image offset.
        return (word, base + (word & 0xffffffff), base + (word & ((1 << 43) - 1)))

    def string_at(addr, names, limit=512):
        pos = locate(addr, 1, names)
        if pos is None:
            return None
        end = data.find(b'\0', pos, pos + limit + 1)
        if end < pos or locate(addr, end - pos + 1, names) is None:
            return None
        value = data[pos:end]
        return value.decode('ascii') if value and all(32 <= c <= 126 for c in value) else None

    literals = {}
    for addr in literal_addresses:
        off = locate(addr, 32, {'__cfstring'})
        if off is None:
            continue
        ptr, length = struct.unpack_from('<QQ', data, off + 16)
        for va in pointer_options(ptr):
            value = string_at(va, {'__cstring', '__objc_methname', '__oslogstring'})
            if value and len(value) == length:
                literals[hex(addr)] = value
                break
    selectors = set()
    for name, start, size, off in sections:
        if name not in {'__objc_methlist', '__objc_const', '__const'}:
            continue
        for i in range(8, size - 3, 4):
            rel, = struct.unpack_from('<i', data, off + i)
            if start + i + rel != parent:
                continue
            name_rel, type_rel = struct.unpack_from('<ii', data, off + i - 8)
            typ = string_at(start + i - 4 + type_rel, {'__objc_methtype', '__cstring'})
            if not typ or '@' not in typ:
                continue
            slot = start + i - 8 + name_rel
            candidates = [slot]
            pos = locate(slot, 8, {'__objc_selrefs'})
            if pos is not None:
                candidates.extend(pointer_options(struct.unpack_from('<Q', data, pos)[0]))
            for va in candidates:
                value = string_at(va, {'__objc_methname'})
                if value:
                    selectors.add(value)
    return dict(assertion_literals=literals, parent_selectors=sorted(selectors))
