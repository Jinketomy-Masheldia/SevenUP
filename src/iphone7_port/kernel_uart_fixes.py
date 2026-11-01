"""Restore UART metaclass aliases and the four indexed STMB fields."""

import base64
import re
import struct
from .core import load_json
from .kc import KC, plist
from .kernel_chestnut import relocations
from .kernel_base import Edits

N='com.apple.driver.AppleHIDTransportUART'

def hu10(source,donor,metadata):
    k=KC(source)
    sm=metadata
    base,slides=relocations(k)
    donor=KC(donor)
    ds={s['name']:s for s in donor.ksegments(N)}
    dst={n:int(r['addr'],16) for n,r in sm['destination'].items()}
    def local(a):
        return next(dst[n]+a-s['addr']for n,s in ds.items()if n in dst and s['addr']<=a<s['addr']+s['size'])
    out=bytearray(k.data);edits=[];aliases=[];newslides=list(slides)
    def edit(a,b,why):
        p=k.offset(a);old=bytes(out[p:p+len(b)]);out[p:p+len(b)]=b
        edits.append(dict(address=hex(a),offset=p,size=len(b),old=old.hex(),new=bytes(b).hex(),reason=why))
    for t in sm['ABI_adaptation']:
        if 'class_name'not in t:continue
        oldpoint=int(t['old_vtable'],16);oldprefix=local(oldpoint-32);newprefix=int(t['new_vtable'],16)-32
        assert k.read(oldprefix,16)==bytes(16)
        # Copy only class/superclass metadata. The discarded old virtual
        # function table remains zero; all live vptrs still use native16 ABI.
        prefix=k.read(newprefix,16);assert all(struct.unpack('<QQ',prefix))
        edit(oldprefix,prefix,'Restore still-referenced MetaClass/superclass prefix: '+t['class_name'])
        for a in (oldprefix,oldprefix+8):
            assert a-base not in slides;newslides.append(a-base)
        aliases.append(dict(class_name=t['class_name'],old_prefix=hex(oldprefix),new_prefix=hex(newprefix),
                            metaclass=hex(struct.unpack('<Q',prefix[:8])[0]),superclass=hex(struct.unpack('<Q',prefix[8:])[0])))
    assert len(aliases)==3 and len(newslides)==len(slides)+6 and len(set(newslides))==len(newslides)
    packed=struct.pack('<I',len(newslides))+struct.pack('<'+'I'*len(newslides),*newslides)
    xml,count=re.subn(rb'(<key>_PrelinkLinkKASLROffsets</key><data>)[A-Za-z0-9+/=\s]*(</data>)',lambda m:m[1]+base64.b64encode(packed)+m[2],k.xml)
    assert count==1;expected=plist(k.xml);expected['_PrelinkLinkKASLROffsets']=packed;assert plist(xml)==expected
    info=next(s for s in k.segments if s['name']=='__PRELINK_INFO');assert len(xml)<=info['size']
    edit(info['addr'],xml.ljust(info['size'],b'\0'),'Add exactly six KASLR relocation entries')
    for old,new in [(b'HU9 Homer UART classes ready',b'H10 Homer UART classes ready'),
                    (b'\x1b[33mH9D:%.128s\x1b[0m\n\0',b'\x1b[33mHAD:%.128s\x1b[0m\n\0')]:
        assert len(old)==len(new)and k.data.count(old)==1;p=k.data.index(old)
        s=next(s for s in k.segments if k.base+s['offset']<=p<k.base+s['offset']+s['size'])
        edit(s['addr']+p-k.base-s['offset'],new,'Fixed-size version label')
    restored=bytearray(out)
    for e in edits:restored[e['offset']:e['offset']+e['size']]=bytes.fromhex(e['old'])
    assert restored==k.data and len(out)==len(k.data)
    return bytes(out), {'aliases': aliases, 'HU9': sm['HU9'], 'edits': edits}


SITES=[(0xfffffff006ca0f28,0x148,0x150,8,'boot baudrate'),
       (0xfffffff006ca0f2c,0x140,0x148,9,'application baudrate'),
       (0xfffffff006ca0f3c,0x14c,0x154,8,'boot line state'),
       (0xfffffff006ca0f40,0x144,0x14c,9,'application line state')]

def hu11(source,donor,metadata):
    k,donor=KC(source),KC(donor)
    hm=metadata
    old=next(s for s in donor.ksegments(N)if s['name']=='__TEXT_EXEC')['addr']
    dest=int(hm['destination']['__TEXT_EXEC']['addr'],16)
    out=bytearray(k.data);patches=[]
    for source,before,after,reg,name in SITES:
        at=dest+source-old;word=0x52800000|(before<<5)|reg
        assert donor.read(source,4)==k.read(at,4)==struct.pack('<I',word)
        new=(word&~(65535<<5))|(after<<5)
        off=k.offset(at);out[off:off+4]=struct.pack('<I',new)
        patches.append(dict(source=hex(source),address=hex(at),offset=off,
          old=hex(word),new=hex(new),old_member=hex(before),new_member=hex(after),field=name))
    # Labels are fixed length; executable layout and all pointers stay put.
    labels=[]
    for before,after in [(b'H10 Homer UART classes ready',b'H11 Homer UART classes ready'),
                         (b'\x1b[33mHAD:%.128s\x1b[0m\n\0',b'\x1b[33mHBD:%.128s\x1b[0m\n\0')]:
        assert len(before)==len(after)and k.data.count(before)==1
        off=k.data.index(before);out[off:off+len(before)]=after
        labels.append(dict(offset=off,old=before.hex(),new=after.hex()))
    check=bytearray(out)
    for p in patches:check[p['offset']:p['offset']+4]=struct.pack('<I',int(p['old'],16))
    for p in labels:check[p['offset']:p['offset']+len(bytes.fromhex(p['old']))]=bytes.fromhex(p['old'])
    assert check==k.data and len(out)==len(k.data)
    return bytes(out), {'patches': patches, 'labels': labels}


def hu12(source,profile):
    k=KC(source)
    review=load_json(profile);out=bytearray(k.data);patches=[]
    for row in review['calls']:
        at=int(row['address'],16);w=struct.unpack('<I',k.read(at,4))[0]
        assert w&0xffc00000==0xf9400000 and (w>>5)&31==8
        assert (w>>10)&4095==row['HU11_slot']
        new=(w&~(4095<<10))|(row['correct_slot']<<10)
        off=k.offset(at);out[off:off+4]=struct.pack('<I',new)
        patches.append(dict(**row,offset=off,old=hex(w),new=hex(new)))
    labels=[]
    for old,new in [(b'H11 Homer UART classes ready',b'H12 Homer UART classes ready'),
                    (b'\x1b[33mHBD:%.128s\x1b[0m\n\0',b'\x1b[33mHCD:%.128s\x1b[0m\n\0')]:
        assert len(old)==len(new)and k.data.count(old)==1
        off=k.data.index(old);out[off:off+len(old)]=new
        labels.append(dict(offset=off,old=old.hex(),new=new.hex()))
    check=bytearray(out)
    for p in patches:check[p['offset']:p['offset']+4]=struct.pack('<I',int(p['old'],16))
    for p in labels:check[p['offset']:p['offset']+len(bytes.fromhex(p['old']))]=bytes.fromhex(p['old'])
    assert check==k.data and len(out)==len(k.data)
    return bytes(out), {'patches': patches, 'labels': labels}
