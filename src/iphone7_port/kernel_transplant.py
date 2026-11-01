"""Source donor transplant engine with bounded allocation and ABI hooks.

Driver content is always read from the verified IPSW-derived donor kernel.
The full historical hash is also checked by the outer stage runner.
"""

import base64
import bisect
import collections
import copy
import re
import struct
import xml.etree.ElementTree as ET

from .core import require
from .kc import KC, plist
from .kernel_chestnut import commands, relocations, image_uuid, adrp_page, encode_adrp, signed, xml_value
from .kernel_d2333 import entry_range
from .kernel_base import branch

PARTS = ['__TEXT', '__TEXT_EXEC', '__DATA', '__DATA_CONST']

def fast_symbols(k):
    names, addresses = {}, collections.defaultdict(list)
    for cmd, q, _ in commands(k):
        if cmd != 2:
            continue
        off, count, strings, length = struct.unpack_from('<IIII', k.data, q + 8)
        st = k.data[k.base + strings:k.base + strings + length]
        for i in range(count):
            idx, typ, sect, desc, va = struct.unpack_from('<IBBHQ', k.data, k.base + off + i * 16)
            if not va or typ & 0xe0:
                continue
            name = st[idx:st.find(b'\0', idx)].decode()
            names[name] = va
            addresses[va].append(name)
    return names, addresses

def owner_ranges(k):
    return sorted((s['addr'], s['addr'] + s['size'], n, s['name'])
                  for n, e in k.kexts.items() if e.get('_PrelinkExecutableLoadAddr')
                  for s in k.ksegments(n) if s['size'])

def owner(ranges, va):
    i = bisect.bisect_right(ranges, (va, 1 << 65, '', '')) - 1
    if i >= 0 and ranges[i][0] <= va < ranges[i][1]:
        return ranges[i][2:]
    return ('XNU', None)

def xml_replace_entry(k, name, entry):
    a,z=entry_range(k.xml,name)
    removed=k.xml[a:z]
    xml=k.xml[:a]+xml_value(entry).encode()+k.xml[z:]
    ids=set(re.findall(rb'\bID="([^"]+)"',removed))
    root=ET.fromstring(k.xml)
    defs={e.attrib['ID']:e for e in root.iter() if 'ID' in e.attrib}
    def val(e):
        if 'IDREF' in e.attrib:return val(defs[e.attrib['IDREF']])
        if e.tag=='dict':
            es=list(e);return {es[i].text:val(es[i+1]) for i in range(0,len(es),2)}
        if e.tag in ('array','set'):return [val(x) for x in e]
        if e.tag=='integer':return int(e.text or '0',0)
        if e.tag=='data':return base64.b64decode(e.text or '')
        if e.tag=='true':return True
        if e.tag=='false':return False
        return e.text or ''
    inlined=0
    for ident in ids:
        pattern=rb'<\w+\b[^>]*\bIDREF="'+re.escape(ident)+rb'"[^>]*/>'
        replacement=xml_value(val(defs[ident.decode()])).encode()
        xml,count=re.subn(pattern,lambda m:replacement,xml)
        inlined+=count
    require(not ids&set(re.findall(rb'\bIDREF="([^"]+)"',xml)), 'Dangling removed XML definition')
    return xml,inlined

def apply(source, donor, work, OLD, NAME, SOURCE_MARKER, TARGET_MARKER=None,
          preserve_text_span=True, registration_only=False, full_donor_metadata=True,
          private_bindings=None, private_review=None, slot_overrides=None,
          extra_donor_slots=None, donor_word_patches=None, finalize=None, non_instruction_words=None,
          skip_donor_slots=None, expanded_segments=None, entry_transform=None):
    OUT = work
    k, d = KC(source), KC(donor)
    old={s['name']:s for s in k.ksegments(OLD)}
    ds={s['name']:s for s in d.ksegments(NAME)}
    require(not any(OLD in e.get('OSBundleLibraries',{}) for e in k.kexts.values()),'Orion has dependent bundle')
    require(NAME not in k.kexts,'Amp already present')
    # Preserve page offsets where capacity permits; otherwise exact page values
    # are reconstructed by a small ADRP+ADD veneer, as in the working DS2 port.
    dst={}
    for n in PARTS:
        pad=(ds[n]['addr']-old[n]['addr'])%4096
        dst[n]=old[n]['addr']+(pad if ds[n]['size']+pad<=old[n]['size'] else 0)
        if preserve_text_span and n=='__TEXT':
            # The physical header itself must stay at the original scan
            # address. Page alignment is secondary; use ADRP veneers instead.
            dst[n]=old[n]['addr']
        require(dst[n]+ds[n]['size']<=old[n]['addr']+old[n]['size'],'Image does not fit '+n)
    def inside_old(a):return any(old[n]['addr']<=a<old[n]['addr']+old[n]['size'] for n in PARTS)
    def local(a):
        for n in PARTS:
            s=ds[n]
            if s['addr']<=a<s['addr']+s['size']:return dst[n]+a-s['addr']
        return None
    def page_owner(a):
        ns=[n for n in PARTS if ds[n]['addr']&~4095<=a<(ds[n]['addr']+ds[n]['size']+4095)&~4095]
        require(len(ns)==1,'Ambiguous ADRP page '+hex(a))
        return ns[0]
    out=bytearray(k.data)
    def write(a,blob):
        require(any(old[n]['addr']<=a and a+len(blob)<=old[n]['addr']+old[n]['size'] for n in PARTS),
                'Write outside reclaimed Orion allocation '+hex(a))
        off=k.offset(a);out[off:off+len(blob)]=blob
    for n in PARTS:
        write(old[n]['addr'],bytes(old[n]['size']))
        write(dst[n],d.read(ds[n]['addr'],ds[n]['size']))
    db,dr=relocations(d);kb,kr=relocations(k)
    dn,da=fast_symbols(d);kn,ka=fast_symbols(k)
    ranges=owner_ranges(d)
    uuids={};ptrs=[];newrel=[]
    for off in kr:
        a=kb+off
        if inside_old(a):continue
        v=struct.unpack('<Q',k.read(a,8))[0]
        require(not inside_old(v),'External pointer into Orion '+hex(a))
        newrel.append(off)
    if extra_donor_slots:
        require(not set(extra_donor_slots)&set(dr),'Extra donor relocation already exists')
        dr=dr+list(extra_donor_slots)
    for off in dr:
        a=db+off;na=local(a)
        if na is None or (skip_donor_slots and a in skip_donor_slots):continue
        v=struct.unpack('<Q',d.read(a,8))[0];nv=local(v);kind='internal'
        if slot_overrides is not None and a in slot_overrides:
            override=slot_overrides[a]
            nv=local(override['target']) if override['kind']=='donor-local' else override['target']
            require(nv is not None,'Unmapped ABI override')
            write(na,struct.pack('<Q',nv));newrel.append(na-kb)
            ptrs.append(dict(old_slot=hex(a),new_slot=hex(na),old_target=hex(v),new_target=hex(nv),kind='ABI vtable override: '+override['kind']))
            continue
        if nv is None:
            vals={kn[n] for n in da.get(v,[]) if n in kn}
            if vals:
                require(len(vals)==1,'Conflicting XNU export aliases')
                nv=next(iter(vals));kind='XNU export'
            else:
                dep,segname=owner(ranges,v)
                require(dep in d.kexts and dep in k.kexts,'Unknown native dependency '+hex(v))
                if private_bindings is not None and v in private_bindings:
                    nv=private_bindings[v];kind='reviewed cross-version dependency'
                    write(na,struct.pack('<Q',nv));newrel.append(na-kb)
                    ptrs.append(dict(old_slot=hex(a),new_slot=hex(na),old_target=hex(v),new_target=hex(nv),kind=kind))
                    continue
                du=image_uuid(d,d.kexts[dep]['_PrelinkExecutableLoadAddr'])
                ku=image_uuid(k,k.kexts[dep]['_PrelinkExecutableLoadAddr'])
                require(du==ku,'Native dependency UUID differs '+dep)
                shape=lambda ss:[(s['name'],s['size'],s['vmsize'],
                    [(t['name'],t['addr']-s['addr'],t['size']) for t in s['sections']]) for s in ss]
                require(shape(d.ksegments(dep))==shape(k.ksegments(dep)),
                        'Native dependency section layout differs '+dep)
                a_seg=next(s for s in d.ksegments(dep) if s['name']==segname)
                b_seg=next(s for s in k.ksegments(dep) if s['name']==segname)
                require(v-a_seg['addr']<b_seg['size'],'Native dependency segment differs')
                nv=b_seg['addr']+v-a_seg['addr'];kind='identical-UUID dependency'
                uuids[dep]=du.hex()
        write(na,struct.pack('<Q',nv));newrel.append(na-kb)
        ptrs.append(dict(old_slot=hex(a),new_slot=hex(na),old_target=hex(v),new_target=hex(nv),kind=kind))
    dk=d.kexts[NAME]['_PrelinkKmodInfo']
    require(dk+156-db not in dr,'kmod.address would receive a duplicate slide')
    write(local(dk)+156,struct.pack('<Q',dst['__TEXT']))
    code=ds['__TEXT_EXEC'];raw=d.read(code['addr'],code['size'])
    tail=dst['__TEXT_EXEC']+((code['size']+3)&~3)
    adrp=[]
    for i in range(0,len(raw),4):
        pc=code['addr']+i;npc=local(pc);w=struct.unpack_from('<I',raw,i)[0]
        if w&0x9f000000==0x90000000:
            page=adrp_page(w,pc);n=page_owner(page);reg=w&31
            require(reg not in (30,31),'Unexpected ADRP destination')
            value=page+dst[n]-ds[n]['addr']
            if value%4096==0:
                write(npc,struct.pack('<I',encode_adrp(w,npc,value)))
                adrp.append(dict(pc=hex(npc),value=hex(value),kind='page'))
            else:
                require(tail+12<=old['__TEXT_EXEC']['addr']+old['__TEXT_EXEC']['size'],'Veneer overflow')
                add=0x91000000|((value&4095)<<10)|(reg<<5)|reg
                write(tail,struct.pack('<II',encode_adrp(w,tail,value&~4095),add)+branch(tail+8,npc+4))
                write(npc,branch(npc,tail))
                adrp.append(dict(pc=hex(npc),value=hex(value),veneer=hex(tail),kind='page-value-veneer'))
                tail+=12
        elif w&0x7c000000==0x14000000:
            target=pc+signed(w&0x3ffffff,26)*4
            require(code['addr']<=target<code['addr']+code['size'],'External direct donor branch')
        elif w&0x9f000000==0x10000000:
            delta=signed(((w>>29)&3)|(((w>>5)&0x7ffff)<<2),21)
            require(local(pc+delta)==npc+delta,'External donor ADR')
        elif w&0x3b000000==0x18000000:
            delta=signed((w>>5)&0x7ffff,19)*4
            require(local(pc+delta)==npc+delta,'External donor literal')
    adaptation=[]
    for p in donor_word_patches or []:
        a=p['va'];require(d.read(a,4)==struct.pack('<I',p['old']),'Donor ABI instruction differs')
        require(bytes(out[k.offset(local(a)):k.offset(local(a))+4])==d.read(a,4),'ABI patch overlaps relocated code/pointer')
        write(local(a),struct.pack('<I',p['new']))
        adaptation.append({**p,'va':hex(a),'destination':hex(local(a))})
    if finalize is not None:
        finished=finalize(k,d,out,local,dst,tail,write)
        require(len(finished) in (2,3),'Unexpected finalizer result')
        tail,extra=finished[:2]
        if len(finished)==3:
            for va in finished[2]:
                require(inside_old(va) and va%8==0,'Invalid additional relocation')
                newrel.append(va-kb)
        adaptation.extend(extra)
    # No other driver's executable may branch into the reclaimed code allocation.
    direct_audit=0
    for n,e in k.kexts.items():
        if n==OLD or not e.get('_PrelinkExecutableLoadAddr'):continue
        for s in k.ksegments(n):
            if s['name']!='__TEXT_EXEC':continue
            buf=k.read(s['addr'],s['size'])
            # Imported helpers can end with non-instruction string bytes.
            # A trailing 1..3 bytes cannot encode an ARM64 instruction.
            for i in range(0,len(buf)-3,4):
                w=struct.unpack_from('<I',buf,i)[0]
                if w&0x7c000000==0x14000000:
                    target=s['addr']+i+signed(w&0x3ffffff,26)*4
                    if inside_old(target) and non_instruction_words and s['addr']+i in non_instruction_words:
                        require(k.read(s['addr']+i,8).hex()==non_instruction_words[s['addr']+i]['bytes'], 'Reviewed literal changed')
                        continue
                    require(not inside_old(target),'External code branch into Orion')
                    direct_audit+=1
    head=dst['__TEXT'];header_len=32+struct.unpack('<I',d.read(ds['__TEXT']['addr']+20,4))[0]
    header=bytearray(out[k.offset(head):k.offset(head)+header_len])
    for cmd,q,size in commands(d,ds['__TEXT']['addr']):
        if cmd!=25:continue
        q-=d.offset(ds['__TEXT']['addr']);n=header[q+8:q+24].split(b'\0')[0].decode()
        if n=='__LINKEDIT':
            require(ds[n]['size']==0,'Nonempty donor LINKEDIT')
            va=dst['__DATA_CONST']+ds['__DATA_CONST']['size']
        else:va=dst[n]
        vmsize=tail-va if n=='__TEXT_EXEC' else ds[n]['vmsize']
        filesize=tail-va if n=='__TEXT_EXEC' else ds[n]['size']
        if expanded_segments and n in expanded_segments:
            require(n not in ('__TEXT','__TEXT_EXEC','__LINKEDIT'),'Unsupported segment expansion')
            require(ds[n]['size']<=expanded_segments[n]<=old[n]['addr']+old[n]['size']-va,'Expanded segment exceeds allocation')
            vmsize=filesize=expanded_segments[n]
        struct.pack_into('<QQ',header,q+24,va,vmsize)
        struct.pack_into('<QQ',header,q+40,va-head,filesize)
        if preserve_text_span and n=='__TEXT':
            # KCGEN kalloc_type_view_parse walks physical __PRELINK_TEXT using
            # round_up(__TEXT.filesize,64), not the XML kext addresses. Keeping
            # only the shorter donor size creates a false end-of-list marker.
            struct.pack_into('<Q',header,q+32,old[n]['vmsize'])
            struct.pack_into('<Q',header,q+48,old[n]['size'])
        if preserve_text_span and n=='__LINKEDIT':
            # This is a discarded zero-length segment. Retain the original
            # allocation's descriptor instead of inventing an interior endpoint.
            original_q=next(z for c,z,sz in commands(k,old['__TEXT']['addr'])
                if c==25 and k.data[z+8:z+24].split(b'\0')[0]==b'__LINKEDIT')
            header[q:q+size]=k.data[original_q:original_q+size]
        for j in range(struct.unpack_from('<I',header,q+64)[0]):
            z=q+72+j*80;oldva=struct.unpack_from('<Q',header,z+32)[0];va=local(oldva)
            require(va is not None,'Unmapped embedded section')
            struct.pack_into('<Q',header,z+32,va)
            if struct.unpack_from('<I',header,z+48)[0]:struct.pack_into('<I',header,z+48,va-head)
    write(head,header)
    entry={n:copy.deepcopy(d.kexts[NAME][n]) for n in ['CFBundleIdentifier','CFBundleName','CFBundleExecutable',
        'CFBundleVersion','CFBundlePackageType','OSBundleLibraries','IOKitPersonalities','_PrelinkBundlePath','_PrelinkExecutableSize']}
    if full_donor_metadata:
        entry=copy.deepcopy(d.kexts[NAME])
    entry.update(_PrelinkExecutableLoadAddr=head,_PrelinkExecutableSourceAddr=head,
                 _PrelinkKmodInfo=local(dk),OSBundleRequired='Root')
    if preserve_text_span:
        entry['_PrelinkExecutableSize']=old['__TEXT']['size']
    if full_donor_metadata:
        # Match the actual donor's loading policy; do not force an early Root
        # load merely because this is a transplanted driver.
        if 'OSBundleRequired' not in d.kexts[NAME]:entry.pop('OSBundleRequired',None)
    if registration_only:
        entry.pop('IOKitPersonalities',None)
        entry.pop('OSBundleRequired',None)
    if entry_transform is not None:
        entry_transform(entry)
    xml,inlined=xml_replace_entry(k,OLD,entry)
    require(len(newrel)==len(set(newrel)),'Duplicate relocation slots')
    packed=struct.pack('<I',len(newrel))+struct.pack('<'+'I'*len(newrel),*newrel)
    xml,count=re.subn(rb'(<key>_PrelinkLinkKASLROffsets</key><data>)[A-Za-z0-9+/=\s]*(</data>)',
        lambda m:m[1]+base64.b64encode(packed)+m[2],xml)
    require(count==1,'Missing KASLR offset array')
    original=plist(k.xml);parsed=plist(xml)
    expected=copy.deepcopy(original)
    expected['_PrelinkInfoDictionary']=[entry if e['CFBundleIdentifier']==OLD else e for e in expected['_PrelinkInfoDictionary']]
    expected['_PrelinkLinkKASLROffsets']=packed
    require(parsed==expected,'Unrelated metadata changed')
    info=next(s for s in k.segments if s['name']=='__PRELINK_INFO')
    require(len(xml)<=info['size'],'Prelink XML exceeds existing allocation')
    at=k.offset(info['addr']);out[at:at+info['size']]=xml.ljust(info['size'],b'\0')
    marker=SOURCE_MARKER
    newmarker=TARGET_MARKER or (b'\x1b[35mAU3:%.128s\x1b[0m\n\0' if preserve_text_span
               else b'\x1b[35mAU2:%.128s\x1b[0m\n\0')
    require(k.data.count(marker)==1,'AG1 version marker differs')
    ma=k.data.index(marker);out[ma:ma+len(marker)]=newmarker
    allowed=[(k.offset(old[n]['addr']),k.offset(old[n]['addr'])+old[n]['size']) for n in PARTS]
    allowed += [(at,at+info['size']),(ma,ma+len(marker))]
    restored=bytearray(out)
    for a,z in allowed:restored[a:z]=k.data[a:z]
    require(restored==k.data and len(out)==len(k.data),'Changed bytes outside explicit allocations')
    (OUT/'kernelcache.raw').write_bytes(out)
    v=KC(OUT/'kernelcache.raw')
    require(v.segments==k.segments and len(v.kexts)==len(k.kexts),'Outer Mach-O layout changed')
    for n in k.kexts:
        if n==OLD:continue
        require(v.kexts[n]==k.kexts[n],'Unrelated metadata differs')
        for s in k.ksegments(n):
            # A few original codeless kpi aliases expose a zero-VA LINKEDIT;
            # these have no mapped driver bytes and are preserved via metadata.
            if s['size'] and s['addr']:
                require(v.read(s['addr'],s['size'])==k.read(s['addr'],s['size']),'Unrelated driver bytes differ '+n)
    return bytes(out), {
        'replaced_bundle': OLD, 'donor_bundle': NAME, 'identical_UUID_dependencies': uuids,
        'XML_bytes': len(xml), 'XML_capacity': info['size'], 'shared_XML_references_inlined': inlined,
        'rebound_pointer_count': len(ptrs), 'relocation_count': len(newrel),
        'destination': {n: {'addr': hex(dst[n]), 'size': ds[n]['size'], 'capacity': old[n]['addr']+old[n]['size']-dst[n]} for n in PARTS},
        'veneer_end': hex(tail), 'allowed_raw_ranges': allowed, 'private_dependency_review': private_review,
        'ABI_adaptation': adaptation, 'other_driver_direct_branches_checked': direct_audit,
    }
