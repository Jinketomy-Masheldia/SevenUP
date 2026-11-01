"""Reproduce the historical SEP request layout compatibility checkpoint."""

import struct
from .kc import KC
from .kernel_chestnut import adrp_page, encode_adrp

def apply(source, work):
    k = KC(source)
    OUT = work
    out = bytearray(k.data)
    changes = []
    def edit(a,old,new,why):
        actual=struct.unpack('<I',k.read(a,4))[0];assert actual==old,(hex(a),hex(actual),hex(old))
        struct.pack_into('<I',out,k.offset(a),new)
        changes.append(dict(va=hex(a),before=f'{old:08x}',after=f'{new:08x}',reason=why))
    edit(0xfffffff0062e3000,0x52800068,0x52800048,'Command 15 request version 3 -> 2')
    edit(0xfffffff0062e300c,0xf94013e8,0xd503201f,'Omit v3-only auxiliary input pointer')
    edit(0xfffffff0062e3010,0xa90ca3e9,0xf90067e9,'Store operation alone at request +0x58')
    edit(0xfffffff0062e3014,0xb94033e8,0xd503201f,'Omit v3-only auxiliary input length')
    edit(0xfffffff0062e3018,0xb900dbe8,0xd503201f,'Remove v3-only input length slot')
    # Compact the legacy fields by 16 bytes. Registers and original API stay unchanged.
    stores=[(0x3020,0xf90073e8,8),(0x302c,0x291d23e9,4),
      (0x3030,0x291e5bf4,4),(0x3034,0xb900fbfa,4),(0x3038,0xf90083f7,8),
      (0x303c,0xb9010bf9,4),(0x3040,0xf9008bf8,8),(0x3048,0xb9011be8,4),
      (0x3050,0xf90093e8,8),(0x3058,0xb9012be8,4),(0x3060,0xb9012fe8,4),
      (0x3068,0xf9009be8,8),(0x3070,0xb9013be8,4)]
    for tail,w,scale in stores:
        # STP has signed imm7 at bit15; STR has unsigned imm12 at bit10.
        bit=15 if (w&0x3b000000)==0x29000000 else 10
        edit(0xfffffff0062e0000+tail,w,w-((16//scale)<<bit),'Place legacy request field at v2 offset')
    edit(0xfffffff0062e3078,0xf900a3e8,0xd503201f,'Omit v3-only trailing auxiliary pointer')
    edit(0xfffffff0062e3080,0xb9014be8,0xd503201f,'Omit v3-only trailing auxiliary length')
    edit(0xfffffff0062e3084,0xa9157fff,0xa9137fff,'Initialize legacy output slots 32 bytes earlier')
    # Output fields are 32 bytes earlier. Retain all native ownership/free/error logic.
    accesses=[(0x3090,0xf900abe8,8),(0x309c,0xb9015be8,4),(0x30a8,0xb9015fe8,4),
      (0x30cc,0xf940abe8,8),(0x30d8,0xb9415bf4,4),(0x30e0,0xf940abe0,8),
      (0x30f4,0xf940abe0,8),(0x3104,0xb9415be8,4),(0x3110,0xb9415fe8,4)]
    for tail,w,scale in accesses:
        edit(0xfffffff0062e0000+tail,w,w-((32//scale)<<10),'Read/write legacy output slot')
    # Keep the original constructor intact. Place the legacy constructor and a
    # discriminator in an already mapped, zero-filled, unused MG1 execution span.
    original=0xfffffff0062e2efc; end=0xfffffff0062e316c
    guard=0xfffffff005f86000; legacy=guard+0x40
    size=end-original
    assert k.read(guard,0x400)==b'\0'*0x400
    segment=next(s for s in k.ksegments('com.apple.driver.AppleMaggieARCAudio')if s['name']=='__TEXT_EXEC')
    assert segment['addr']<=guard<legacy+size<=segment['addr']+segment['size']
    legacy_bytes=bytearray(out[k.offset(original):k.offset(end)])
    def sx(v,b):return v-(1<<b)if v&(1<<(b-1))else v
    def branch(pc,target,link=False):
        delta=target-pc;assert not delta%4 and -(1<<27)<=delta<(1<<27)
        return (0x94000000 if link else 0x14000000)|((delta//4)&0x3ffffff)
    relocated=[]
    for off in range(0,size,4):
        w=struct.unpack_from('<I',legacy_bytes,off)[0];pc=original+off;newpc=legacy+off;nw=w
        if w&0x9f000000==0x90000000:
            target=adrp_page(w,pc);nw=encode_adrp(w,newpc,target)
        elif w&0x7c000000==0x14000000:
            target=pc+sx(w&0x3ffffff,26)*4
            if not original<=target<end:nw=branch(newpc,target,bool(w&0x80000000))
        elif w&0x9f000000==0x10000000 or w&0x3b000000==0x18000000:
            raise AssertionError('Unreviewed ADR or literal-load relocation')
        if nw!=w:relocated.append(dict(source=hex(pc),destination=hex(newpc),before=f'{w:08x}',after=f'{nw:08x}'))
        struct.pack_into('<I',legacy_bytes,off,nw)
    out=bytearray(k.data)
    out[k.offset(legacy):k.offset(legacy)+size]=legacy_bytes
    # CBNZ arguments to the local fallback, without touching any call arguments.
    words=[]
    for index,(op,reg) in enumerate([(0xb5000000,3),(0x35000000,4)]):
        words.append(op|(((28-index*4)//4)<<5)|reg)
    words += [0xf9402bf0,0xb5000090,0xb9405bf0,0x35000050,
              branch(guard+24,legacy),branch(guard+28,original)]
    out[k.offset(guard):k.offset(guard)+32]=struct.pack('<8I',*words)
    hook=0xfffffff0062d1e7c
    old_hook=struct.unpack('<I',k.read(hook,4))[0]
    assert hook+sx(old_hook&0x3ffffff,26)*4==original
    struct.pack_into('<I',out,k.offset(hook),branch(hook,guard,True))
    allowed=set(range(k.offset(guard),k.offset(guard)+32))|set(range(k.offset(legacy),k.offset(legacy)+size))|set(range(k.offset(hook),k.offset(hook)+4))
    assert len(out)==len(k.data)
    assert all(i in allowed for i,(a,b) in enumerate(zip(k.data,out))if a!=b)
    # Layout, kext metadata, KASLR fixups, and all other code are byte-identical.
    assert KC(source).xml==k.xml
    (OUT/'kernelcache.raw').write_bytes(out)
    return bytes(out), {'changes': changes, 'native_constructor_and_errors_preserved': True}
