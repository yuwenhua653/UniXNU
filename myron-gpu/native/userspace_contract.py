"""Use the same A840 wire header in Turnip and the native kernel.

This verifies a transport input, not Metal availability or GPU execution.
"""
import hashlib
from pathlib import Path

ABI_SHA256 = '59bb5757b97d808bb5ee1c71fb55e2e6bb431d4f351b9d2e42511e30b4b8c98a'


def verify_abi(directory):
    path = Path(directory)/'NativeAdrenoABI.h'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != ABI_SHA256:
        raise ValueError('Turnip must use the exact staged A840 ABI; an A740 or modified header is not accepted')
    return dict(header_sha256=digest, version=1, max_buffers=128,
                submit_bytes=3104, device_info_bytes=64,
                kernel_revision='5bbeb3b8d049a637a595090319835a49e58a8b56')
