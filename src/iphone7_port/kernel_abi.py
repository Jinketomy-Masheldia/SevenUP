"""Apply reviewed immediate-field ABI changes to instructions read from IPSWs."""

import hashlib
import struct
from .core import load_json, require


def load_plan(donor, profile):
    plan = load_json(profile)
    patches = []
    for row in plan['instruction_fields']:
        address = int(row['address'], 16)
        raw = donor.read(address, 4)
        require(hashlib.sha256(raw).hexdigest() == row['expected_sha256'], f'ABI source word changed at {address:#x}.')
        old = struct.unpack('<I', raw)[0]
        if row['kind'] == 'scalar32':
            new = row['value']
        else:
            require(row['kind'] == 'instruction-immediate', 'Unknown ABI patch kind.')
            mask, shift = int(row['mask'], 16), row['shift']
            require(mask in {0xffff << 5, 4095 << 10, 127 << 15, 511 << 12}, 'Unreviewed instruction immediate mask.')
            require((row['value'] << shift) & ~mask == 0, 'ABI immediate exceeds its field.')
            new = (old & ~mask) | (row['value'] << shift)
        patches.append({'va': address, 'old': old, 'new': new, 'reason': row['reason']})
    pairs = []
    for row in plan.get('pair_veneers', []):
        pairs.append({**row, 'old': struct.unpack('<I', donor.read(row['va'], 4))[0]})
    require(len({p['va'] for p in patches}) == len(patches), 'Duplicate ABI instruction patch.')
    return patches, pairs
