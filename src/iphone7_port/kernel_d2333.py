"""D2333 transplant into the existing D2365 allocations; no pool repacking."""

import base64
import collections
import copy
import json
import re
import struct
from .core import require
from .kc import KC, plist
from .kernel_base import branch
from .kernel_chestnut import commands, symbols, relocations, adrp_page, encode_adrp, signed, xml_value

OLD='com.apple.driver.AppleD2365PMU'
NAME='com.apple.driver.AppleD2333PMU'
NAMES=['__TEXT','__TEXT_EXEC','__DATA','__DATA_CONST']

def bind_private(d,k,profile):
    candidates = json.loads(profile.read_text())
    out = {int(a,16): int(b,16) for a,b in candidates['bindings'].items()}
    require(len(out) == 68, 'Private binding count changed')
    # The PMU callback dispatcher is byte-identical for its complete 7-instruction body.
    require(d.read(0xfffffff005d48510,28)==k.read(0xfffffff005c9b5a0,28),'PowerSource callback ABI differs')
    dn,da=symbols(d);kn,ka=symbols(k)
    amap={int(a,16):int(b,16) for a,b in candidates['private_virtual_targets'].items()}
    checks=[]
    for a in [0xfffffff006ce83a0,0xfffffff006ffba10,0xfffffff006ce17a8]:
        b=out[a];count=0
        require(d.read(a,16)==k.read(b,16)==bytes(16),'Vtable header mismatch')
        for off in range(16,0x1000,8):
            x=struct.unpack('<Q',d.read(a+off,8))[0];y=struct.unpack('<Q',k.read(b+off,8))[0]
            if not x or not y:
                require(x==y==0,'Vtable length mismatch');break
            require(y in {kn[n] for n in da.get(x,[]) if n in kn} or amap.get(x)==y,
                    'Private base virtual slot differs '+hex(a)+' '+hex(off))
            count+=1
        checks.append(dict(source=hex(a),target=hex(b),slots=count))
    # Native 16.1 methods are used for calendar conversion and temperature factory:
    # register/struct signatures agree; calendar month clamping was recompiled,
    # temperature factory's own subclass virtual call moved 0x728 -> 0x730.
    # No old factory code or its old virtual offset is transplanted.
    for i in range(171):
        a=struct.unpack('<Q',d.read(dn['__ZTV9IOService']+i*8,8))[0]
        b=struct.unpack('<Q',k.read(kn['__ZTV9IOService']+i*8,8))[0]
        if i==2:require(d.read(a,12)==k.read(b,12)==bytes.fromhex('08008092080000f9c0035fd6'),'IOService destructor differs')
        else:require(a==b==0 or b in {kn[n] for n in da.get(a,[]) if n in kn},'IOService base ABI differs')
    return out,dict(private_targets=68,private_base_vtables=checks,IOService_slots=171,
                    native_calendar_mapping='Manually reviewed date struct -> epoch routine; native 16.1 implementation used',
                    native_temperature_mapping='Manually reviewed factory signature; native 16.1 virtual dispatch used',
                    hardware_compatibility_not_proven=True)

def entry_range(xml,name):
    prefix=b'<dict><key>_PrelinkInfoDictionary</key><array>';require(xml.startswith(prefix),'Unexpected XML')
    start=len(prefix);depth=0;begin=None
    for m in re.finditer(rb'<dict\b[^>]*>|</dict>',xml[start:]):
        tag=m[0];off=start+m.start()
        if tag.startswith(b'</'):
            depth-=1
            if depth==0 and name.encode() in xml[begin:start+m.end()]:return begin,start+m.end()
        elif not tag.endswith(b'/>'):
            if depth==0:begin=off
            depth+=1
    raise RuntimeError('Missing entry '+name)

def apply(source,donor,profile,work):
    k,d = KC(source),KC(donor)
    OUT = work
    old={s['name']:s for s in k.ksegments(OLD)};donor={s['name']:s for s in d.ksegments(NAME)}
    require(all(donor[n]['size']<=old[n]['size'] for n in NAMES),'Donor no longer fits original allocation')
    inside_old=lambda va:any(old[n]['addr']<=va<old[n]['addr']+old[n]['size'] for n in NAMES)
    def local(va):
        for n in NAMES:
            s=donor[n]
            if s['addr']<=va<s['addr']+s['size']:return old[n]['addr']+va-s['addr']
        return None
    def page_owner(page):
        ns=[n for n in NAMES if (donor[n]['addr']&~4095)<=page<((donor[n]['addr']+donor[n]['size']+4095)&~4095)]
        require(len(ns)==1,'Ambiguous donor ADRP page '+hex(page));return ns[0]
    out=bytearray(k.data)
    def write(va,data):
        require(any(old[n]['addr']<=va and va+len(data)<=old[n]['addr']+old[n]['size'] for n in NAMES),
                'Write outside replacement slots '+hex(va))
        a=k.offset(va);out[a:a+len(data)]=data
    for n in NAMES:
        s=old[n];write(s['addr'],d.read(donor[n]['addr'],donor[n]['size']).ljust(s['size'],b'\0'))
    private,abi=bind_private(d,k,profile);dn,da=symbols(d);kn,ka=symbols(k)
    kb,kr=relocations(k);db,dr=relocations(d)
    kept=[];removed=[]
    for off in kr:
        slot=kb+off
        if inside_old(slot):removed.append(off);continue
        target=struct.unpack('<Q',k.read(slot,8))[0]
        require(not inside_old(target),'External reference into replaced D2365 '+hex(slot))
        kept.append(off)
    require(len(removed)==943,'D2365 relocation count changed')
    require(not any(OLD in e.get('OSBundleLibraries',{}) for e in k.kexts.values()),'A driver depends on D2365')
    ptrs=[];added=[]
    for off in dr:
        slot=db+off;dst=local(slot)
        if dst is None:continue
        target=struct.unpack('<Q',d.read(slot,8))[0];value=local(target);kind='internal'
        if value is None:
            vals={kn[n] for n in da.get(target,[]) if n in kn}
            if vals:require(len(vals)==1,'Conflicting export alias');value=next(iter(vals));kind='XNU export'
            else:require(target in private,'Unresolved private import '+hex(target));value=private[target];kind='private dependency'
        write(dst,struct.pack('<Q',value));added.append(dst-kb)
        ptrs.append(dict(old_slot=hex(slot),new_slot=hex(dst),old_target=hex(target),new_target=hex(value),kind=kind))
    require(len(added)==906,'D2333 relocation count changed')
    dk=d.kexts[NAME]['_PrelinkKmodInfo'];require(dk+156-db not in dr,'kmod.address would slide twice')
    write(local(dk)+156,struct.pack('<Q',old['__TEXT']['addr']))

    # 703 immediate pairs can be retargeted in place. For the remaining nine
    # definitions, compute the translated page *value* (possibly unaligned)
    # in a tiny veneer, leaving all original subsequent uses unchanged.
    code=donor['__TEXT_EXEC'];raw=d.read(code['addr'],code['size'])
    tail=old['__TEXT_EXEC']['addr']+((code['size']+3)&~3)
    adrp_records=[];changes=[];stats=collections.Counter()
    for i in range(0,len(raw),4):
        pc=code['addr']+i;npc=local(pc);w=struct.unpack_from('<I',raw,i)[0]
        if w&0x9f000000==0x90000000:
            page=adrp_page(w,pc);n=page_owner(page);reg=w&31
            require(reg not in [30,31],'Unexpected ADRP LR/ZR destination')
            delta=old[n]['addr']-donor[n]['addr'];base=page+delta
            row=dict(pc=hex(pc),new_pc=hex(npc),register=reg,owner=n,old_page=hex(page),translated_base=hex(base))
            v=struct.unpack_from('<I',raw,i+4)[0]
            if base%4096==0:
                nw=encode_adrp(w,npc,base);write(npc,struct.pack('<I',nw));row['kind']='aligned-page';stats[row['kind']]+=1
            elif v&0xffc00000==0x91000000 and (v>>5)&31==reg and v&31==reg:
                a=page+((v>>10)&4095);b=local(a)
                require(b is not None and b==a+delta,'ADD target outside its own segment')
                nw=encode_adrp(w,npc,b&~4095);nv=(v&~(4095<<10))|((b&4095)<<10)
                write(npc,struct.pack('<II',nw,nv));row.update(kind='destructive-ADD',old_target=hex(a),new_target=hex(b));stats[row['kind']]+=1
            elif v&0x3b000000==0x39000000 and not v&(1<<26) and v&(1<<22) and (v>>5)&31==reg and v&31==reg:
                scale=(v>>30)&3;a=page+(((v>>10)&4095)<<scale);b=local(a)
                require(b is not None and b==a+delta and b%(1<<scale)==0,'LDR target outside its own segment/alignment')
                require((v>>22)&3==1,'Review signed load before retargeting')
                nw=encode_adrp(w,npc,b&~4095);nv=(v&~(4095<<10))|(((b&4095)>>scale)<<10)
                write(npc,struct.pack('<II',nw,nv));row.update(kind='destructive-LDR',old_target=hex(a),new_target=hex(b),load_bytes=1<<scale);stats[row['kind']]+=1
            else:
                veneer=tail;tail+=12
                nw=encode_adrp(w,veneer,base&~4095)
                add=0x91000000|((base&4095)<<10)|(reg<<5)|reg
                write(veneer,struct.pack('<II',nw,add)+branch(veneer+8,npc+4))
                write(npc,branch(npc,veneer));row.update(kind='page-value-veneer',veneer=hex(veneer));stats[row['kind']]+=1
            adrp_records.append(row)
        elif w&0x7c000000==0x14000000:
            target=pc+signed(w&0x3ffffff,26)*4
            require(code['addr']<=target<code['addr']+code['size'],'Unexpected external direct branch')
        elif w&0x9f000000==0x10000000:
            x=((w>>29)&3)|(((w>>5)&0x7ffff)<<2);target=pc+signed(x,21)
            require(local(target)==npc+signed(x,21),'External ADR requires review')
        elif w&0x3b000000==0x18000000:
            target=pc+signed((w>>5)&0x7ffff,19)*4
            require(local(target)==npc+signed((w>>5)&0x7ffff,19)*4,'External literal requires review')
    require(stats=={'aligned-page':9,'destructive-ADD':510,'destructive-LDR':193,'page-value-veneer':9},'ADRP profile changed')
    require(tail<=old['__TEXT_EXEC']['addr']+old['__TEXT_EXEC']['size'],'Address veneers exceed original code slot')

    # Rewrite only the donor's embedded header; main kernel load commands stay.
    head=old['__TEXT']['addr'];header_len=32+struct.unpack('<I',d.read(donor['__TEXT']['addr']+20,4))[0]
    header=bytearray(out[k.offset(head):k.offset(head)+header_len])
    for cmd,q,size in commands(d,donor['__TEXT']['addr']):
        if cmd!=25:continue
        q-=d.offset(donor['__TEXT']['addr']);name=header[q+8:q+24].split(b'\0')[0].decode()
        va=old[name]['addr']
        if name=='__LINKEDIT':require(donor[name]['size']==0,'Nonempty donor LINKEDIT')
        struct.pack_into('<Q',header,q+24,va);struct.pack_into('<Q',header,q+40,va-head)
        if name=='__TEXT_EXEC':struct.pack_into('<QQ',header,q+32,old[name]['size'],va-head);struct.pack_into('<Q',header,q+48,old[name]['size'])
        ns=struct.unpack_from('<I',header,q+64)[0]
        for j in range(ns):
            z=q+72+j*80;a=struct.unpack_from('<Q',header,z+32)[0];a=local(a)
            require(a is not None,'Unmapped donor section')
            struct.pack_into('<Q',header,z+32,a)
            if struct.unpack_from('<I',header,z+48)[0]:struct.pack_into('<I',header,z+48,a-head)
    write(head,header)

    # Reuse a native start log, not additional function-entry/return wrappers.
    oldfmt=b'AppleD2333PMU::start: %s _pmuIICNub: %p built 16:49:38 Jun 21 2022\n\0'
    newfmt=b'\x1b[36mDS2 D2333 provider=%s I2C=%p\x1b[0m\n\0'
    off=d.data.index(oldfmt);oldfmtva=next(s['addr']+off-d.base-s['offset'] for s in d.segments if d.base+s['offset']<=off<d.base+s['offset']+s['size'])
    write(local(oldfmtva),newfmt.ljust(len(oldfmt),b'\0'))
    pc=local(0xfffffff006cc30c4);w=struct.unpack('<I',branch(pc,kn['_printf']))[0]|0x80000000
    write(pc,struct.pack('<I',w))
    # Early marker is the sole change outside slots and prelink info.
    marker=b'\x1b[32mCH2:%.128s\x1b[0m\n\0';replacement=b'\x1b[36mDS2:%.128s\x1b[0m\n\0'
    require(k.data.count(marker)==1 and len(marker)==len(replacement),'Early marker differs')
    marker_at=k.data.index(marker);out[marker_at:marker_at+len(marker)]=replacement

    entry={key:copy.deepcopy(d.kexts[NAME][key]) for key in ['CFBundleIdentifier','CFBundleName','CFBundleExecutable',
        'CFBundleVersion','CFBundlePackageType','OSBundleLibraries','IOKitPersonalities','_PrelinkBundlePath','_PrelinkExecutableSize']}
    entry.update(_PrelinkExecutableLoadAddr=head,_PrelinkExecutableSourceAddr=head,
                 _PrelinkKmodInfo=local(dk),OSBundleRequired='Root')
    a,z=entry_range(k.xml,OLD);blob=k.xml[a:z]
    ids=set(re.findall(rb'\bID="([^"]+)"',blob));refs=set(re.findall(rb'\bIDREF="([^"]+)"',k.xml[:a]+k.xml[z:]))
    require(not ids&refs,'Removed XML definitions have external references')
    xml=k.xml[:a]+xml_value(entry).encode()+k.xml[z:]
    offsets=kept+added;require(len(offsets)==len(set(offsets))==379970,'New slide table count/duplicates')
    packed=struct.pack('<I',len(offsets))+struct.pack('<'+'I'*len(offsets),*offsets)
    xml,count=re.subn(rb'(<key>_PrelinkLinkKASLROffsets</key><data>)[A-Za-z0-9+/=\s]*(</data>)',lambda m:m[1]+base64.b64encode(packed)+m[2],xml)
    require(count==1,'Slide table missing')
    decoded=plist(xml);orig=plist(k.xml)
    expect=[entry if e['CFBundleIdentifier']==OLD else e for e in orig['_PrelinkInfoDictionary']]
    require(decoded['_PrelinkInfoDictionary']==expect,'Unrelated prelink entry changed')
    info=next(s for s in k.segments if s['name']=='__PRELINK_INFO')
    require(len(xml)<info['size'],'XML does not fit original allocation')
    at=k.offset(info['addr']);out[at:at+info['size']]=xml.ljust(info['size'],b'\0')
    slots=[(k.offset(old[n]['addr']),k.offset(old[n]['addr'])+old[n]['size']) for n in NAMES]
    allowed=slots+[(at,at+info['size']),(marker_at,marker_at+len(marker))]
    restored=bytearray(out)
    for a,z in allowed:restored[a:z]=k.data[a:z]
    require(restored==k.data and len(out)==len(k.data),'Changed original bytes outside explicit allocations')
    (OUT/'kernelcache.raw').write_bytes(out);v=KC(OUT/'kernelcache.raw')
    require(v.segments==k.segments and len(v.kexts)==len(k.kexts)==230,'Outer layout or kext count changed')
    require(OLD not in v.kexts and v.kexts[NAME]==entry,'Replacement entry missing')
    for n,e in k.kexts.items():
        if n!=OLD:require(v.kexts[n]==e,'Existing driver metadata changed')
    return bytes(out), {'replaced_bundle': OLD, 'donor_bundle': NAME, 'slots': {n: {'source': hex(donor[n]['addr']), 'destination': hex(old[n]['addr']), 'capacity': old[n]['size']} for n in NAMES}, 'private_dependency_review': abi, 'relocation_count': len(offsets), 'pointer_count': len(ptrs), 'address_veneer_bytes': tail - old['__TEXT_EXEC']['addr'] - ((code['size']+3)&~3)}
