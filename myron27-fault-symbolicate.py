#!/usr/bin/env python3
"""Read original arm64e shared-cache bytes around a photographed user abort.

This is static attribution, not an execution, PAC authentication, or proof that
the first recorded exception caused the eventual process exit. No cache bytes
are modified. Only bounded instruction and pointer windows enter the report.
"""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct


class Error(ValueError):
    pass


def require(ok, why):
    if not ok:
        raise Error(why)


def unpack(fmt, data, offset=0):
    size = struct.calcsize(fmt)
    require(0 <= offset <= len(data) and size <= len(data)-offset, 'truncated structure')
    return struct.unpack_from(fmt, data, offset)


def cstring(data, offset, limit=4096):
    require(0 <= offset < len(data), 'string outside file')
    end = data.find(b'\0', offset, min(len(data), offset+limit))
    require(end >= offset, 'unterminated or oversized string')
    return data[offset:end].decode('utf-8', errors='replace')


def uleb(data, offset):
    value = shift = 0
    for _ in range(10):
        require(offset < len(data), 'truncated ULEB')
        byte = data[offset]; offset += 1
        value |= (byte & 127) << shift
        require(value < 1 << 64, 'ULEB overflow')
        if not byte & 128:
            return value, offset
        shift += 7
    raise Error('oversized ULEB')


class CacheSet:
    # Layout from Apple's dyld_cache_format.h blob
    # e2248242441655e811d8e12668f532e5f88acb92. Entry and pointer layouts are
    # cross-checked against the pinned XNU vm_shared_region.c v5 implementation.
    def __init__(self, directory):
        self.directory = Path(directory)
        self.files = []; self.maps = []; self.images = []; self._macho = {}
        try:
            main = self._open('dyld_shared_cache_arm64e')
            self.main = main
            b = main['data']
            self.region_start, self.region_size, self.max_slide = unpack('<3Q', b, 224)
            require(self.region_start and self.region_size, 'missing shared region')
            off, count = unpack('<2I', b, 392)
            require(count <= 256 and off <= len(b) and count <= (len(b)-off)//56, 'invalid subcache table')
            seen = {b[88:104]}; suffixes = set()
            for n in range(count):
                ident, vmoff, suffix = unpack('<16sQ32s', b, off+n*56)
                require(b'\0' in suffix, 'unterminated subcache suffix')
                suffix = suffix.split(b'\0', 1)[0].decode('ascii')
                require(re.fullmatch(r'\.[A-Za-z0-9_.]+', suffix) and '..' not in suffix and suffix not in suffixes,
                        'unsafe or duplicate subcache suffix')
                suffixes.add(suffix)
                child = self._open(main['name']+suffix)
                require(child['data'][88:104] == ident and ident not in seen, 'subcache UUID mismatch or duplicate')
                seen.add(ident)
            self.maps.sort(key=lambda m: m['address'])
            for a, z in zip(self.maps, self.maps[1:]):
                require(a['address']+a['size'] <= z['address'], 'overlapping cache mappings')
            off, count = unpack('<2Q', b, 136)
            require(0 < count <= 50000 and off <= len(b) and count <= (len(b)-off)//32, 'invalid image text table')
            for n in range(count):
                ident, va, size, path = unpack('<16sQII', b, off+n*32)
                require(size > 0 and self.region_start <= va < self.region_start+self.region_size,
                        'invalid image text range')
                require(va+size <= self.region_start+self.region_size, 'image exceeds shared region')
                self.images.append(dict(address=va, size=size, path=cstring(b, path), uuid=ident.hex()))
            self.images.sort(key=lambda x: x['address'])
            for a, z in zip(self.images, self.images[1:]):
                require(a['address']+a['size'] <= z['address'], 'overlapping image text ranges')
        except BaseException:
            self.close(); raise

    def _open(self, name):
        p = self.directory/name
        require(p.is_file() and not p.is_symlink(), 'missing regular cache file: '+name)
        stream = p.open('rb')
        try:
            b = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        except BaseException:
            stream.close(); raise
        row = dict(name=name, path=p, stream=stream, data=b)
        self.files.append(row)
        require(len(b) >= 464 and b[:16].rstrip(b'\0') == b'dyld_v1  arm64e', 'wrong cache architecture or short header')
        require(any(b[88:104]), 'zero cache UUID')
        mo, count = unpack('<2I', b, 16)
        sig, sigsize = unpack('<2Q', b, 40)
        require(464 <= mo <= len(b) and 0 < count <= 64 and count <= (len(b)-mo)//32, 'invalid mapping table')
        require(mo+count*32 <= sig <= len(b) and sigsize <= len(b)-sig, 'invalid signature extent')
        so, sc = unpack('<2I', b, 312)
        require(sc in (0, count) and so <= len(b) and sc <= (len(b)-so)//56, 'invalid slide mapping table')
        for i in range(count):
            va, size, off, maximum, prot = unpack('<3Q2I', b, mo+32*i)
            require(size and va % 4096 == size % 4096 == off % 4096 == 0 and off <= sig and size <= sig-off,
                    'mapping outside signed range or unaligned')
            m = dict(file=row, address=va, size=size, file_offset=off, protection=prot,
                     slide_offset=0, slide_size=0, flags=0)
            if sc:
                sva, sz, fo, sio, sis, flags, mp, ip = unpack('<6Q2I', b, so+56*i)
                require((sva, sz, fo, ip) == (va, size, off, prot), 'slide mapping differs')
                require(sio <= sig and sis <= sig-sio, 'slide info outside signed range')
                m.update(slide_offset=sio, slide_size=sis, flags=flags)
            self.maps.append(m)
        return row

    def close(self):
        for f in self.files:
            f['data'].close(); f['stream'].close()
        self.files = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def mapping(self, va, size=1):
        require(type(size) is int and 0 < size <= 64*1024*1024, 'invalid bounded read size')
        found = [m for m in self.maps if m['address'] <= va and va+size <= m['address']+m['size']]
        require(len(found) == 1, 'address is not wholly inside one cache mapping')
        return found[0]

    def read(self, va, size, executable=False):
        m = self.mapping(va, size)
        require(not executable or m['protection'] & 4, 'address is not executable')
        off = m['file_offset']+va-m['address']
        return bytes(m['file']['data'][off:off+size]), dict(file=m['file']['name'], offset=hex(off),
            mapping_address=hex(m['address']), mapping_size=hex(m['size']), protection=m['protection'])

    def image_for(self, va):
        return next((i for i in self.images if i['address'] <= va < i['address']+i['size']), None)

    def macho(self, image):
        base = image['address']
        if base in self._macho:
            return self._macho[base]
        head = self.read(base, 32)[0]
        magic, cpu, subtype, kind, count, size, flags, reserved = unpack('<8I', head)
        require(magic == 0xfeedfacf and cpu == 0x100000c and subtype & 0xffffff == 2,
                'embedded image is not arm64e Mach-O')
        require(0 < count <= 4096 and count*8 <= size <= 1024*1024, 'invalid Mach-O commands')
        data = self.read(base+32, size)[0]
        pos = 0; segments = []; starts = None; symtab = None; exports = None
        for _ in range(count):
            cmd, length = unpack('<2I', data, pos)
            require(length >= 8 and length % 8 == 0 and pos+length <= len(data), 'bad load command')
            if cmd == 0x19:
                name, va, vs, off, fs, maxp, prot, sections, sf = unpack('<16s4Q4I', data, pos+8)
                require(length == 72+80*sections and fs <= vs, 'bad Mach-O segment')
                segments.append(dict(name=name.rstrip(b'\0').decode(), address=va, size=vs,
                                     file_offset=off, file_bytes=fs, protection=prot))
            elif cmd in (0x26, 0x80000033):
                require(length == 16, 'bad linkedit command')
                spec = unpack('<2I', data, pos+8)
                if cmd == 0x26: starts = spec
                else: exports = spec
            elif cmd == 0x2:
                require(length == 24 and symtab is None, 'bad symbol table command')
                symtab = unpack('<4I', data, pos+8)
            elif cmd in (0x22, 0x80000022):
                require(length == 48, 'bad dyld info command')
                exports = unpack('<2I', data, pos+40)
            pos += length
        require(pos == len(data), 'unconsumed load command bytes')
        result = dict(segments=segments, starts=[], symtab=symtab, exports=exports)
        self._macho[base] = result
        if starts and starts[1]:
            payload = self.linkedit(image, *starts)
            pos = 0; va = base; terminated = False
            while pos < len(payload):
                delta, pos = uleb(payload, pos)
                if not delta:
                    require(not any(payload[pos:]), 'nonzero function-start padding')
                    terminated = True; break
                va += delta
                require(va % 4 == 0 and any(s['protection'] & 4 and s['address'] <= va < s['address']+s['size'] for s in segments),
                        'function start outside executable image')
                result['starts'].append(va)
            require(terminated, 'unterminated function starts')
        return result

    def linkedit_range(self, image, offset, size):
        """Validate a potentially large shared LINKEDIT range without copying it."""
        require(type(offset) is int and type(size) is int and offset >= 0 and size >= 0,
                'invalid linkedit range')
        segs = self._macho[image['address']]['segments']
        found = [s for s in segs if s['name'] == '__LINKEDIT' and s['file_offset'] <= offset and
                 offset+size <= s['file_offset']+s['file_bytes']]
        require(len(found) == 1, 'linkedit range outside image')
        s = found[0]; va = s['address']+offset-s['file_offset']
        maps = [m for m in self.maps if m['address'] <= va and va+size <= m['address']+m['size']]
        require(len(maps) == 1, 'linkedit range outside one cache mapping')
        m = maps[0]; file_offset = m['file_offset']+va-m['address']
        data = m['file']['data']
        require(file_offset <= len(data) and size <= len(data)-file_offset, 'linkedit range outside file')
        return data, file_offset

    def linkedit(self, image, offset, size):
        require(0 < size <= 64*1024*1024, 'linkedit copied range is too large')
        data, file_offset = self.linkedit_range(image, offset, size)
        return bytes(data[file_offset:file_offset+size])

    def _symtab_symbols(self, image):
        meta = self._macho[image['address']]
        if not meta['symtab']:
            return []
        no, nc, so, ss = meta['symtab']
        meta['symbol_table_layout'] = dict(nlist_offset=no, nlist_count=nc,
                                          strings_offset=so, strings_bytes=ss)
        if not nc:
            return []
        # Modern caches share one large LINKEDIT string pool among images. Its
        # total size is not the amount we need to read, nor a per-image limit.
        rows, rows_at = self.linkedit_range(image, no, nc*16)
        strings, strings_at = self.linkedit_range(image, so, ss)
        result = []
        for n in range(nc):
            string, kind, section, desc, value = unpack('<IBBHQ', rows, rows_at+n*16)
            if not kind & 0xe0 and kind & 0xe == 0xe and section and image['address'] <= value < image['address']+image['size']:
                require(string < ss, 'symbol string index outside validated pool')
                name = cstring(strings, strings_at+string, min(4096, ss-string))
                result.append((value, name, 'LC_SYMTAB'))
        return result

    def _export_symbols(self, image):
        meta = self._macho[image['address']]; result = []
        if not meta['exports'] or not meta['exports'][1]:
            return result
        trie = self.linkedit(image, *meta['exports'])
        stack = [(0, '', frozenset())]; visited = 0
        while stack:
            pos, prefix, ancestors = stack.pop()
            require(pos not in ancestors and len(prefix) <= 4096 and visited < 200000, 'cyclic or oversized exports trie')
            visited += 1; ancestors = ancestors | {pos}
            terminal, cursor = uleb(trie, pos)
            end = cursor+terminal
            require(end < len(trie), 'exports terminal outside trie')
            if terminal:
                flags, at = uleb(trie, cursor)
                if not flags & 8 and flags & 3 == 0:
                    offset, at = uleb(trie, at)
                    require(at <= end, 'export payload outside terminal')
                    address = image['address']+offset
                    if image['address'] <= address < image['address']+image['size']:
                        result.append((address, prefix, 'exports_trie'))
            children = trie[end]; cursor = end+1
            for _ in range(children):
                edge = cstring(trie, cursor)
                cursor += len(edge.encode('utf-8'))+1
                child, cursor = uleb(trie, cursor)
                require(child < len(trie), 'export child outside trie')
                stack.append((child, prefix+edge, ancestors))
        return result

    def _local_symbols(self, image):
        result = []
        symbol_path = self.directory/'dyld_shared_cache_arm64e.symbols'
        if not symbol_path.is_file() or symbol_path.is_symlink():
            return result
        with symbol_path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as b:
            require(len(b) >= 104 and b[88:104] == self.main['data'][400:416], 'local symbols UUID mismatch')
            lo, ls = unpack('<2Q', b, 72)
            require(24 <= ls <= len(b) and lo <= len(b)-ls, 'invalid local symbols chunk')
            no, nc, so, ss, eo, ec = unpack('<6I', b, lo)
            require(no <= ls and nc <= (ls-no)//16 and so <= ls and ss <= ls-so and eo <= ls and ec <= (ls-eo)//16,
                    'local symbols tables outside chunk')
            target = image['address']-self.region_start
            matching = [unpack('<2I', b, lo+eo+n*16+8) for n in range(ec)
                        if unpack('<Q', b, lo+eo+n*16)[0] == target]
            require(len(matching) <= 1, 'duplicate local symbols image')
            for start, count in matching:
                require(start <= nc and count <= nc-start, 'local symbols image exceeds table')
                for n in range(start, start+count):
                    string, kind, section, desc, value = unpack('<IBBHQ', b, lo+no+n*16)
                    if not kind & 0xe0 and kind & 0xe == 0xe and section and image['address'] <= value < image['address']+image['size']:
                        require(string < ss, 'local symbol string exceeds pool')
                        result.append((value, cstring(b, lo+so+string, min(4096, ss-string)), 'local_symbols'))
        return result

    def symbols(self, image, strict=True):
        meta = self.macho(image)
        if 'symbols' not in meta:
            result = []; warnings = []
            for source, loader in [('LC_SYMTAB', self._symtab_symbols), ('exports_trie', self._export_symbols),
                                   ('local_symbols', self._local_symbols)]:
                try:
                    result.extend(loader(image))
                except (Error, OSError, ValueError, struct.error) as error:
                    warnings.append(dict(source=source, error=str(error)))
            meta['symbols'] = sorted(set(result)); meta['symbol_warnings'] = warnings
        if strict and meta['symbol_warnings']:
            raise Error('; '.join(x['source']+': '+x['error'] for x in meta['symbol_warnings']))
        return meta['symbols']

    def symbol_for(self, va, image, strict=True):
        if image is None:
            return None
        meta = self.macho(image)
        starts = [s for s in meta['starts'] if s <= va]
        start = starts[-1] if starts else None
        symbols = [s for s in self.symbols(image, strict=strict) if s[0] <= va]
        best = max(symbols, default=None, key=lambda s: s[0])
        if not best:
            return dict(function_start=hex(start) if start is not None else None, name=None,
                        warnings=meta['symbol_warnings'], symbol_table_layout=meta.get('symbol_table_layout'))
        address, name, source = best
        return dict(name=name, address=hex(address), offset=hex(va-address), source=source,
                    function_start=hex(start) if start is not None else None,
                    exact_function_start_match=start is not None and start == address,
                    attribution='nearest static symbol; not a runtime backtrace',
                    warnings=meta['symbol_warnings'], symbol_table_layout=meta.get('symbol_table_layout'))

    def describe(self, va, window=64, with_symbols=True):
        require(va % 4 == 0 and 0 <= window <= 512 and window % 4 == 0, 'unaligned instruction window')
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
        m = self.mapping(va, 4)
        require(m['protection'] & 4, 'PC mapping is not executable')
        image = self.image_for(va)
        low = max(m['address'], va-window)
        high = min(m['address']+m['size'], va+window+4)
        data, where = self.read(low, high-low, executable=True)
        cs = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        ins = []
        for offset in range(0, len(data), 4):
            address = low+offset; word = data[offset:offset+4]
            decoded = list(cs.disasm(word, address))
            require(len(decoded) <= 1, 'ambiguous fixed-width instruction')
            item = decoded[0] if decoded else None
            ins.append(dict(address=hex(address), bytes=word.hex(),
                mnemonic=item.mnemonic if item else '.word', operands=item.op_str if item else hex(int.from_bytes(word, 'little')),
                decoded=item is not None, is_observed_pc=address == va))
        require(any(i['is_observed_pc'] and i['decoded'] for i in ins), 'observed PC instruction is not recognized')
        result = dict(unslid_address=hex(va), image=image, symbol=None, source=where, instructions=ins)
        if with_symbols:
            self.enrich_description(result)
        return result

    def enrich_description(self, description):
        try:
            description['symbol'] = self.symbol_for(int(description['unslid_address'], 16),
                                                   description['image'], strict=False)
        except (Error, OSError, ValueError, struct.error) as error:
            description['symbol'] = dict(name=None, warnings=[dict(source='image_metadata', error=str(error))])
        return description

    def masked_candidates(self, runtime_address, slide):
        candidates = {}
        for bits in (36, 38, 39, 42, 48, 56, 64):
            value = runtime_address & ((1 << bits)-1)
            if value < slide:
                continue
            try: m = self.mapping(value-slide)
            except Error: continue
            item = candidates.setdefault(value, dict(runtime_address=hex(value), unslid_address=hex(value-slide),
                masks_bits=[], executable=bool(m['protection'] & 4), file=m['file']['name']))
            item['masks_bits'].append(bits)
        return list(candidates.values())

    def pointer_chain(self, va, slide):
        m = self.mapping(va, 8)
        if m['slide_size'] < 24:
            return dict(chain_member=False, reason='mapping has no supported slide info')
        data = m['file']['data']; at = m['slide_offset']
        version, page_size, count = unpack('<3I', data, at)
        if version != 5:
            return dict(chain_member=False, slide_version=version, reason='only v5 decoded')
        require(page_size in (4096, 16384) and 24+count*2 <= m['slide_size'], 'invalid v5 starts')
        page = (va-m['address'])//page_size
        require(page < count, 'v5 page index beyond starts')
        begin = unpack('<H', data, at+24+page*2)[0]
        if begin == 0xffff:
            return dict(chain_member=False, slide_version=5)
        value_add = unpack('<Q', data, at+16)[0]
        delta = begin; pos = 0; visited = 0; target_offset = va-m['address']-page*page_size
        while True:
            pos += delta
            require(pos % 8 == 0 and pos+8 <= page_size and visited < page_size//8, 'invalid v5 chain offset')
            visited += 1
            value = unpack('<Q', data, m['file_offset']+page*page_size+pos)[0]
            if pos == target_offset:
                auth = bool(value >> 63)
                target = (value & 0x3ffffffff)+value_add+slide
                row = dict(chain_member=True, slide_version=5, raw=hex(value), unsigned_runtime_target=hex(target),
                    authenticated=auth, chain_entries_traversed=visited, native_pointer_authentication_executed=False)
                if auth:
                    row.update(diversity=hex((value >> 34) & 0xffff), address_diversity=bool(value & (1 << 50)),
                               key='DA' if value & (1 << 51) else 'IA')
                else:
                    row.update(high8=hex((value >> 34) & 0xff), rebased_runtime_value=hex(target | (((value >> 34) & 0xff) << 56)))
                return row
            delta = ((value >> 52) & 0x7ff)*8
            if not delta or pos > target_offset:
                return dict(chain_member=False, slide_version=5)

    def pointer_window(self, va, slide):
        m = self.mapping(va, 8)
        low = max(m['address'], (va & ~7)-128); high = min(m['address']+m['size'], (va & ~7)+136)
        raw, source = self.read(low, high-low)
        return dict(center_unslid_address=hex(va), source=source, values=[dict(unslid_slot=hex(low+i),
            runtime_slot=hex(low+i+slide), raw=hex(unpack('<Q', raw, i)[0]),
            slide=self.pointer_chain(low+i, slide)) for i in range(0, len(raw), 8)])

    def page_summary(self, va, slide):
        m = self.mapping(va, 8)
        if m['slide_size'] < 24:
            return dict(available=False, reason='no supported slide info')
        data = m['file']['data']; at = m['slide_offset']
        version, size, count = unpack('<3I', data, at)
        if version != 5:
            return dict(available=False, slide_version=version)
        require(size in (4096, 16384) and 24+count*2 <= m['slide_size'], 'invalid v5 starts')
        index = (va-m['address'])//size
        require(index < count, 'v5 page index beyond table')
        start = unpack('<H', data, at+24+index*2)[0]
        page_va = m['address']+index*size
        raw = self.read(page_va, size)[0]
        parts = [dict(part_offset=hex(n), entries=0, first_chain_offset=None) for n in range(0, size, 4096)]
        if start != 0xffff:
            offset = 0; delta = start; traversed = 0
            while True:
                offset += delta
                require(offset % 8 == 0 and offset+8 <= size and traversed < size//8, 'v5 page chain out of bounds')
                traversed += 1; value = unpack('<Q', raw, offset)[0]
                part = parts[offset//4096]; part['entries'] += 1
                if part['first_chain_offset'] is None:
                    part.update(first_chain_offset=hex(offset), first_offset_within_4k=hex(offset%4096),
                        first_raw=hex(value), first_decoded=self.pointer_chain(page_va+offset, slide))
                delta = ((value >> 52) & 0x7ff)*8
                if not delta:
                    break
        return dict(available=True, slide_version=5, page_size=size, page_index=index,
            page_unslid_address=hex(page_va), page_runtime_address=hex(page_va+slide),
            original_page_sha256=hashlib.sha256(raw).hexdigest(), page_start=hex(start),
            value_add=hex(unpack('<Q', data, at+16)[0]), four_k_parts=parts,
            mapping_flags=hex(m['flags']), slide_info_file_offset=hex(at), slide_info_bytes=m['slide_size'])

    def inventory(self):
        return [dict(file=f['name'], bytes=len(f['data']), uuid=f['data'][88:104].hex(),
                     sha256=hashlib.sha256(f['data']).hexdigest()) for f in self.files]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    for name in ('pc', 'lr', 'slide', 'fault'):
        p.add_argument('--'+name, type=lambda x: int(x, 0), required=True)
    a = p.parse_args()
    require(all(0 <= x < 1 << 64 for x in (a.pc, a.lr, a.slide, a.fault)), 'address outside uint64')
    def checkpoint(result):
        encoded = json.dumps(result, indent=2)+'\n'
        require(len(encoded.encode()) <= 2*1024*1024, 'bounded report exceeded 2 MiB')
        a.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = a.output.with_name(a.output.name+'.partial')
        temporary.write_text(encoded)
        temporary.replace(a.output)

    with CacheSet(a.cache_dir) as cache:
        require(a.slide != 0xffffffff and a.slide % 4096 == 0 and a.slide <= cache.max_slide,
                'unavailable or invalid captured cache slide')
        require(a.pc >= a.slide, 'PC below slide')
        result = dict(format=2, result='partial', target='iPhone12,1/27.0.1/24A446',
            observed=dict(pc=hex(a.pc), lr=hex(a.lr), slide=hex(a.slide), fault_address=hex(a.fault)),
            pc=cache.describe(a.pc-a.slide, 512, with_symbols=False),
            lr_candidates=cache.masked_candidates(a.lr, a.slide),
            fault_candidates=cache.masked_candidates(a.fault, a.slide),
            cache_header_blob='e2248242441655e811d8e12668f532e5f88acb92',
            cache_files=[], raw_files_modified=False, phone_execution_observed=False,
            completed_stages=['pc_image_and_instructions'], warnings=[], optional_analysis_complete=False,
            limitations=['Static bytes plus photographed addresses; the snapshot is the first unresolved user abort.',
                'Masked LR/fault candidates are cache-range matches, not authenticated pointers or captured canonical values.',
                'On-disk pointer slots are chain encodings, not a dump of runtime RAM.',
                'Firmware source identity must be independently verified by the extraction job.'])
        # Persist the fault instruction before optional names or data-chain work.
        # Any later decoder failure must not erase already captured evidence.
        checkpoint(result)
        result['cache_files'] = cache.inventory()
        result['completed_stages'].append('cache_inventory_hashes')
        checkpoint(result)

        def enrich(row, label):
            cache.enrich_description(row)
            for warning in (row.get('symbol') or {}).get('warnings', []):
                result['warnings'].append(dict(stage=label, **warning))
            result['completed_stages'].append(label)
            checkpoint(result)

        enrich(result['pc'], 'pc_optional_symbols')
        for row in result['lr_candidates']:
            if not row['executable']:
                continue
            try:
                va = int(row['unslid_address'], 16)
                row['callsite'] = cache.describe(va-4, 512, with_symbols=False)
                checkpoint(result)
                enrich(row['callsite'], 'lr_optional_symbols')
            except (Error, OSError, ValueError, struct.error) as error:
                row['callsite_error'] = str(error)
                result['warnings'].append(dict(stage='lr_callsite', error=str(error)))
                checkpoint(result)
        for row in result['fault_candidates']:
            for key, loader in [('nearby_original_data', cache.pointer_window), ('original_v5_page', cache.page_summary)]:
                try:
                    row[key] = loader(int(row['unslid_address'], 16), a.slide)
                    result['completed_stages'].append(key)
                except (Error, OSError, ValueError, struct.error) as error:
                    row[key] = dict(available=False, error=str(error))
                    result['warnings'].append(dict(stage=key, error=str(error)))
                checkpoint(result)
        result['result'] = 'passed'
        result['optional_analysis_complete'] = not result['warnings']
        checkpoint(result)
        print(json.dumps(dict(result=result['result'], output=str(a.output), pc=result['pc']['symbol'],
                              image=result['pc']['image'], cache_files=len(result['cache_files']),
                              warnings=result['warnings'])))


if __name__ == '__main__':
    main()
