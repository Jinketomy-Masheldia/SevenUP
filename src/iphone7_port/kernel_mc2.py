"""Reproduce the additional switch-only CS42L71 ABI accesses on MC1D."""

import struct
from .core import require
from .kc import KC
from .kernel_base import Edits
from .kernel_abi import load_plan


def apply(source, donor, project, work):
    edits, d = Edits(source), KC(donor)
    name = 'com.apple.driver.AppleCS42L71Audio'
    old = {s['name']: s for s in d.ksegments(name)}
    new = {s['name']: s for s in edits.k.ksegments(name)}
    def local(address):
        return next(new[n]['addr'] + address - s['addr'] for n,s in old.items()
                    if s['addr'] <= address < s['addr'] + s['size'])
    patches, pairs = load_plan(d, project.root / 'profiles/microphone-switch-abi.json')
    require(len(patches) == 82 and not pairs, 'MC2 additional ABI plan changed.')
    for row in patches:
        edits.put(local(row['va']), struct.pack('<I', row['old']), struct.pack('<I', row['new']), row['reason'])
    needle = b'MC1 CS42L71'
    require(edits.k.data.count(needle) == 7, 'MC1 class markers changed.')
    start = 0
    for _ in range(7):
        offset = edits.k.data.index(needle, start)
        start = offset + len(needle)
        segment = next(s for s in edits.k.segments if edits.k.base+s['offset'] <= offset < edits.k.base+s['offset']+s['size'])
        address = segment['addr'] + offset - edits.k.base - segment['offset']
        edits.put(address, needle, b'MC2 CS42L71', 'Retain fixed-size MC2 markers')
    edits.string(b'\x1b[33mMCD:%.128s\x1b[0m\n', b'\x1b[33mM2D:%.128s\x1b[0m\n')
    return bytes(edits.output), {'edits': edits.records, 'additional_instruction_count': len(patches)}
