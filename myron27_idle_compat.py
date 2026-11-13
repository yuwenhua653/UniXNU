"""Scoped, hash-pinned myron idle compatibility derivative of native run 43379932443.

Apple cpu.c ac9718fb1af618d5ce8678d0dc6e8a58f252216f documents that
masked WFE may ignore pending interrupts. This applies the existing wfe_allowed=0
policy, retaining WFI, interrupt masks, timer programming and all instructions.
It is a compatibility experiment, not a confirmed diagnosis of the APFS stall.
"""
import hashlib
import struct
from myron_continuous_contract import kernel_definitions

INPUT_SHA = 'd2f48e6237be23bc1e8dfb2547d835c589d0f9ceb982709efe98117e14a879d4'
OUTPUT_SHA = '029c470f8fb62163a33a92913ed9566c1044d76e0add30263428aadfdc656726'
SYMBOL = '_wfe_allowed'
ADDRESS = 0xfffffff00ac2a348
OFFSET = 0x3c26348

def sha(data):
    return hashlib.sha256(data).hexdigest()

def need(ok, message):
    if not ok:
        raise ValueError(message)

def mapped_scalar(data):
    """Independently validate native segment/section mapping; offsets are absolute."""
    def commands(at):
        need(0 <= at <= len(data)-32, 'Truncated header')
        count, size = struct.unpack_from('<II', data, at+16)
        pos, end = at+32, at+32+size
        need(end <= len(data) and count <= size//8, 'Truncated commands')
        rows = []
        for _ in range(count):
            need(pos+8 <= end, 'Truncated command')
            cmd, length = struct.unpack_from('<II', data, pos)
            need(length >= 8 and pos+length <= end, 'Invalid command extent')
            rows.append((cmd, pos, length)); pos += length
        need(pos == end, 'Inconsistent commands')
        return rows
    members = []
    for cmd, pos, length in commands(0):
        if cmd != 0x80000035:
            continue
        need(length >= 32, 'Truncated fileset entry')
        _, offset, name = struct.unpack_from('<QQI', data, pos+8)
        need(32 <= name < length, 'Invalid fileset name')
        end = data.find(b'\0', pos+name, pos+length)
        need(end >= 0, 'Unterminated fileset name')
        if data[pos+name:end] == b'com.apple.kernel':
            members.append(offset)
    need(len(members) == 1, 'Ambiguous native kernel')
    matches = []
    for cmd, pos, length in commands(members[0]):
        if cmd != 0x19:
            continue
        need(length >= 72, 'Truncated segment')
        name, va, vmsize, fileoff, size, maxprot, initprot, nsects, _ = struct.unpack_from('<16sQQQQiiII', data, pos+8)
        need(length == 72+80*nsects, 'Invalid section table')
        if not va <= ADDRESS <= va+size-4:
            continue
        need(name.rstrip(b'\0') == b'__DATA' and maxprot == initprot == 3,
             'Scalar is not in non-executable writable data')
        offset = fileoff+ADDRESS-va
        need(offset+4 <= len(data) and offset == OFFSET, 'Scalar mapping changed')
        sections = []
        for index in range(nsects):
            sec = pos+72+80*index
            sname, seg, sva, ssize, soff = struct.unpack_from('<16s16sQQI', data, sec)
            flags = struct.unpack_from('<I', data, sec+64)[0]
            if sva <= ADDRESS <= sva+ssize-4:
                need(sname.rstrip(b'\0') == b'__data' and seg.rstrip(b'\0') == b'__DATA', 'Wrong scalar section')
                need(flags == 0 and soff+ADDRESS-sva == offset, 'Scalar section is not regular file-backed data')
                sections.append(sec)
        need(len(sections) == 1, 'Ambiguous scalar section')
        matches.append(offset)
    need(matches == [OFFSET], 'Ambiguous scalar mapping')
    return OFFSET

def patch_kernel(data):
    need(sha(data) == INPUT_SHA, 'Require exact qualified native kernel; no automatic fallback')
    definitions = kernel_definitions(data)
    need(definitions.get(SYMBOL) == ADDRESS, 'Native wfe_allowed symbol changed')
    offset = mapped_scalar(data)
    need(data[offset:offset+4] == b'\1\0\0\0', 'Unexpected wfe_allowed initializer')
    result = data[:offset]+b'\0\0\0\0'+data[offset+4:]
    need(len(result) == len(data) and result[:offset] == data[:offset]
         and result[offset+1:] == data[offset+1:], 'Unexpected kernel modification')
    need(sha(result) == OUTPUT_SHA, 'Unexpected derived kernel digest')
    return result, dict(kind='myron-masked-wfe-compatibility', symbol=SYMBOL,
        virtual_address=hex(ADDRESS), file_offset=offset, before=1, after=0,
        input_sha256=INPUT_SHA, output_sha256=sha(result), changed_bytes=1,
        kernel_instructions_unchanged=True, native_run='43379932443',
        native_commit='e7cd64972d3a5725f1a13d130806729a21101361',
        confirmed_root_cause=False, phone_tested=False)
