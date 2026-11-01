"""Rebuild the AOP firmware completion adapter from C and assembly source."""

import struct
from .core import require
from .kernel_base import Edits, branch
from .kernel_compile import c_helper


def apply(source, project, work):
    edits = Edits(source)
    k, cave, hook = edits.k, 0xfffffff0078bb400, 0xfffffff005b0f9b4
    require(k.read(hook, 4).hex() == '000080d2', 'Inherited firmware-update patch changed.')
    require(k.read(0xfffffff005b0f9d0, 12).hex() == '046440f9840200b4e20301aa', 'Native AOP completion dispatcher changed.')
    require(k.read(0xfffffff005b0fcd4, 12).hex() == '617a00f9280080520c000014', 'Native AOP payload ownership changed.')
    folder = project.root / 'resources/kernel'
    flat, symbols, start = c_helper(project, folder / 'au5_aop_decode.c', folder / 'au5_aop_decode.s', work, '_au5_entry')
    addresses = {name: cave + address - start for name, address in symbols.items() if start <= address < start + len(flat)}
    imports = {'_au5_bytes': 0xfffffff0077676d4, '_au5_length': 0xfffffff007767550,
               '_au5_copy': 0xfffffff0077681a0, '_au5_complete': 0xfffffff005b0fcac, '_au5_printf': 0xfffffff007215444}
    for name, target in imports.items():
        address = addresses[name]
        offset = address - cave
        require(flat[offset:offset+4] == branch(address, address), f'AOP import placeholder changed: {name}')
        flat[offset:offset+4] = branch(address, target)
    require(cave + len(flat) <= 0xfffffff0078bb840, 'AOP helper exceeds its allocation.')
    segment = next(s for s in k.segments if s['name'] == '__TEXT_EXEC')
    require(max(s['addr'] + s['size'] for s in segment['sections']) <= cave and
            0xfffffff0078bb840 <= segment['addr'] + segment['size'], 'AOP helper overlaps native code.')
    edits.put(cave, bytes(len(flat)), flat, 'AOP-only DER extraction and native completion, compiled from source')
    call = struct.unpack('<I', branch(hook, addresses['_au5_entry']))[0] | 0x80000000
    edits.put(hook, bytes.fromhex('000080d2'), struct.pack('<I', call), 'Route the selected firmware-update call through the AOP adapter')
    return bytes(edits.output), {'helper_size': len(flat), 'edits': edits.records, 'other_firmware_tags_keep_inherited_behavior': True}
