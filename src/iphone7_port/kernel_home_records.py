"""HC3 command records: compile the observer and preserve original API forwarding."""

import struct
from .kc import KC
from .kernel_transplant import fast_symbols
from .kernel_chestnut import relocations
from .kernel_base import branch
from .kernel_compile import imported_c
from .kernel_walk import walk

CAVE=0xfffffff006293000
HOOKS={'short':0xfffffff005b9c3f4,'long':0xfffffff005b9c354}

def apply(source, allocation_source, project, work):
    k=KC(source)
    sy,_=fast_symbols(k)
    original=KC(allocation_source)
    allocation=next(s for s in original.ksegments('com.apple.driver.AppleALSColorSensor')if s['name']=='__TEXT_EXEC')
    assert allocation['addr']==CAVE-0x3000 and CAVE+0x1010<=allocation['addr']+allocation['size']
    imports={'_hc2_printf':sy['_printf'],'_hc2_name':sy['__ZNK15IORegistryEntry7getNameEPK15IORegistryPlane'],
             '_hc2_original_short':CAVE+0x1000,'_hc2_original_long':CAVE+0x1008}
    imports['_hc2_property']=sy['__ZN15IORegistryEntry11setPropertyEPKcPvj']
    blob,trace=imported_c(project,CAVE,project.root/'resources/kernel/hc3_button_commands.c',imports,work/'trace','_hc2_short')
    assert len(blob)<=0x1000
    out=bytearray(k.data);patches=[]
    def write(a,new,reason):
        off=k.offset(a);old=k.read(a,len(new));assert out[off:off+len(new)]==old
        out[off:off+len(new)]=new;patches.append(dict(address=hex(a),offset=off,old=old.hex(),new=new.hex(),reason=reason))
    assert k.read(CAVE,0x1010)==bytes(0x1010)
    write(CAVE,blob,'Read-only command observer, scoped by interface name')
    for name,a in HOOKS.items():
        expected=bytes.fromhex('e80303aa'if name=='short'else'ffc300d1')
        assert k.read(a,4)==expected
        trampoline=imports['_hc2_original_'+name]
        write(trampoline,expected+branch(trampoline+4,a+4),'Replay native first instruction, then resume unchanged code')
        write(a,branch(a,int(trace['symbols']['_hc2_'+name],16)),'Redirect native entry through observer')
    # Extend only the imported Homer's executable span within its already
    # reserved former ALS allocation. Nothing moves, and no section is changed.
    e=k.kexts['com.apple.driver.AppleHomerDriver'];q=k.offset(e['_PrelinkExecutableLoadAddr'])+32
    found=0
    for _ in range(struct.unpack_from('<I',k.data,q-16)[0]):
        cmd,size=struct.unpack_from('<II',k.data,q)
        if cmd==25 and k.data[q+8:q+24].split(b'\0')[0]==b'__TEXT_EXEC':
            va,vs,fo,fs=struct.unpack_from('<QQQQ',k.data,q+24)
            assert va==allocation['addr'] and fs==vs and va+fs<=CAVE
            newsize=CAVE+0x1010-va
            for off in [q+32,q+48]:
                old=k.data[off:off+8];new=struct.pack('<Q',newsize);out[off:off+8]=new
                patches.append(dict(offset=off,old=old.hex(),new=new.hex(),reason='Extend imported Homer executable span inside reserved allocation'))
            found+=1
        q+=size
    assert found==1
    (work/'kernelcache.raw').write_bytes(out)
    v=KC(work/'kernelcache.raw');assert v.segments==k.segments and v.kexts==k.kexts and v.xml==k.xml and relocations(v)==relocations(k)
    wa,wb=walk(k),walk(v)
    assert [x['address']for x in wa['headers']]==[x['address']for x in wb['headers']] and wa['terminator']==wb['terminator']
    check=bytearray(out)
    for p in patches:check[p['offset']:p['offset']+len(bytes.fromhex(p['old']))]=bytes.fromhex(p['old'])
    assert check==k.data
    return bytes(out), {'patches': patches, 'trace': trace, 'imports': {n:hex(v)for n,v in imports.items()}, 'native_arguments_and_results_forwarded_unmodified': True}
