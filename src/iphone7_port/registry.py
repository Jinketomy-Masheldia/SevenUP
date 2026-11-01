"""Read the registry fields needed by installation from normal ioreg output.

The bundled SSHRD ioreg cannot archive to stdout. Parse its ordinary tree
without evaluating property expressions or requiring extra device utilities.
"""

import json
import plistlib
import re

from .core import require

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
HEADER = re.compile(r'([ |]*)\+-o (.*?)\s+<class ([^,>]+)[,>]')
PROPERTY = re.compile(r'([ |]*)"(IOClass|BSD Name|UUID|FullName|RoleValue|unique-chip-id|ecid|ECID)"\s*=\s*(.*?)\s*$')


def read_registry(data):
    if isinstance(data, bytes):
        if data.startswith(b'bplist'):
            return plistlib.loads(data)
        data = data.decode('utf-8')
    text = ANSI.sub('', data)
    if text.lstrip().startswith(('<?xml', '<plist')):
        return plistlib.loads(text.encode())
    roots, stack = [], []
    for line in text.splitlines():
        header = HEADER.match(line)
        if header:
            depth = len(header[1])
            while stack and stack[-1][0] >= depth:
                stack.pop()
            node = {'IOClass': header[3], 'IORegistryEntryName': header[2], 'IORegistryEntryChildren': []}
            if stack:
                stack[-1][1]['IORegistryEntryChildren'].append(node)
            else:
                roots.append(node)
            stack.append((depth, node))
            continue
        prop = PROPERTY.fullmatch(line)
        if not prop or not stack or len(prop[1]) - stack[-1][0] not in (4, 6):
            continue
        name, value = prop[2], prop[3]
        if value.startswith('"'):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                continue
        elif re.fullmatch(r'0[xX][0-9a-fA-F]+|[0-9]+', value):
            decoded = int(value, 16 if value.lower().startswith('0x') else 10)
        elif re.fullmatch(r'<(?:[0-9a-fA-F]{2}\s*)+>', value):
            decoded = bytes.fromhex(value[1:-1])
        else:
            continue
        require(name not in stack[-1][1] or name == 'IOClass', f'Duplicate registry property: {name}')
        stack[-1][1][name] = decoded
    require(roots, 'ioreg returned an unrecognized registry tree. No installation action was performed.')
    return roots
