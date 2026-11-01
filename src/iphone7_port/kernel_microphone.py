"""CS42L71 source transplant: rebuild native-parent vtables and typed metadata."""

import struct
from .core import load_json
from .kernel_chestnut import relocations, adrp_page, signed, encode_adrp
from .kernel_base import branch
from .kernel_transplant import fast_symbols
from .kernel_maggie import adr, bl
from .kernel_abi import load_plan

MAIN='AppleCS42L71Audio'
MIKEY='AppleCS42L71Mikey'
AUDIO='AppleCSCodecMikeyBusAudio'
NAME='com.apple.driver.AppleCS42L71Audio'
OLD='com.apple.driver.AppleANXDPTX'
PARTS=('__TEXT','__TEXT_EXEC','__DATA','__DATA_CONST')

def slot(typ,i):
    if typ in (MAIN,'AppleCSSPIv2Audio'):
        assert i not in (331,332),('Removed EmbeddedAudio virtual',typ,i)
        return i if i<180 else i+3 if i<331 else i+1
    if typ in (MIKEY,'AppleCSHTDCodecMikey'):return i if i<205 else i+2
    return i

def prepare(d,k,profile):
    plan_data = load_json(profile)
    dc,nc = plan_data['classes15'],plan_data['classes16']
    dc[AUDIO].update(vtable='0xfffffff006fce390',virtual_slots=252)
    own={n:c for n,c in dc.items() if c['bundle']==NAME}
    bymeta={int(c['metaclass'],16):n for n,c in dc.items()}
    ds={s['name']:s for s in d.ksegments(NAME)};os={s['name']:s for s in k.ksegments(OLD)}
    dest={}
    for n in PARTS:
        pad=(ds[n]['addr']-os[n]['addr'])%4096
        dest[n]=os[n]['addr']+(pad if ds[n]['size']+pad<=os[n]['size']else 0)
    dest['__TEXT']=os['__TEXT']['addr']
    assert all(dest[n]+ds[n]['size']<=os[n]['addr']+os[n]['size'] for n in PARTS)
    def local(a):
        for n in PARTS:
            if ds[n]['addr']<=a<ds[n]['addr']+ds[n]['size']:return dest[n]+a-ds[n]['addr']
        raise ValueError(hex(a))
    def vt(c):return int(c['vtable'],16)+16
    def vals(c,k):return list(struct.unpack('<'+'Q'*c['virtual_slots'],k.read(vt(c),c['virtual_slots']*8)))
    const_extra=dest['__DATA_CONST']+0x6000
    moved_header=const_extra+16;moved_vt=moved_header+16
    parser=dest['__TEXT_EXEC']+0x28000
    trace=dest['__TEXT_EXEC']+0x29000
    marker=dest['__TEXT_EXEC']+0x30000
    assert marker+256<=os['__TEXT_EXEC']['addr']+os['__TEXT_EXEC']['size']
    raw=plan_data
    private={int(a,16):int(b,16) for a,b in raw['bindings'].items()}
    private[0xfffffff005bb4890]=0xfffffff005ae9b08
    assert d.read(0xfffffff005bb4890,12)==k.read(private[0xfffffff005bb4890],12)
    private[0xfffffff005f78f10]=parser
    nn,_=fast_symbols(k);on,oa=fast_symbols(d)
    # Rebuild all local class virtual tables from the native16 root parents.
    tables={};table_reports={}
    pending=dict(own)
    while pending:
        progressed=False
        for name,c in list(pending.items()):
            parent=bymeta[int(c['super_metaclass'],16)]
            if parent in pending:continue
            old_table=vals(c,d);old_parent=vals(dc[parent],d)
            if parent in tables:table=list(tables[parent])
            else:table=[{'kind':'native','target':x} for x in vals(nc[parent],k)]
            overrides=[]
            for i,x in enumerate(old_table):
                if i<len(old_parent) and x==old_parent[i]:continue
                j=slot(name,i)
                if ds['__TEXT_EXEC']['addr']<=x<ds['__TEXT_EXEC']['addr']+ds['__TEXT_EXEC']['size']:
                    value={'kind':'donor-local','target':x}
                else:
                    targets={nn[n] for n in oa.get(x,[]) if n in nn}
                    assert len(targets)==1,(name,i,hex(x))
                    value={'kind':'native','target':targets.pop()}
                if j<len(table):table[j]=value
                else:assert j==len(table);table.append(value)
                overrides.append({'old_slot':i,'new_slot':j,'function':hex(x)})
            assert len(table)==c['virtual_slots']+(1 if name==MAIN else 2 if name==MIKEY else 0)
            tables[name]=table
            table_reports[name]={'parent':parent,'old_slots':len(old_table),'new_slots':len(table),'overrides':overrides}
            del pending[name];progressed=True
        assert progressed
    # Traced start and handleStart call the real adapted methods.
    tables[MAIN][86]={'kind':'native','target':trace}
    tables[MAIN][slot(MAIN,339)]={'kind':'native','target':trace+0x200}
    special={};extra=[];skip=set()
    base,fix=relocations(d);fixset={base+x for x in fix}
    for n,table in tables.items():
        a=vt(dc[n])
        if n==MIKEY:
            skip.update(range(a,a+dc[n]['virtual_slots']*8,8))
            continue
        for i,v in enumerate(table):
            p=a+i*8;special[p]=v
            if p not in fixset:assert d.read(p,8)==bytes(8);extra.append(p-base)
    # Redirect every absolute pointer to the expanded Mikey table. Constructor
    # address materializations are handled separately, at the exact ADD PC.
    old_header=int(dc[MIKEY]['vtable'],16);old_vt=old_header+16
    redirects=[]
    for off in fix:
        p=base+off
        if p in skip or not any(s['addr']<=p<s['addr']+s['size'] for s in ds.values()):continue
        x=struct.unpack('<Q',d.read(p,8))[0]
        if old_header-16<=x<old_vt:
            assert p not in special
            special[p]={'kind':'native','target':moved_header+x-old_header};redirects.append(hex(p))
    rows={s['addr']+i: {'raw': struct.unpack('<I', d.read(s['addr']+i,4))[0], 'op': 'adrp' if struct.unpack('<I', d.read(s['addr']+i,4))[0]&0x9f000000==0x90000000 else ''} for s in d.ksegments(NAME) if s['name']=='__TEXT_EXEC' for i in range(0,s['size']-3,4)}
    materializations=[]
    for p,r in rows.items():
        if r['op']!='adrp' or p+4 not in rows:continue
        w=r['raw'];v=rows[p+4]['raw'];reg=w&31
        if v&0xffc003ff!=0x91000000|(reg<<5)|reg:continue
        target=adrp_page(w,p)+((v>>10)&4095)
        if old_header-16<=target<old_vt+8:
            materializations.append({'pc':p+4,'reg':reg,'old_target':target,
                                     'new_target':moved_header+target-old_header})
    assert [p['pc'] for p in materializations]==[
        0xfffffff006bc23c8,0xfffffff006bc24a8,0xfffffff006bcbb08,
        0xfffffff006bcbb28,0xfffffff006bcbbf8,0xfffffff006bcbc3c],materializations
    # Typed allocation signatures describe pointer/nonpointer words. Rebuild
    # native parent prefixes as well as updating the byte counts; do not leave
    # a392-word signature attached to the new393-word main object.
    def signatures(obj,bundles):
        found={}
        for bundle in bundles:
            for s in obj.ksegments(bundle):
                for t in s['sections']:
                    if t['name']!='__kalloc_type':continue
                    for a in range(t['addr'],t['addr']+t['size'],64):
                        namep=struct.unpack('<Q',obj.read(a+16,8))[0]
                        name=obj.read(namep,128).split(b'\0')[0].decode().removeprefix('site.')
                        sigp=struct.unpack('<Q',obj.read(a+32,8))[0]
                        sig=obj.read(sigp,2048).split(b'\0')[0]
                        found[name]=(a,sig)
        return found
    parents={bymeta[int(c['super_metaclass'],16)] for c in own.values()}-own.keys()
    bundles={dc[n]['bundle'] for n in parents}
    old_sig=signatures(d,bundles|{NAME});native_sig=signatures(k,bundles)
    rebuilt={};pending=dict(own);signature_pool=bytearray();signature_records=[]
    while pending:
        progressed=False
        for n,c in list(pending.items()):
            parent=bymeta[int(c['super_metaclass'],16)]
            if parent in pending:continue
            a,sig=old_sig[n];parent_old=old_sig[parent][1]
            assert sig.startswith(parent_old),(n,parent)
            parent_new=rebuilt[parent]if parent in rebuilt else native_sig[parent][1]
            sig=parent_new+sig[len(parent_old):]
            expected=(c['instance_size']+(8 if n in (MAIN,AUDIO)else 0)+7)//8
            assert len(sig)==expected,(n,len(sig),expected)
            new_address=dest['__TEXT']+0x4000+len(signature_pool)
            special[a+32]={'kind':'native','target':new_address}
            signature_records.append({'class':n,'descriptor':hex(local(a)),'signature':hex(new_address),'words':len(sig)})
            signature_pool.extend(sig+b'\0');rebuilt[n]=sig;del pending[n];progressed=True
        assert progressed
    assert 0x4000+len(signature_pool)<os['__TEXT']['size']
    patches,pairs=load_plan(d,profile)
    plan=plan_data
    assert not pairs
    def finalize(k,d,out,local,dst,tail,write):
        records=[];newfix=[]
        def edit(a,b,why):write(a,b);records.append({'address':hex(a),'size':len(b),'reason':why})
        edit(dest['__TEXT']+0x4000,signature_pool,'Typed allocation word signatures with native16 parent layouts')
        for p in materializations:
            assert tail+12<parser
            target=p['new_target'];reg=p['reg'];pc=local(p['pc'])
            code=struct.pack('<II',encode_adrp(0x90000000|reg,tail,target&~4095),
                                  0x91000000|((target&4095)<<10)|(reg<<5)|reg)+branch(tail+8,pc+4)
            edit(tail,code,'Materialize expanded Mikey vtable; preserve exact source register')
            edit(pc,branch(pc,tail),'Redirect exact vtable ADD, retaining relocated ADRP before it');tail+=12
        # New Mikey vtable has its own association pair and zero Itanium header.
        edit(local(old_vt),bytes(dc[MIKEY]['virtual_slots']*8),'Erase unreferenced legacy Mikey table; no stale unrelocated donor pointers')
        prefix=struct.pack('<QQQQ',local(int(dc[MIKEY]['metaclass'],16)),int(nc['AppleCSHTDCodecMikey']['metaclass'],16),0,0)
        values=[local(v['target']) if v['kind']=='donor-local'else v['target'] for v in tables[MIKEY]]
        blob=prefix+struct.pack('<'+'Q'*len(values),*values)
        edit(const_extra,blob,'Native285-slot Mikey table outside unchanged original tables')
        newfix.extend([const_extra,const_extra+8]);newfix.extend(range(moved_vt,moved_vt+len(values)*8,8))
        assert const_extra+len(blob)<=os['__DATA_CONST']['addr']+os['__DATA_CONST']['size']
        # Preserve the original legacy decoder, including cases removed in16.
        start=0xfffffff005f78f10;size=1592;raw=bytearray(d.read(start,size));words=list(struct.unpack('<398I',raw))
        strings={};pool=bytearray();targets=set()
        for i,w in enumerate(words):
            pc=start+4*i
            if w&0x7c000000==0x14000000:targets.add(pc+4*signed(w&0x3ffffff,26))
            elif w&0xff000010==0x54000000 or w&0x7e000000==0x34000000:targets.add(pc+4*signed((w>>5)&0x7ffff,19))
        for i,w in enumerate(words):
            pc=start+4*i;npc=parser+4*i
            if w&0x9f000000==0x90000000:
                v=words[i+1];reg=w&31;assert v&0xffc003ff==0x91000000|(reg<<5)|reg
                target=adrp_page(w,pc)+((v>>10)&4095);assert pc+4 not in targets
                if target not in strings:
                    s=d.read(target,256).split(b'\0')[0]+b'\0';assert len(s)<256
                    strings[target]=parser+size+len(pool);pool.extend(s)
                struct.pack_into('<II',raw,4*i,adr(npc,strings[target],reg),0xd503201f)
            elif w&0x7c000000==0x14000000:
                target=pc+4*signed(w&0x3ffffff,26)
                if start<=target<start+size:continue
                a,b,_=struct.unpack('<III',d.read(target,12));assert a&0x9f000000==0x90000000 and b&0xffc00000==0xf9400000
                real=struct.unpack('<Q',d.read(adrp_page(a,target)+((b>>10)&4095)*8,8))[0]
                vals={nn[n] for n in oa.get(real,[]) if n in nn}
                if vals:assert len(vals)==1;value=vals.pop()
                else:assert real==0xfffffff005acf468;value=0xfffffff0059f8468
                struct.pack_into('<I',raw,4*i,struct.unpack('<I',bl(npc,value))[0])
        assert parser+len(raw)+len(pool)<trace
        edit(parser,bytes(raw)+pool,'Retain all original CS codec configuration decoder cases')
        def trace_wrapper(a,real,name):
            # Preserve all eight integer arguments. Stack remains16-byte aligned.
            code=struct.pack('<III',0xa9ba7bfd,0x910003fd,0xa90107e0)
            code+=struct.pack('<III',0xa9020fe2,0xa90317e4,0xa9041fe6)
            begin=a+0x100;okay=a+0x140;fail=a+0x180
            code+=struct.pack('<I',adr(a+len(code),begin,0));code+=bl(a+len(code),nn['_IOLog'])
            code+=struct.pack('<IIII',0xa94107e0,0xa9420fe2,0xa94317e4,0xa9441fe6)
            code+=bl(a+len(code),local(real));code+=struct.pack('<I',0xf9002be0)
            code+=struct.pack('<I',0x34000060) # cbz w0, +12
            code+=struct.pack('<I',adr(a+len(code),okay,0));code+=branch(a+len(code),a+len(code)+8)
            code+=struct.pack('<I',adr(a+len(code),fail,0));code+=bl(a+len(code),nn['_IOLog'])
            code+=struct.pack('<III',0xf9402be0,0xa8c67bfd,0xd65f03c0)
            assert len(code)<0x100
            edit(a,code,'Call real '+name+' with all x0-x7 arguments preserved; trace boolean return')
            for addr,label in [(begin,' begin'),(okay,' success'),(fail,' failure')]:
                edit(addr,b'\x1b[36mMC1 CS42L71 '+name.encode()+label.encode()+b'\x1b[0m\n\0','Cyan hardware path checkpoint')
        trace_wrapper(trace,0xfffffff006bc1214,'start')
        trace_wrapper(trace+0x200,0xfffffff006bc1284,'handleStart')
        init=next(t for s in ds.values() for t in s['sections'] if t['name']=='__mod_init_func')
        original=struct.unpack('<Q',d.read(init['addr']+8,8))[0]
        text=b'\x1b[33mMC1 CS42L71 classes ready; ABI adapted\x1b[0m\n\0'
        code=struct.pack('<II',0xa9bf7bfd,0x910003fd)+bl(marker+8,local(original))
        code+=struct.pack('<I',adr(marker+12,marker+28,0))+bl(marker+16,nn['_IOLog'])+struct.pack('<II',0xa8c17bfd,0xd65f03c0)+text
        edit(marker,code,'Yellow registration marker after all8 real metaclass initializers')
        edit(local(init['addr']+8),struct.pack('<Q',marker),'Retain initializer through marker wrapper')
        records.append({'marker':hex(marker),'trace':hex(trace),'parser':hex(parser),'moved_mikey_table':hex(moved_vt),
                        'table_counts':{n:len(v) for n,v in tables.items()}})
        return marker+len(code),records,newfix
    report={'status':'DRAFT; FINAL IMAGE AND NATIVE EXECUTION AUDIT REQUIRED','classes':table_reports,
            'field_instruction_and_size_patches':len(patches),'reclaimed_bundle':OLD,
            'Mikey_expanded_table':hex(moved_vt),'Mikey_materializations':materializations,
            'Mikey_absolute_redirects':redirects,'legacy_decoder_cloned':True,
            'typed_allocation_signatures':signature_records,
            'unresolved_foreign_dispatches':plan['unresolved_dispatches']}
    return private,report,special,patches,extra,skip,finalize
