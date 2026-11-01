"""Verify detached launchd-cache CodeDirectory coverage and hashes locally."""

import hashlib
import struct

from .core import require


def verify_detached(blob, code):
    require(len(blob) >= 12, 'Truncated detached signature.')
    magic, length, count = struct.unpack_from('>III', blob)
    require(magic == 0xfade0cc0 and 12 <= length <= len(blob) and 12 + count * 8 <= length,
            'Invalid detached signature SuperBlob.')
    components = {}
    for index in range(count):
        kind, offset = struct.unpack_from('>II', blob, 12 + index * 8)
        require(offset + 8 <= length and kind not in components, 'Invalid signature component.')
        _, size = struct.unpack_from('>II', blob, offset)
        require(size >= 8 and offset + size <= length, 'Signature component exceeds allocation.')
        components[kind] = blob[offset:offset + size]
    directories = []
    for kind, cd in components.items():
        if len(cd) < 44 or cd[:4] != bytes.fromhex('fade0c02'):
            continue
        offset, _, special, slots, limit = struct.unpack_from('>5I', cd, 16)
        size, algorithm, _, shift = cd[36:40]
        require((algorithm, size) in ((1, 20), (2, 32), (3, 20)) and shift in (12, 14), 'Unsupported CodeDirectory format.')
        require(limit == len(code) and slots == (limit + (1 << shift) - 1) >> shift,
                'Detached signature must cover the entire cache.')
        require(offset >= special * size and offset + slots * size <= len(cd), 'CodeDirectory hash table exceeds allocation.')
        digest = hashlib.sha1 if algorithm == 1 else hashlib.sha256
        for page in range(slots):
            expected = digest(code[page * (1 << shift):min((page + 1) * (1 << shift), limit)]).digest()[:size]
            require(cd[offset + page * size:offset + (page + 1) * size] == expected, 'Detached signature page hash mismatch.')
        for slot in range(1, special + 1):
            expected = digest(components[slot]).digest()[:size] if slot in components else bytes(size)
            require(cd[offset - slot * size:offset - (slot - 1) * size] == expected, 'Detached signature special-slot mismatch.')
        directories.append({'cdhash': digest(cd).digest()[:20].hex(), 'pages': slots, 'slot': kind})
    require(directories, 'Detached signature contains no usable CodeDirectory.')
    return directories
