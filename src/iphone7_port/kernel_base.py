"""Source implementations of the D through O stages of the frozen HC3 chain.

All driver bytes come from the user's verified kernel. No old build artifacts,
binary deltas, device snapshots, or device-bound IMG4 files are inputs here.
"""

import re
import struct
from pathlib import Path

from .core import require
from .kc import KC


def word(k, address):
    return struct.unpack('<I', k.read(address, 4))[0]


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def branch(pc, target):
    delta = target - pc
    require(delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27), 'ARM64 branch is out of range.')
    return struct.pack('<I', 0x14000000 | ((delta >> 2) & 0x3ffffff))


def symbols(k):
    """Resolve the actual input's LC_SYMTAB, including private kernel exports."""
    pos, result = k.base + 32, {}
    for _ in range(struct.unpack_from('<I', k.data, k.base + 16)[0]):
        command, size = struct.unpack_from('<II', k.data, pos)
        require(size >= 8 and pos + size <= len(k.data), 'Invalid Mach-O load command.')
        if command == 2:
            offset, count, strings, length = struct.unpack_from('<IIII', k.data, pos + 8)
            table = k.data[k.base + strings:k.base + strings + length]
            for i in range(count):
                index, kind, _, _, address = struct.unpack_from('<IBBHQ', k.data, k.base + offset + 16 * i)
                if address and not kind & 0xe0:
                    name = table[index:].split(b'\0', 1)[0].decode()
                    result[name] = address
        pos += size
    return result


class Edits:
    def __init__(self, path):
        self.k = KC(path)
        self.output = bytearray(self.k.data)
        self.records = []

    def put(self, address, old, new, reason, owner=None):
        require(len(old) == len(new), 'An in-place base patch must preserve size.')
        offset = self.k.offset(address)
        require(bytes(self.output[offset:offset + len(old)]) == old, f'Unexpected original bytes at {address:#x}.')
        if owner:
            require(any(s['name'] == '__TEXT_EXEC' and s['addr'] <= address and
                        address + len(old) <= s['addr'] + s['size'] for s in self.k.ksegments(owner)),
                    f'Patch is outside the executable allocation for {owner}.')
        self.output[offset:offset + len(new)] = new
        self.records.append({'address': hex(address), 'offset': offset, 'size': len(new), 'reason': reason})

    def string(self, old, new, *, owner=None):
        formats = re.compile(rb'%(?:[-+ #0]*)(?:\d+)?(?:\.\d+)?(?:ll|l|z|h)?[diuoxXpsc]')
        require(formats.findall(old) == formats.findall(new), 'A log format changes printf arguments.')
        require(len(new) <= len(old), 'A replacement string exceeds its allocation.')
        if owner:
            sections = [sec for s in self.k.ksegments(owner) for sec in s['sections'] if sec['name'] == '__cstring']
            require(len(sections) == 1, 'Ambiguous driver string section.')
            start = self.k.offset(sections[0]['addr'])
            data = self.k.read(sections[0]['addr'], sections[0]['size'])
        else:
            start, data = 0, self.k.data
        require(data.count(old + b'\0') == 1, f'Log format is not unique: {old!r}')
        offset = start + data.index(old + b'\0')
        segment = next(s for s in self.k.segments if self.k.base + s['offset'] <= offset < self.k.base + s['offset'] + s['size'])
        address = segment['addr'] + offset - self.k.base - segment['offset']
        self.put(address, old + b'\0', new + bytes(len(old) + 1 - len(new)), 'Preserve printf arguments while labeling the console')


def watchdog_usb(edits):
    for address, old, new, owner in [
        (0xfffffff006c378a8, '200300b5', '19000014', 'com.apple.driver.AppleARMWatchdogTimer'),
        (0xfffffff006c39268, '40050034', '36000014', 'com.apple.driver.AppleARMWatchdogTimer'),
        (0xfffffff005f3c1c0, '200100b4', '1f2003d5', 'com.apple.driver.AppleEmbeddedUSB'),
    ]:
        edits.put(address, bytes.fromhex(old), bytes.fromhex(new), 'Retain the historical no-PMU watchdog/USB path', owner)


def usb_logging(edits):
    k = edits.k
    for owner, address, old in [
        ('com.apple.driver.AppleEmbeddedUSB', 0xfffffff005f3a228, 'e81f40b9'),
        ('com.apple.driver.AppleEmbeddedUSB', 0xfffffff005f3bdec, 'a8c35cb8'),
        ('com.apple.driver.AppleEmbeddedUSB', 0xfffffff005f3e8a0, 'e82740b9'),
        ('com.apple.driver.AppleS5L8960XUSB', 0xfffffff006c7a228, 'e82f40b9'),
    ]:
        edits.put(address, bytes.fromhex(old), bytes.fromhex('e8008052'), 'Select driver debug categories 0 through 2', owner)
    owner = 'com.apple.iokit.IOUSBDeviceFamily'
    for address, old, new in [(0xfffffff005f6e61c, 'a8c35cb8', '68c641b9'),
                              (0xfffffff005f6e620, '69c641b9', '08090032'),
                              (0xfffffff005f6e624, '2801082a', '08010232')]:
        edits.put(address, bytes.fromhex(old), bytes.fromhex(new), 'Retain controller flags and add the historical logging mask', owner)
    names = symbols(k)
    require(names['_printf'] == 0xfffffff007215444 and names['_IOLog'] == 0xfffffff0077bb330, 'Kernel logging exports changed.')
    for owner in ['com.apple.driver.AppleEmbeddedUSB', 'com.apple.driver.AppleS5L8960XUSB',
                  'com.apple.driver.AppleSynopsysOTGDevice', 'com.apple.iokit.IOUSBDeviceFamily',
                  'com.apple.driver.AppleUSBDeviceMux']:
        found = []
        for s in k.ksegments(owner):
            for section in s['sections']:
                if section['name'] != '__stubs':
                    continue
                for offset in range(0, section['size'], 12):
                    pc = section['addr'] + offset
                    a, b, c = struct.unpack('<III', k.read(pc, 12))
                    if a & 0x9f00001f != 0x90000010 or b & 0xffc003ff != 0xf9400210 or c != 0xd61f0200:
                        continue
                    immediate = signed(((a >> 5) & 0x7ffff) * 4 + ((a >> 29) & 3), 21)
                    got = (pc & ~4095) + (immediate << 12) + ((b >> 10) & 4095) * 8
                    if struct.unpack('<Q', k.read(got, 8))[0] == names['_IOLog']:
                        found.append(pc)
        require(len(found) == 1, f'Expected exactly one IOLog stub in {owner}.')
        edits.put(found[0], k.read(found[0], 4), branch(found[0], names['_printf']), 'Route the driver log stub to printf', owner)


def early_usb_logging(edits):
    k = edits.k
    def call_target(pc):
        op = word(k, pc)
        require(op & 0xfc000000 == 0x94000000, 'Expected BL in the logging guard.')
        return pc + 4 * signed(op & 0x3ffffff, 26)
    def bne_target(pc):
        op = word(k, pc)
        require(op & 0xff00001f == 0x54000001, 'Expected B.NE logging fallback.')
        return pc + 4 * signed((op >> 5) & 0x7ffff, 19)
    pc = 0xfffffff00628e24c
    a, b, c = struct.unpack('<III', k.read(pc, 12))
    require(a & 0x9f00001f == 0x90000010 and b & 0xffc003ff == 0xf9400210 and c == 0xd61f0200, 'Interrupt-state stub changed.')
    got = (pc & ~4095) + (signed(((a >> 5) & 0x7ffff) * 4 + ((a >> 29) & 3), 21) << 12) + ((b >> 10) & 4095) * 8
    require(struct.unpack('<Q', k.read(got, 8))[0] == symbols(k)['_ml_get_interrupts_enabled'], 'Wrong interrupt-state export.')
    before = len(edits.records)
    for lo, hi in [(0xfffffff00627c1f0, 0xfffffff00627c79c), (0xfffffff00627e0b4, 0xfffffff00627e854),
                   (0xfffffff00627ea44, 0xfffffff00627f71c)]:
        for pc in range(lo, hi, 4):
            op, reason = word(k, pc), None
            if op & 0xfff80000 == 0x36f00000:
                destination = pc + 4 * signed((op >> 5) & 0x3fff, 14)
                require(call_target(pc + 4) == 0xfffffff00628e24c and word(k, pc + 8) == 0x7100041f and
                        bne_target(pc + 12) == destination, 'Interrupt-disabled fallback changed.')
                reason = 'Remove only the bit30 log-routing guard'
            elif op == 0x72a80009:
                require(word(k, pc - 4) == 0x52800049 and word(k, pc + 4) == 0x6a28013f and
                        call_target(pc + 12) == 0xfffffff00628e24c and word(k, pc + 16) == 0x7100041f and
                        bne_target(pc + 8) == bne_target(pc + 20), 'Logging-mask context changed.')
                reason = 'Keep only bit1 in the local log mask'
            if reason:
                edits.put(pc, k.read(pc, 4), bytes.fromhex('1f2003d5'), reason, 'com.apple.driver.AppleSynopsysOTGDevice')
    require(len(edits.records) - before == 18, 'Unexpected early USB logging patch count.')


def dock_and_color(edits):
    k = edits.k
    pc = 0xfffffff00627c2d4
    require(k.read(pc, 16).hex() == '81470094601202f9200100b400000090', 'Optional CHRG lookup context changed.')
    edits.put(pc, k.read(pc, 4), bytes.fromhex('000080d2'), 'Select the existing absent-CHRG-function path',
              'com.apple.driver.AppleSynopsysOTGDevice')
    pairs = [
        (b'iBoot version: %.128s\n', b'iB:%.128s\n'),
        (b'iBoot version: %s\n', b'iB:%s\n'),
        (b'%06lu.%06u %s::%s: publishing nub %p for %s\n', b'%06lu.%06u %s:%s PUB %p %s\n'),
        (b'%06lu.%06u %s::%s: cable type is %s\n', b'%06lu.%06u %s:%s %s\n'),
        (b"%s@%s: %s::%s: Can't create phyServiceClient\n", b'%s@%s %s:%s NO phyClient\n'),
        (b"%s@%s: %s::%s: Can't create _powerAssertionPhyServiceClient\n", b'%s@%s %s:%s NO powerPhyClient\n'),
        (b'%s@%s: %s::%s: failed to get provider \n', b'%s@%s %s:%s NO provider\n'),
        (b'%s@%s: %s::%s: AppleSynopsysOTGDevice::start : failed to start _provider \n', b'%s@%s %s:%s provider start FAIL\n'),
        (b'%s@%s: %s::%s: unable to allocate usb ep0 rx buffer memory descriptor\n', b'%s@%s %s:%s NO EP0 RX buffer\n'),
        (b"%s@%s: %s::%s: can't get register map\n", b'%s@%s %s:%s NO reg map\n'),
        (b'%s@%s: %s::%s: failed to find and set max endpoints supported\n', b'%s@%s %s:%s endpoint setup FAIL\n'),
    ]
    for old, body in pairs:
        edits.string(old, b'\x1b[31m' + body.rstrip(b'\n') + b'\x1b[0m\n',
                     owner='com.apple.driver.AppleSynopsysOTGDevice' if old.startswith(b'%s@%s') else None)


def rootful(edits):
    k = edits.k
    # Exact contextual matches from the reviewed PongoOS iOS15 rootful logic.
    # This profile intentionally preserves the three selected historical sites.
    require(k.read(0xfffffff007072a89, 43).startswith(b'rootvp not authenticated after mounting'), 'Root authentication context changed.')
    require(word(k, 0xfffffff0075f1970) == 0x35001160, 'Root authentication branch changed.')
    require(word(k, 0xfffffff006402124) == 0x54000880, 'APFS root-mount privilege branch changed.')
    require(k.read(0xfffffff0064023a8, 12).hex() == 'e8b340b908791f12e8b300b9', 'APFS read/write fallthrough changed.')
    for address, old, new, owner in [
        (0xfffffff0075f196c, '00013fd6', '000080d2', None),
        (0xfffffff006402120, '1f0008eb', '1f0000eb', 'com.apple.filesystems.apfs'),
        (0xfffffff0064023a4, 'a00b7037', '00008052', 'com.apple.filesystems.apfs'),
    ]:
        edits.put(address, bytes.fromhex(old), bytes.fromhex(new), 'Preserve the selected historical rootful mount behavior', owner)
    for old, new in [(b'\x1b[31miB:%.128s\x1b[0m\n', b'\x1b[31mH1:%.128s\x1b[0m\n'),
                     (b'\x1b[31miB:%s\x1b[0m\n', b'\x1b[31mH1:%s\x1b[0m\n'),
                     (b'BSD root: %s, major %d, minor %d\n', b'\x1b[31mH ROOT:%s %d:%d\x1b[0m\n')]:
        edits.string(old, new)


def firmware_update(edits, project, work):
    k = edits.k
    path = Path(project.tool('Kernel64Patcher3'))
    source, output = work / 'patcher-input.raw', work / 'patcher-output.raw'
    source.write_bytes(k.data)
    project.run([path, source, output, '-f'])
    patched = output.read_bytes()
    require(len(patched) == len(k.data) and patched[:4] == bytes.fromhex('cffaedfe'), 'Unexpected Kernel64Patcher3 output layout.')
    edits.put(0xfffffff005b0f9b4, bytes.fromhex('54feff97'), bytes.fromhex('000080d2'),
              'Apply only the AppleFirmwareUpdate -f instruction', 'com.apple.driver.AppleFirmwareUpdateKext')
    require(k.data[:k.base] + patched[:len(k.data) - k.base] == edits.output,
            'Kernel64Patcher3 made changes beyond the selected instruction.')
    require(source.read_bytes() == k.data, 'Kernel64Patcher3 mutated its input.')


def optional_button_wake(edits):
    k, pc = edits.k, 0xfffffff006b9c48c
    require(k.offset(pc) == 0x024ac4a8, 'Button VA/file mapping changed.')
    wake_format = b'function-wake_button_%s\0'
    require(k.read(0xfffffff005795f72, len(wake_format)) == wake_format, 'Optional wake function format changed.')
    require(k.read(pc - 8, 12).hex() == 'e1830191e00314aac3550094' and k.read(pc + 4, 4).hex() == '000300f9',
            'Button lookup/store context changed.')
    require(struct.unpack('<Q', k.read(0xfffffff006fbd400, 8))[0] == 0xfffffff005836224, 'Wrong ARM function resolver.')
    require(k.read(0xfffffff006b9c454, 4).hex() == 'd1550094', 'Ordinary GPIO button lookup changed.')
    edits.put(pc, bytes.fromhex('c3550094'), bytes.fromhex('000080d2'),
              'Select only the optional wake-function absent path; retain ordinary GPIO and interrupts',
              'com.apple.driver.AppleM68Buttons')


FUNCTIONS = {'D': watchdog_usb, 'E': usb_logging, 'F': early_usb_logging, 'G': dock_and_color,
             'H': rootful, 'O': optional_button_wake}


def apply(stage, source, project, work):
    edits = Edits(source)
    if stage == 'I':
        firmware_update(edits, project, work)
    else:
        require(stage in FUNCTIONS, f'Kernel stage {stage} is not ported yet.')
        FUNCTIONS[stage](edits)
    require(len(edits.output) == len(edits.k.data), 'Kernel allocation size changed.')
    return bytes(edits.output), edits.records
