"""Source-based Chestnut transplant; proprietary code is read from the donor IPSW."""

import base64
import collections
import copy
import re
import struct
from xml.sax.saxutils import escape

from .core import require
from .kc import KC, plist

NAME = 'com.apple.driver.AppleChestnutDisplayPMU'
PLATFORM = 'com.apple.driver.AppleARMPlatform'
POOLS = {'__TEXT': '__PRELINK_TEXT', '__TEXT_EXEC': '__PLK_TEXT_EXEC',
         '__DATA': '__PRELINK_DATA', '__DATA_CONST': '__PLK_DATA_CONST'}

def commands(k, va=None):
    off = k.base if va is None else k.offset(va)
    q = off + 32
    for _ in range(struct.unpack_from('<I', k.data, off + 16)[0]):
        cmd, size = struct.unpack_from('<II', k.data, q)
        yield cmd, q, size
        q += size

def image_uuid(k, va):
    return next(k.data[q + 8:q + 24] for cmd, q, size in commands(k, va) if cmd == 27)

def symbols(k):
    byname, byaddr = {}, collections.defaultdict(list)
    for cmd, q, _ in commands(k):
        if cmd != 2:
            continue
        off, count, strings, length = struct.unpack_from('<IIII', k.data, q + 8)
        st = k.data[k.base + strings:k.base + strings + length]
        for i in range(count):
            idx, typ, sect, desc, va = struct.unpack_from('<IBBHQ', k.data, k.base + off + i * 16)
            if not va or typ & 0xe0:
                continue
            name = st[idx:].split(b'\0', 1)[0].decode()
            byname[name] = va
            byaddr[va].append(name)
    return byname, byaddr

def relocations(k):
    d = plist(k.xml)['_PrelinkLinkKASLROffsets']
    words = list(struct.unpack('<' + 'I' * (len(d) // 4), d))
    require(words[0] == len(words) - 1, 'Invalid packed KASLR count')
    require(len(words[1:]) == len(set(words[1:])), 'Duplicate original KASLR slots')
    start = next(s['addr'] for s in k.segments if s['name'] == '__PRELINK_TEXT')
    return start, words[1:]

def xml_value(v):
    if isinstance(v, (bytes, bytearray)):
        return '<data>' + base64.b64encode(v).decode('ascii') + '</data>'
    if isinstance(v, dict):
        return '<dict>' + ''.join('<key>' + escape(k) + '</key>' + xml_value(x) for k, x in v.items()) + '</dict>'
    if isinstance(v, list):
        return '<array>' + ''.join(xml_value(x) for x in v) + '</array>'
    if isinstance(v, bool):
        return '<true/>' if v else '<false/>'
    if isinstance(v, int):
        return '<integer size="64">0x' + format(v, 'x') + '</integer>'
    if isinstance(v, str):
        return '<string>' + escape(v) + '</string>'
    raise TypeError(type(v))

def array_end(xml):
    prefix = b'<dict><key>_PrelinkInfoDictionary</key><array>'
    require(xml.startswith(prefix), 'Unexpected prelink XML prefix')
    depth = 1
    for m in re.finditer(rb'<array\b[^>]*>|</array>', xml[len(prefix):]):
        tag = m[0]
        if tag == b'</array>':
            depth -= 1
        elif not tag.endswith(b'/>'):
            depth += 1
        if depth == 0:
            return len(prefix) + m.start()
    raise RuntimeError('Missing root array end')

def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value

def adrp_page(word, pc):
    imm = ((word >> 29) & 3) | (((word >> 5) & 0x7ffff) << 2)
    return (pc & ~4095) + (signed(imm, 21) << 12)

def encode_adrp(word, pc, page):
    pages = (page - (pc & ~4095)) >> 12
    require(-(1 << 20) <= pages < (1 << 20), 'ADRP out of range')
    imm = pages & 0x1fffff
    return (word & ~0x60ffffe0) | ((imm & 3) << 29) | ((imm >> 2) << 5)

def apply(source, donor, work):
    k, d = KC(source), KC(donor)
    require(NAME not in k.kexts, 'Chestnut already present')
    ds = {s['name']: s for s in d.ksegments(NAME)}
    chunks, plan = {}, {}
    for segname, poolname in POOLS.items():
        s = ds[segname]
        pool = next(x for x in k.segments if x['name'] == poolname)
        occupied = [x for name, info in k.kexts.items() if info.get('_PrelinkExecutableLoadAddr')
                    for x in k.ksegments(name) if x['name'] == segname and x['size']]
        end = max(x['addr'] + x['size'] for x in occupied)
        # Keep the original page offset where possible. __DATA straddles a page
        # in the donor, so put it at 64-byte alignment and rewrite its ADD pairs.
        if segname == '__DATA':
            new = (end + 63) & ~63
        else:
            new = (end & ~4095) | (s['addr'] & 4095)
            if new < end:
                new += 4096
        require(new + s['size'] <= pool['addr'] + pool['size'], 'Insufficient tail: ' + segname)
        require(k.read(new, s['size']) == bytes(s['size']), 'Nonzero destination tail')
        chunks[segname] = bytearray(d.read(s['addr'], s['size']))
        plan[segname] = dict(old=s['addr'], new=new, size=s['size'], pool=poolname)

    def local(va):
        for p in plan.values():
            if p['old'] <= va < p['old'] + p['size']:
                return p['new'] + va - p['old']
        return None

    kn, ka = symbols(k)
    dn, da = symbols(d)
    pds, pts = d.ksegments(PLATFORM), k.ksegments(PLATFORM)
    require(image_uuid(d, d.kexts[PLATFORM]['_PrelinkExecutableLoadAddr']) ==
            image_uuid(k, k.kexts[PLATFORM]['_PrelinkExecutableLoadAddr']), 'Platform UUID differs')
    layout = lambda ss: [(s['name'], s['size'], s['vmsize'],
                         [(x['name'], x['addr'] - s['addr'], x['size']) for x in s['sections']]) for s in ss]
    require(layout(pds) == layout(pts), 'Platform dependency layout differs')
    external = {}

    def bind(va):
        mapped = local(va)
        if mapped is not None:
            return mapped, 'internal'
        aliases = da.get(va, [])
        matches = {kn[n] for n in aliases if n in kn}
        if matches:
            require(len(matches) == 1, 'Conflicting symbol aliases: ' + str(aliases))
            value = next(iter(matches))
            external[hex(va)] = dict(target=hex(value), symbols=aliases, kind='XNU export')
            return value, 'XNU export'
        for a, b in zip(pds, pts):
            if a['addr'] <= va < a['addr'] + a['size']:
                value = b['addr'] + va - a['addr']
                external[hex(va)] = dict(target=hex(value), owner=PLATFORM,
                                         segment=a['name'], relative=hex(va - a['addr']), kind='same UUID dependency')
                return value, 'same UUID dependency'
        raise RuntimeError('Unresolved pointer ' + hex(va))

    # Calls through IOService's vtable use numeric slots. Validate the whole
    # exported table (171 entries), not merely that its symbol exists.
    abi_slots = 0x558 // 8
    for i in range(abi_slots):
        a = struct.unpack('<Q', d.read(dn['__ZTV9IOService'] + i * 8, 8))[0]
        b = struct.unpack('<Q', k.read(kn['__ZTV9IOService'] + i * 8, 8))[0]
        if i == 2:  # unnamed non-deleting destructor, immediately before D0
            stub = bytes.fromhex('08008092080000f9c0035fd6')
            require(d.read(a, 12) == k.read(b, 12) == stub, 'IOService destructor stub differs')
            continue
        require((bind(a)[0] if a else 0) == b, 'IOService vtable ABI differs at ' + hex(i * 8))

    dbase, drel = relocations(d)
    kbase, krel = relocations(k)
    pointer_records, new_offsets = [], []
    for offset in drel:
        slot = dbase + offset
        if local(slot) is None:
            continue
        old = struct.unpack('<Q', d.read(slot, 8))[0]
        target, kind = bind(old)
        seg = next(n for n, p in plan.items() if p['old'] <= slot and slot + 8 <= p['old'] + p['size'])
        struct.pack_into('<Q', chunks[seg], slot - plan[seg]['old'], target)
        new_slot = local(slot)
        new_offsets.append(new_slot - kbase)
        pointer_records.append(dict(old_slot=hex(slot), new_slot=hex(new_slot), old_target=hex(old),
                                    new_target=hex(target), kind=kind))
    require(len(new_offsets) == 441 and not set(new_offsets).intersection(krel), 'Unexpected new relocation set')

    # OSKext slides kmod_info->address itself, outside the coalesced pointer list.
    # kmod_info is 4-byte packed on this ARM64 target: address is at +156.
    old_kmod = d.kexts[NAME]['_PrelinkKmodInfo']
    require(old_kmod == plan['__DATA']['old'], 'Unexpected kmod location')
    require(old_kmod + 156 - dbase not in drel, 'kmod address must not be slid twice')
    require(struct.unpack_from('<Q', chunks['__DATA'], 156)[0] == plan['__TEXT']['old'], 'Wrong kmod address')
    struct.pack_into('<Q', chunks['__DATA'], 156, plan['__TEXT']['new'])

    code = chunks['__TEXT_EXEC']
    oldpc, newpc = plan['__TEXT_EXEC']['old'], plan['__TEXT_EXEC']['new']
    instruction_records = []
    for off in range(0, len(code), 4):
        word = struct.unpack_from('<I', d.read(oldpc, len(code)), off)[0]
        pc, npc = oldpc + off, newpc + off
        if word & 0x9f000000 == 0x90000000:  # ADRP
            page = adrp_page(word, pc)
            candidates = [n for n, p in plan.items()
                          if (p['old'] & ~4095) <= page < ((p['old'] + p['size'] + 4095) & ~4095)]
            require(len(candidates) == 1, 'Unknown or ambiguous ADRP page ' + hex(page))
            segname = candidates[0]
            if segname == '__DATA':
                nxt = struct.unpack_from('<I', code, off + 4)[0]
                require(nxt & 0xffc00000 == 0x91000000 and (nxt >> 5) & 31 == word & 31
                        and nxt & 31 == word & 31, 'Non-adjacent DATA ADRP/ADD')
                oldtarget = page + ((nxt >> 10) & 4095)
                target = local(oldtarget)
                require(target is not None, 'DATA address outside driver')
                newword = encode_adrp(word, npc, target & ~4095)
                newadd = (nxt & ~(4095 << 10)) | ((target & 4095) << 10)
                struct.pack_into('<I', code, off + 4, newadd)
                require(adrp_page(newword, npc) + ((newadd >> 10) & 4095) == target,
                        'DATA relocation roundtrip failed')
                instruction_records.append(dict(pc=hex(pc), kind='ADRP+ADD', old_target=hex(oldtarget),
                                                new_target=hex(target), old_add=hex(nxt), new_add=hex(newadd)))
            else:
                p = plan[segname]
                target = page + p['new'] - p['old']
                newword = encode_adrp(word, npc, target)
                require(adrp_page(newword, npc) == target, 'ADRP relocation failed')
                instruction_records.append(dict(pc=hex(pc), kind='ADRP', old_page=hex(page), new_page=hex(target)))
            struct.pack_into('<I', code, off, newword)
        elif word & 0x7c000000 == 0x14000000:  # B/BL, including tail-call stubs
            target = pc + signed(word & 0x3ffffff, 26) * 4
            require(oldpc <= target < oldpc + len(code), 'External direct branch requires rebinding')
        elif word & 0x9f000000 == 0x10000000 or word & 0x3b000000 == 0x18000000:
            raise RuntimeError('Unexpected ADR / literal load: review ' + hex(pc))
    require(len(instruction_records) == 108 and sum(x['kind'] == 'ADRP+ADD' for x in instruction_records) == 25,
            'Unexpected PC-relative reference count')

    # Update embedded Mach-O segment/section addresses. The outer kernel maps
    # are unchanged. A stripped zero-size LINKEDIT is moved to the host's marker.
    header = chunks['__TEXT']
    oldheader = plan['__TEXT']['old']
    newheader = plan['__TEXT']['new']
    for cmd, absolute, size in commands(d, oldheader):
        q = absolute - d.offset(oldheader)
        if cmd != 25:
            continue
        segname = header[q + 8:q + 24].split(b'\0')[0].decode()
        if segname == '__LINKEDIT':
            require(ds[segname]['size'] == ds[segname]['vmsize'] == 0, 'Nonempty LINKEDIT')
            value = next(s['addr'] for s in k.segments if s['name'] == '__PLK_LINKEDIT')
        else:
            value = plan[segname]['new']
        struct.pack_into('<Q', header, q + 24, value)
        struct.pack_into('<Q', header, q + 40, value - newheader)
        count = struct.unpack_from('<I', header, q + 64)[0]
        for i in range(count):
            sec = q + 72 + i * 80
            a = struct.unpack_from('<Q', header, sec + 32)[0]
            mapped = local(a)
            require(mapped is not None, 'Section address outside donor')
            struct.pack_into('<Q', header, sec + 32, mapped)
            if struct.unpack_from('<I', header, sec + 48)[0]:
                struct.pack_into('<I', header, sec + 48, mapped - newheader)

    # Use a native existing kprintf call as the marker; keep its two arguments.
    old_log = b'AppleDisplayPMU::start: %s _pmuIICNub: %p built 19:29:31 Oct  6 2022\n\0'
    new_log = b'CH1 AppleDisplayPMU::start: %s I2C=%p\n\0'
    require(header.count(old_log) == 1 and len(new_log) <= len(old_log), 'Native start log changed')
    at = header.index(old_log)
    header[at:at + len(old_log)] = new_log.ljust(len(old_log), b'\0')

    entry = {key: copy.deepcopy(d.kexts[NAME][key]) for key in [
        'CFBundleIdentifier', 'CFBundleName', 'CFBundleExecutable', 'CFBundleVersion',
        'CFBundlePackageType', 'OSBundleLibraries', 'IOKitPersonalities',
        '_PrelinkBundlePath', '_PrelinkExecutableSize']}
    entry.update(_PrelinkExecutableLoadAddr=newheader, _PrelinkExecutableSourceAddr=newheader,
                 _PrelinkKmodInfo=local(old_kmod), OSBundleRequired='Root')
    fragment = xml_value(entry).encode()
    insertion = array_end(k.xml)
    xml = k.xml[:insertion] + fragment + k.xml[insertion:]
    offsets = krel + new_offsets
    packed = struct.pack('<I', len(offsets)) + struct.pack('<' + 'I' * len(offsets), *offsets)
    pattern = rb'(<key>_PrelinkLinkKASLROffsets</key><data>)[A-Za-z0-9+/=\s]*(</data>)'
    xml, count = re.subn(pattern, lambda m: m[1] + base64.b64encode(packed) + m[2], xml)
    require(count == 1, 'Missing coalesced slide data')
    info = next(s for s in k.segments if s['name'] == '__PRELINK_INFO')
    require(len(xml) + 1 <= info['size'], 'Prelink XML no longer fits its existing allocation')
    decoded = plist(xml)
    require(decoded['_PrelinkInfoDictionary'][:-1] == plist(k.xml)['_PrelinkInfoDictionary'],
            'Existing prelink entries changed')
    require(decoded['_PrelinkInfoDictionary'][-1] == entry, 'New prelink entry mismatch')

    result = bytearray(k.data)
    for n, p in plan.items():
        off = k.offset(p['new'])
        result[off:off + p['size']] = chunks[n]
    infooff = k.offset(info['addr'])
    result[infooff:infooff + info['size']] = xml.ljust(info['size'], b'\0')
    # Every original byte outside the four new allocations and prelink XML stays.
    reverse = bytearray(result)
    for p in plan.values():
        a = k.offset(p['new'])
        reverse[a:a + p['size']] = bytes(p['size'])
    reverse[infooff:infooff + info['size']] = k.data[infooff:infooff + info['size']]
    require(reverse == k.data, 'Unexpected changes outside append-only allocations')
    (work / 'kernelcache.raw').write_bytes(result)
    post = KC(work / 'kernelcache.raw')
    require(post.segments == k.segments and len(post.kexts) == len(k.kexts) + 1, 'Outer layout / kext count mismatch')
    require(post.kexts[NAME] == entry, 'New kext missing after reparse')
    # All data pointer records must resolve and receive exactly one slide.
    rb, rr = relocations(post)
    require(rr[:len(krel)] == krel and rr[len(krel):] == new_offsets, 'Slide records changed')
    for row in pointer_records:
        slot, target = int(row['new_slot'], 16), int(row['new_target'], 16)
        require(struct.unpack('<Q', post.read(slot, 8))[0] == target, 'Copied pointer mismatch')
        for slide in [0, 0x4000, 0x15e94000, 0x30000000]:
            require(slot + slide - (rb + slide) in set(new_offsets), 'Slide base mismatch')
            require((target + slide) >> 36 == 0xfffffff, 'Slid pointer out of range')
    require(local(old_kmod) + 156 - rb not in rr, 'kmod address would be slid twice')

    return bytes(result), {"allocations": plan, "pointer_count": len(pointer_records), "instruction_rebindings": len(instruction_records), "appended_kext": NAME, "existing_kexts_preserved": True}
