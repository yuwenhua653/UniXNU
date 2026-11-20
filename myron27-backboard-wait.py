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
    return dict(executable_sha256=info['sha256'],uuid=exe.uuid,sites=functions,
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
