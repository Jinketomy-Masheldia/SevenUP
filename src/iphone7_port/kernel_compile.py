"""Compile project-owned ARM64 helpers and reject runtime dyld fixups."""

import struct
from pathlib import Path

from .core import require

def macho_image(data):
    h = struct.unpack_from("<8I", data)
    assert h[0] == 0xFEEDFACF and h[1] == 0x100000C
    offset, sections, symbols, symtab = 32, [], {}, None
    for _ in range(h[4]):
        command, size = struct.unpack_from("<II", data, offset)
        if command == 0x19:
            count = struct.unpack_from("<I", data, offset + 64)[0]
            for i in range(count):
                sn, sg, va, length, diskoff = struct.unpack_from("<16s16sQQI", data, offset + 72 + 80*i)
                sections.append({"name": sn.rstrip(b"\0").decode(), "segment": sg.rstrip(b"\0").decode(),
                                 "va": va, "size": length, "offset": diskoff})
        elif command == 2:
            symtab = struct.unpack_from("<4I", data, offset + 8)
        elif command == 0x80000022:
            info = struct.unpack_from("<10I", data, offset + 8)
            assert info[1] == info[3] == info[5] == info[7] == 0, "Runtime dyld fixups/imports"
        elif command == 0x80000034:
            raise AssertionError("Unexpected chained fixups in flat helper")
        offset += size
    assert symtab is not None
    symoff, count, stroff, _ = symtab
    for i in range(count):
        index, kind, section, desc, value = struct.unpack_from("<IBBHQ", data, symoff + 16*i)
        start = stroff + index
        name = data[start:data.index(0, start)].decode()
        assert kind & 0xE != 0 or not name, f"Undefined helper symbol: {name}"
        symbols[name] = value
    return sections, symbols

def assembly(project, source, work, entry, alignment=None):
    sdk = project.run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
    obj, linked = work / 'helper.o', work / 'helper.macho'
    project.run(['xcrun', 'clang', '-target', 'arm64-apple-ios16.1', '-isysroot', sdk, '-c', source, '-o', obj])
    linker = project.linker()
    args = [linker, '-arch', 'arm64', '-platform_version', 'ios', '16.1', '16.1', '-e', entry]
    if alignment:
        args += ['-sectalign', '__TEXT', '__text', hex(alignment)]
    project.run([*args, '-no_fixup_chains', '-no_uuid', '-o', linked, obj])
    data = linked.read_bytes()
    sections, symbols = macho_image(data)
    require(len(sections) == 1 and sections[0]['name'] == '__text', 'Unexpected linked helper sections.')
    text = sections[0]
    require(text['va'] == symbols[entry], 'Helper entry is not the beginning of its text.')
    return bytearray(data[text['offset']:text['offset'] + text['size']]), symbols, text['va']


def c_helper(project, source, imports, work, entry, *, assembly_first=False, alignment=None, hidden=False, allow_adrp=False):
    sdk = project.run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
    common = ['xcrun', 'clang', '-target', 'arm64-apple-ios16.1', '-isysroot', sdk]
    body, stubs, linked = work / 'body.o', work / 'imports.o', work / 'helper.macho'
    project.run([*common, '-Os', '-march=armv8-a', '-mgeneral-regs-only', '-mno-outline-atomics',
                 '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
                 '-fno-asynchronous-unwind-tables', *(['-fvisibility=hidden'] if hidden else []), '-c', source, '-o', body])
    project.run([*common, '-c', imports, '-o', stubs])
    linker = project.linker()
    project.run([linker, '-arch', 'arm64', '-platform_version', 'ios', '16.1', '16.1', '-e', entry,
                 *(['-sectalign', '__TEXT', '__text', hex(alignment)] if alignment else []),
                 '-no_fixup_chains', '-no_uuid', '-o', linked, *([stubs, body] if assembly_first else [body, stubs])])
    data = linked.read_bytes()
    sections, symbols = macho_image(data)
    sections = [s for s in sections if s['size']]
    require({s['name'] for s in sections} <= {'__text', '__cstring', '__const'}, 'Unexpected C helper section.')
    text = next(s for s in sections if s['name'] == '__text')
    start, end = text['va'], max(s['va'] + s['size'] for s in sections)
    require(all(s['offset'] - text['offset'] == s['va'] - start for s in sections), 'C helper is not flat.')
    flat = bytearray(data[text['offset']:text['offset'] + end - start])
    words = struct.unpack('<' + 'I' * (text['size']//4), flat[:text['size']])
    require(allow_adrp or not any(w & 0x9f000000 == 0x90000000 for w in words), 'C helper needs explicit page-relative rebasing.')
    return flat, symbols, start


def imported_c(project, address, source, imports, folder, entry):
    from .kernel_base import branch
    folder.mkdir(parents=True, exist_ok=True)
    stubs = folder / 'imports.s'
    stubs.write_text('.text\n' + ''.join(f'.p2align 2\n.globl {name}\n.private_extern {name}\n{name}: b {name}\n' for name in imports))
    flat, symbols, base = c_helper(project, source, stubs, folder, entry)
    mapped = {name: address + value - base for name,value in symbols.items() if base <= value < base + len(flat)}
    for name,target in imports.items():
        offset = mapped[name] - address
        require(flat[offset:offset+4] == branch(mapped[name], mapped[name]), f'Import stub changed: {name}')
        flat[offset:offset+4] = branch(mapped[name], target)
    return flat, {'address': hex(address), 'size': len(flat), 'symbols': {n:hex(v) for n,v in mapped.items()},
                  'imports': {n:hex(v) for n,v in imports.items()}}
