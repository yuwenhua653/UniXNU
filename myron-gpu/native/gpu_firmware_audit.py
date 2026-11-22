"""Audit actual linked A840 firmware placement and bytes, before prelinking."""
import hashlib
import json
from pathlib import Path
import struct


def verify(image, pins):
    symbols = {}
    for address, names in image.symbols().items():
        for name in names:
            if name.startswith('_myron_') and '_firmware' in name:
                if name in symbols:
                    raise ValueError('Duplicate GPU firmware symbol: '+name)
                symbols[name] = address
    section, = [s for s in image.sections if (s['segment'], s['name']) == ('__TEXT', '__myron_gpu')]
    segment, = [s for s in image.segments if s['name'] == '__TEXT']
    # These bytes are not CPU instructions and require no writable mapping.
    protection, = struct.unpack_from('<i', image.data, segment['command_offset'] + 60)
    if not protection & 1 or protection & 2:
        raise ValueError('GPU firmware must be mapped read-only')
    result = {}
    intervals = []
    for kind in ('gmu', 'sqe', 'aqe', 'zap'):
        filename, = [name for name in pins if name.startswith('gen80200_'+kind+'.')]
        pin = pins[filename]
        symbol = '_myron_'+kind+'_firmware'
        start, size_at = symbols[symbol], symbols[symbol+'_size']
        count = pin['bytes']
        if start % 4096 or size_at % 8:
            raise ValueError('GPU firmware alignment differs: '+kind)
        for begin, end in ((start, start+count), (size_at, size_at+8)):
            if not section['va'] <= begin < end <= section['va']+section['size']:
                raise ValueError('GPU firmware escapes read-only payload section: '+kind)
            if any(begin < b and a < end for a,b in intervals):
                raise ValueError('GPU firmware ranges overlap: '+kind)
            intervals.append((begin,end))
        size, = struct.unpack('<Q', image.read(size_at, 8))
        digest = hashlib.sha256(image.read(start, count)).hexdigest()
        if size != count or digest != pin['sha256']:
            raise ValueError('Linked GPU firmware bytes or size differ: '+kind)
        result[filename] = dict(bytes=count, sha256=digest, address=hex(start))
    return dict(section='__TEXT,__myron_gpu', read_only=True, firmware=result,
                hardware_tested=False)


def verify_linked(path, pins_path):
    from kc_image import Image
    return verify(Image(Path(path).read_bytes()), json.loads(Path(pins_path).read_text())['files'])
