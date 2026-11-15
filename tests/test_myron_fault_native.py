#!/usr/bin/env python3
"""Check the emitted-call gate against branch encoding and false positives."""
import argparse
import importlib.util
from pathlib import Path
import struct

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--device', type=Path, required=True)
a = p.parse_args()
spec = importlib.util.spec_from_file_location('native_checker', a.device/'verify_native_artifact.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def blob(*words):
    return struct.pack('<'+'I'*len(words), *words)

def rejected(data, segments, target):
    try:
        module.direct_calls(data, segments, target)
    except ValueError:
        return
    raise AssertionError('Invalid or absent call was accepted')

assert module.direct_calls(blob(0x94000002, 0xd503201f, 0xd65f03c0), [(0x1000, 0, 12)], 0x1008) == [0x1000]
assert module.direct_calls(blob(0xd65f03c0, 0x97ffffff), [(0x1000, 0, 8)], 0x1000) == [0x1004]
rejected(blob(0x14000002, 0xd503201f, 0xd65f03c0), [(0x1000, 0, 12)], 0x1008)
rejected(blob(0x94000002, 0xd503201f, 0xd65f03c0), [(0x1000, 0, 12)], 0x1004)
# Matching bytes outside the supplied executable range do not qualify.
rejected(blob(0x94000002, 0xd503201f, 0xd65f03c0), [(0x1004, 4, 8)], 0x1008)
rejected(blob(0x94000002), [(0x1000, 0, 8)], 0x1008)
rejected(blob(0x94000002), [(0x1001, 0, 4)], 0x1009)
print('PASS emitted AArch64 BL gate: positive/negative displacement, non-call/wrong-target/non-executable/truncated/misaligned rejection')
