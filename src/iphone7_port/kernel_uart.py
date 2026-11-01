"""Rebuild HU9 UART tracing, typed layouts and Homer firmware adapter."""

import copy
import struct
from .core import load_json
from .kc import KC
from .kernel_base import branch
from .kernel_chestnut import relocations, adrp_page, encode_adrp, signed
from .kernel_transplant import fast_symbols, apply as transplant, xml_replace_entry
from .kernel_uart_prepare import prepare
from .kernel_compile import imported_c

N='com.apple.driver.AppleHIDTransportUART'
OLD='com.apple.iokit.IODisplayPortFamily'

def views(k,n):
    t=next(t for s in k.ksegments(n)for t in s['sections']if t['name']=='__kalloc_type');out={}
    for a in range(t['addr'],t['addr']+t['size'],64):
        np=struct.unpack('<Q',k.read(a+16,8))[0];sp=struct.unpack('<Q',k.read(a+32,8))[0]
        name=k.read(np,180).split(b'\0')[0].decode().removeprefix('site.')
        out[name]=(a,k.read(sp,200).split(b'\0')[0],struct.unpack('<I',k.read(a+44,4))[0])
    return out

def apply(source,donor,project,work):
    k,d=KC(source),KC(donor)
    O=work
    profile=project.root/'profiles/homer-uart-abi.json'
    assert not any(OLD in e.get('OSBundleLibraries',{})for e in k.kexts.values())
    private,review,patches,original_finish,skip,expand=prepare(d,k,profile)
    def compile_blob(address,source,imports,folder,entry):
        return imported_c(project,address,source,imports,folder,entry)
    extra={};secondary_offset=(expand['__DATA_CONST']+15)&~15;expand['__DATA_CONST']=secondary_offset+16+12*8
    native,_=fast_symbols(k);donor_sy,_=fast_symbols(d);db,dr=relocations(d)
    def finish(k,d,out,local,dst,tail,write):
        def label(a,blob):write(a,blob.replace(b'HU1 Homer UART classes ready',b'HU9 Homer UART classes ready'))
        tail,records,added=original_finish(k,d,out,local,dst,tail,label)
        tables={r['class_name']:int(r['new_vtable'],16)for r in records if 'new_vtable'in r}
        primary=tables['AppleHIDTransportDeviceUART'];boot=tables['AppleHIDTransportBootloaderSTMB']
        point=dst['__DATA_CONST']+secondary_offset+16
        get=lambda q,a,n:list(struct.unpack('<'+'Q'*n,q.read(a,n*8)))
        op,np,oc=get(d,0xfffffff006de39d8,10),get(k,0xfffffff006dc8478,12),get(d,0xfffffff006ff0c98,10)
        mapping={0:0,1:1,2:2,3:3,4:4,5:5,6:6,7:8,8:10,9:11};secondary=list(np)
        for a,p in enumerate(oc):
            if p!=op[a]:secondary[mapping[a]]=local(p)
        write(point-16,struct.pack('<QQ',2**64-0x98,0)+struct.pack('<'+'Q'*12,*secondary));added.extend(point+a*8 for a in range(12))
        pairs=next(r['vptr_materializations']for r in records if 'vptr_materializations'in r);sf=[]
        for p in pairs:
            if int(p['target'],16)!=primary:continue
            source=int(p['source'],16)+12;at=int(p['destination'],16)+12
            assert d.read(source,8)==bytes.fromhex('08c11c91084c00f9')
            assert bytes(out[k.offset(at):k.offset(at)+4])==d.read(source,4)
            veneer=(tail+3)&~3;write(veneer,struct.pack('<II',encode_adrp(0x90000008,veneer,point&~4095),0x91000108|((point&4095)<<10))+branch(veneer+8,at+4));write(at,branch(at,veneer));tail=veneer+12
            sf.append(dict(source=hex(source),destination=hex(at),veneer=hex(veneer),target=hex(point)))
        assert len(sf)==5
        # Typed allocation signatures must use the new parent's prefix and
        # the unchanged child's tail, including the newly inserted STMB word.
        dv,pv,nv=views(d,N),views(d,'com.apple.driver.AppleHIDTransport'),views(k,'com.apple.driver.AppleHIDTransport')
        pool=dst['__TEXT']+0x4000;type_records=[]
        assert pool>=dst['__TEXT']+next(s for s in d.ksegments(N)if s['name']=='__TEXT')['size']
        for cls,parent in [('AppleHIDTransportProtocolUART','AppleHIDTransportProtocol'),('AppleHIDTransportDeviceUART','AppleHIDTransportDevice'),('AppleHIDTransportBootloaderSTMB','AppleHIDTransportBootloader')]:
            a,own,size=dv[cls];_,oldp,osize=pv[parent];_,newp,nsize=nv[parent]
            assert len(own)*8==size and len(oldp)*8==osize and len(newp)*8==nsize and own.startswith(oldp)
            signature=newp+own[len(oldp):];assert len(signature)*8==size+nsize-osize
            write(pool,signature+b'\0');write(local(a)+32,struct.pack('<Q',pool));assert a+32-db in dr
            type_records.append(dict(class_name=cls,view=hex(local(a)),signature=hex(pool),old=own.decode(),new=signature.decode(),new_size=len(signature)*8));pool+=len(signature)+1
        assert pool<dst['__TEXT']+0x5000
        # Trace class-specific boundaries and startup factories. No registry
        # access, dynamic logging allocations or success/error substitution.
        rq=lambda a:struct.unpack_from('<Q',out,k.offset(a))[0]
        hooks={name:{'slot':slot,'original':rq(slot)}for name,slot in [
          ('probe',primary+85*8),('start',primary+86*8),('handle_start',primary+198*8),
          ('boot_init',boot+21*8),
          ('boot_212',boot+212*8),('boot_225',boot+225*8),('boot_226',boot+226*8)]}
        # Derive this metaclass vptr from the donor constructor; do not trust
        # an unrelated class's nearby table address.
        classes=load_json(profile)['classes15']
        c=classes['AppleHIDTransportBootloaderSTMB'];pc=int(c['ctor_call'],16)+4
        w,v=struct.unpack('<II',d.read(pc,8));meta=adrp_page(w,pc)+((v>>10)&4095)
        hooks['boot_alloc']={'slot':local(meta)+13*8,'original':rq(local(meta)+13*8)}
        for key,sym in [('workloop','__ZN10IOWorkLoop8workLoopEv'),('interrupt','__ZN22IOInterruptEventSource20interruptEventSourceEP8OSObjectPFvS1_PS_iEP9IOServicei'),('timer','__ZN18IOTimerEventSource16timerEventSourceEP8OSObjectPFvS1_PS_E'),('gate','__ZN13IOCommandGate11commandGateEP8OSObjectPFiS1_PvS2_S2_S2_E')]:
            slots=[]
            for off in dr:
                a=db+off;la=local(a)
                if la is not None and a not in skip and struct.unpack('<Q',d.read(a,8))[0]==donor_sy[sym]:slots.append(la)
            assert len(slots)==1;hooks[key]={'slot':slots[0],'original':native[sym]}
        direct={'uart_config':0xfffffff006c9a008,'uart_activate':0xfffffff006c9a014}
        for key,pc in direct.items():
            w=struct.unpack('<I',d.read(pc,4))[0];assert w&0xfc000000==0x94000000
            hooks[key]={'callsite':local(pc),'original':local(pc+signed(w&0x3ffffff,26)*4)}
        source='typedef unsigned long U;\nextern int hu9_printf(const char *,...);\n#define ARGS U a,U b,U c,U d,U e,U f,U g,U h\n#define PASS a,b,c,d,e,f,g,h\n'
        for name in hooks:
            source+=f'extern U hu9_orig_{name}(ARGS);\nU hu9_{name}(ARGS){{hu9_printf("\\033[35mHU9 {name} begin\\033[0m\\n");U value=hu9_orig_{name}(PASS);hu9_printf("\\033[35mHU9 {name} end=%lx\\033[0m\\n",value);return value;}}\n'
        (O/'trace.c').write_text(source)
        imports={'_hu9_printf':native['_printf'],**{'_hu9_orig_'+n:r['original']for n,r in hooks.items()}}
        address=(tail+15)&~15;blob,trace=compile_blob(address,O/'trace.c',imports,O/'trace','_hu9_start');write(address,blob);tail=(address+len(blob)+15)&~15
        for name,r in hooks.items():
            target=int(trace['symbols']['_hu9_'+name],16);r['target']=target
            if 'slot'in r:write(r['slot'],struct.pack('<Q',target))
            else:
                pc=r['callsite'];write(pc,struct.pack('<I',struct.unpack('<I',branch(pc,target))[0]|0x80000000))
        # homr decoder shares the new UART allocation; all other firmware tags
        # delegate to the exact pre-existing AOP helper, including aopf.
        hook=0xfffffff005b0f9b4;word=struct.unpack('<I',k.read(hook,4))[0];assert word&0xfc000000==0x94000000
        legacy=hook+signed(word&0x3ffffff,26)*4
        imports={'_au5_bytes':native['__ZNK6OSData14getBytesNoCopyEv'],'_au5_length':native['__ZNK6OSData9getLengthEv'],
          '_au5_copy':native['__ZN6OSData9withBytesEPKvj'],'_au5_complete':0xfffffff005b0fcac,'_au5_printf':native['_printf'],'_au5_legacy':legacy}
        blob,fw=compile_blob(tail,project.root/'resources/kernel/hu9_homer_decode.c',imports,O/'firmware','_au5_entry');write(tail,blob);tail=(tail+len(blob)+15)&~15
        extra.update(primary=hex(primary),secondary=hex(point),secondary_fixes=sf,typed_layouts=type_records,trace=trace,hooks=hooks,firmware=fw,firmware_hook=hex(hook),firmware_original_word=hex(word),firmware_legacy=hex(legacy))
        records.append({'HU9':copy.deepcopy(extra)})
        return tail,records,added
    raw,report=transplant(source,donor,work,OLD,N,b'\x1b[33mM2D:%.128s\x1b[0m\n\0',b'\x1b[33mH9D:%.128s\x1b[0m\n\0',private_bindings=private,private_review=review,donor_word_patches=patches,finalize=finish,skip_donor_slots=skip,expanded_segments=expand)
    v=KC(work/'kernelcache.raw')
    entry=copy.deepcopy(v.kexts[N])
    entry['IOKitPersonalities']['AppleHIDTransportDeviceUART']['IOPropertyMatch']={'compatible':b'hid-transport,uart\0','IOTTYBaseName':'homer'}
    xml,_=xml_replace_entry(v,N,entry)
    info=next(s for s in v.segments if s['name']=='__PRELINK_INFO')
    assert len(xml)<=info['size']
    out=bytearray(raw)
    at=v.offset(info['addr'])
    out[at:at+info['size']]=xml.ljust(info['size'],b'\0')
    pc=int(extra['firmware_hook'],16)
    target=int(extra['firmware']['symbols']['_au5_entry'],16)
    assert v.read(pc,4)==k.read(pc,4)
    out[v.offset(pc):v.offset(pc)+4]=struct.pack('<I',struct.unpack('<I',branch(pc,target))[0]|0x80000000)
    return bytes(out), {**report,'HU9':extra,'exact_homer_provider_only':True}
