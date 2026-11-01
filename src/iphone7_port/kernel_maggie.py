"""Maggie ABI adaptation with native parent tables and source donor parsing."""

import collections
import struct
from .core import require
from .kernel_chestnut import adrp_page, signed
from .kernel_transplant import fast_symbols
from .kernel_base import branch
from .kernel_abi import load_plan

NAME='com.apple.driver.AppleMaggieARCAudio'
OLD='com.apple.plugin.IOgPTPPlugin'
OLD_VT=0xfffffff006eee820
OLD_PARENT=0xfffffff006e30240
NEW_PARENT=0xfffffff006d83df0
PARSER=0xfffffff005f78f10
PARSER_SIZE=1592

def word(k,a):return struct.unpack('<I',k.read(a,4))[0]

def adr(pc,target,reg):
    delta=target-pc;assert -(1<<20)<=delta<(1<<20)
    n=delta&0x1fffff;return (0x10000000|((n&3)<<29)|((n>>2)<<5)|reg)

def bl(pc,target):return struct.pack('<I',struct.unpack('<I',branch(pc,target))[0]|0x80000000)

def field(n):
    assert n in (0,0x90,0x198)or 0x1b8<=n<=0x268,hex(n)
    return n+(8 if n>=0x198 else 0)

def slot(i):
    assert i not in (331,332),'Obsolete parent slot requires a separate semantic review'
    return i if i<180 else i+3 if i<331 else i+1

def prepare(d,k,profile):
    assert d.data[0:4]in [bytes.fromhex('cafebabe'),bytes.fromhex('cffaedfe')]
    on,oa=fast_symbols(d);nn,na=fast_symbols(k)
    os={s['name']:s for s in k.ksegments(OLD)}
    ds={s['name']:s for s in d.ksegments(NAME)}
    new_exec=os['__TEXT_EXEC']['addr'] # Both donor and destination are page aligned.
    assert ds['__TEXT_EXEC']['addr']%4096==new_exec%4096==0
    parser_va=new_exec+0x20000;marker_va=new_exec+0x21000
    assert marker_va+256<=new_exec+os['__TEXT_EXEC']['size']
    raw_parent=list(struct.unpack('<340Q',d.read(OLD_PARENT,340*8)))
    native_parent=list(struct.unpack('<341Q',k.read(NEW_PARENT,341*8)))
    old_vt=list(struct.unpack('<366Q',d.read(OLD_VT,366*8)))
    assert d.read(OLD_VT+366*8,8)==bytes(8)
    vtable=[{'kind':'native','target':x}for x in native_parent]
    overrides=[]
    for i,fn in enumerate(old_vt[:340]):
        if fn==raw_parent[i]:continue
        j=slot(i);assert ds['__TEXT_EXEC']['addr']<=fn<ds['__TEXT_EXEC']['addr']+ds['__TEXT_EXEC']['size']
        vtable[j]={'kind':'donor-local','target':fn};overrides.append({'old_slot':i,'new_slot':j,'function':hex(fn)})
    for fn in old_vt[340:]:vtable.append({'kind':'donor-local','target':fn})
    assert len(vtable)==367
    special={OLD_VT+8*j:x for j,x in enumerate(vtable)}
    # The imported method's symbols and export stubs are handled separately.
    private={
        0xfffffff006e30230:0xfffffff006d83de0, # native parent vtable header
        0xfffffff007a3bf38:0xfffffff007aea038, # native parent metaclass
        0xfffffff005f65a10:0xfffffff005bd9a78, # ctor: native bool fields + native parent vptr
        0xfffffff005f65a38:0xfffffff005bd9aa4, # dtor: same IOService destructor contract
        0xfffffff005f6b1d8:0xfffffff005bdf294, # named child/report registration, native parent fields
        PARSER:parser_va,                   # clone old fourcc/flag decoder, not the changed 16.1 decoder
        0xfffffff006ce1798:0xfffffff006ca3590, # AppleARMFunction metaclass/parent pair
        0xfffffff006ceba80:0xfffffff006cae7a8, # AppleARMSPIDevice metaclass/parent pair
        0xfffffff0079e0dc8:0xfffffff007a95c60, # ARM function lookup symbol global
        0xfffffff0079e0dc0:0xfffffff007a95c58, # ARM function lookup symbol global
        0xfffffff005964608:0xfffffff005836224, # same property/4cc getter ABI (84 normalized bytes)
        0xfffffff005acd340:0xfffffff0059f66b0, # identical 16-byte scalar math intrinsic
        0xfffffff005aca060:0xfffffff0059f3060, # identical 8-byte scalar math intrinsic
    }
    # Exhaustive XNU base vtable checks: the helper classes retain their layout.
    xnu=[]
    for name,count in [('__ZTV9IOService',168),('__ZTV12IOUserClient',186),('__ZTV8OSObject',15)]:
        for i in range(count):
            a=struct.unpack('<Q',d.read(on[name]+16+8*i,8))[0];b=struct.unpack('<Q',k.read(nn[name]+16+8*i,8))[0]
            assert b in {nn[n]for n in oa.get(a,[])if n in nn}or d.read(a,12)==k.read(b,12)
        xnu.append({'name':name,'slots':count})
    assert word(d,on['__ZN12IOUserClient9MetaClassC1Ev']+24)==word(k,nn['__ZN12IOUserClient9MetaClassC1Ev']+24)==0x52801b03
    # Review the exact inherited flag getter and ordinary IOService state getter.
    assert d.read(0xfffffff005f6e178,8).hex()=='00604639c0035fd6'
    assert k.read(0xfffffff005be2704,8).hex()=='00804639c0035fd6'
    assert d.read(0xfffffff005f6e1b4,16)==k.read(0xfffffff005be2740,16)
    patches,pairs = load_plan(d,profile)
    review={'status':'EXPLICIT ABI ADAPTATION; HARDWARE UNTESTED','parent_size':[440,448],'ARC_size':[616,624],
        'parent_vtable_slots':[340,341],'ARC_vtable_slots':[366,367],'new_parent_prefix_from_native16':True,
        'Maggie_overrides':overrides,'XNU_base_tables':xnu,'IOUserClient_parent_size':216,
        'unchanged_other_parent_sizes':{'AppleARMSPIDevice':224,'AppleARMFunction':40},
        'old_flag_field':hex(0x198),'new_flag_field':hex(0x1a0),'private_member_shift':8,
        'raw_word_patches':len(patches),'pair_access_veneers':len(pairs),'old_flag_decoder_cloned_bytes':PARSER_SIZE,
        'private_targets_outside_reconstructed_vtable':len(private),
        'storage_reuse':OLD,'declared_incoming_bundle_dependencies':[]}
    def finalize(k,d,out,local,dst,tail,write):
        records=[]
        def edit(va,new,why):
            old=bytes(out[k.offset(va):k.offset(va)+len(new)]);write(va,new)
            records.append({'destination':hex(va),'size':len(new),'old':old.hex(),'new':bytes(new).hex(),'reason':why})
        # Pairs cannot always encode the shifted +8 address (Q-pair immediates
        # scale by 16). Temporarily adjust only the base, replay, and restore it.
        for r in pairs:
            pc=local(r['va']);base=r['base_register'];delta=r['delta'];assert delta==8
            assert tail+16<parser_va
            code=struct.pack('<III',0x91000000|(delta<<10)|(base<<5)|base,r['old'],0xd1000000|(delta<<10)|(base<<5)|base)+branch(tail+12,pc+4)
            edit(tail,code,'Replay misaligned/overflowing pair with an exactly restored base register')
            edit(pc,branch(pc,tail),'Branch to pair-access ABI adapter');tail+=16
        assert tail<parser_va
        # Clone the old fourcc/flag decoder, including its old-only labels.
        raw=bytearray(d.read(PARSER,PARSER_SIZE));strings={};pool=bytearray();fixes=[]
        words=list(struct.unpack('<'+'I'*(PARSER_SIZE//4),raw));targets=set()
        for i,w in enumerate(words):
            pc=PARSER+4*i
            if w&0x7c000000==0x14000000:targets.add(pc+4*signed(w&0x3ffffff,26))
            elif w&0xff000010==0x54000000 or w&0x7e000000==0x34000000:targets.add(pc+4*signed((w>>5)&0x7ffff,19))
        for i,w in enumerate(words):
            pc=PARSER+4*i;npc=parser_va+4*i
            if w&0x9f000000==0x90000000:
                v=words[i+1];reg=w&31;assert v&0xffc003ff==0x91000000|(reg<<5)|reg
                old=adrp_page(w,pc)+((v>>10)&4095);assert pc+4 not in targets
                if old not in strings:
                    s=d.read(old,256).split(b'\0')[0]+b'\0';assert s[-1]==0 and len(s)<256
                    strings[old]=parser_va+PARSER_SIZE+len(pool);pool.extend(s)
                struct.pack_into('<II',raw,4*i,adr(npc,strings[old],reg),0xd503201f)
                fixes.append({'pc':hex(npc),'source_string':hex(old),'target_string':hex(strings[old])})
            elif w&0x7c000000==0x14000000:
                target=pc+4*signed(w&0x3ffffff,26)
                if PARSER<=target<PARSER+PARSER_SIZE:continue
                a,b,c=struct.unpack('<III',d.read(target,12));assert a&0x9f000000==0x90000000 and b&0xffc00000==0xf9400000
                real=struct.unpack('<Q',d.read(adrp_page(a,target)+((b>>10)&4095)*8,8))[0]
                names={nn[n]for n in oa.get(real,[])if n in nn}
                if names:assert len(names)==1;new=next(iter(names))
                else:assert real==0xfffffff005acf468;new=0xfffffff0059f8468
                struct.pack_into('<I',raw,4*i,struct.unpack('<I',bl(npc,new))[0])
                fixes.append({'pc':hex(npc),'old_callee':hex(real),'new_callee':hex(new)})
        helper=bytes(raw)+bytes(pool);assert parser_va+len(helper)<marker_va
        edit(parser_va,helper,'Old raw fourcc/flag decoder plus all referenced strings; exported OSObject APIs retained')
        # A cyan loader marker runs after the ARC metaclass initializer. It does
        # not claim that SPI/DMA/hardware initialization has completed.
        init=next(s for s in ds['__DATA_CONST']['sections']if s['name']=='__mod_init_func')
        assert init['size']==24;original=struct.unpack('<Q',d.read(init['addr']+16,8))[0]
        text=b'\x1b[36mMG1 Maggie classes ready (ARC size=624)\x1b[0m\n\0'
        code=struct.pack('<II',0xa9bf7bfd,0x910003fd)+bl(marker_va+8,local(original))+struct.pack('<I',adr(marker_va+12,marker_va+28,0))+bl(marker_va+16,nn['_IOLog'])+struct.pack('<II',0xa8c17bfd,0xd65f03c0)+text
        edit(marker_va,code,'Cyan marker after real metaclass initializer; ordinary console logging')
        edit(local(init['addr']+16),struct.pack('<Q',marker_va),'Retain the original initializer via the marker shim')
        records.append({'decoder_references':fixes,'decoder_size':len(helper),'source_initializer':hex(original),'marker_va':hex(marker_va)})
        return (marker_va+len(code)+15)&~15,records
    return private,review,special,[OLD_VT+366*8-next(s['addr']for s in d.segments if s['name']=='__PRELINK_TEXT')],patches,finalize
