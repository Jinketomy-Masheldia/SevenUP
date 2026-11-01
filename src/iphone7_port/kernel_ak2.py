"""Reproduce the historical SEP request layout compatibility checkpoint."""

import struct
from .kc import KC
from .kernel_chestnut import adrp_page, encode_adrp

def apply(source, work):
    k = KC(source)
    OUT = work
    out = bytearray(k.data)
    changes = []
    def edit(va,before,after,reason):
        assert struct.unpack('<I',k.read(va,4))[0]==before,hex(va)
        struct.pack_into('<I',out,k.offset(va),after)
        changes.append(dict(va=hex(va),before=f'{before:08x}',after=f'{after:08x}',reason=reason))
    guard=0xfffffff005f86000;legacy=guard+0x40;original=0xfffffff0062e2efc
    edit(guard+8,0xf9402bf0,0xf94023f0,'Check V3-only penultimate pointer at caller SP+0x40; preserve final FS context')
    edit(guard+16,0xb9405bf0,0xb9404bf0,'Check V3-only penultimate length at caller SP+0x48')
    edit(legacy+0xfffffff0062e3068-original,0xf90093e8,0xd503201f,'Do not place new optional pointer into V2 filesystem-context slot')
    edit(legacy+0xfffffff0062e3070-original,0xb9012be8,0xd503201f,'Do not place new optional length into V2 filesystem-context slot')
    edit(legacy+0xfffffff0062e3078-original,0xd503201f,0xf90093e8,'Carry required final FS context pointer from V3 to V2 +0xb0')
    edit(legacy+0xfffffff0062e3080-original,0xd503201f,0xb9012be8,'Carry required final FS context length from V3 to V2 +0xb8')
    allowed={k.offset(int(p['va'],16))+i for p in changes for i in range(4)}
    assert len(out)==len(k.data)and all(i in allowed for i,(a,b)in enumerate(zip(k.data,out))if a!=b)
    (OUT/'kernelcache.raw').write_bytes(out)
    return bytes(out), {'changes': changes, 'native_constructor_and_errors_preserved': True}
