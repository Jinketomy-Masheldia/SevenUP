"""Reviewed fixed-build virtual-MCA interface bindings, checked against inputs."""

import struct
from .core import load_json, require
from .kernel_chestnut import adrp_page, signed
from .kernel_transplant import fast_symbols

def normalize(k,sg):
    words=list(struct.unpack('<'+'I'*(sg['size']//4),k.read(sg['addr'],sg['size'])))
    result=words[:];refs={}
    for i,w in enumerate(words):
        pc=sg['addr']+i*4
        if w&0x9f000000==0x90000000:
            result[i]=w&~0x60ffffe0
            if i+1<len(words):
                v=words[i+1];reg=w&31;page=adrp_page(w,pc)
                if v&0xffc00000==0x91000000 and (v>>5)&31==reg:
                    result[i+1]=v&~(4095<<10);refs[pc+4]=page+((v>>10)&4095)
                elif v&0x3b000000==0x39000000 and (v>>5)&31==reg:
                    result[i+1]=v&~(4095<<10);refs[pc+4]=page+(((v>>10)&4095)<<((v>>30)&3))
        elif w&0x7c000000==0x14000000:result[i]=w&~0x3ffffff
        elif w&0xff000010==0x54000000 or w&0x7e000000==0x34000000:result[i]=w&~(0x7ffff<<5)
        elif w&0x7e000000==0x36000000:result[i]=w&~(0x3fff<<5)
        elif w&0x9f000000==0x10000000:result[i]=w&~0x60ffffe0
        elif w&0x3b000000==0x18000000:result[i]=w&~(0x7ffff<<5)
    return words,result,refs

def bind(d,k,profile):
    plan = load_json(profile)
    out = {int(a,16):int(b,16) for a,b in plan['bindings'].items()}
    known = {int(a,16):int(b,16) for a,b in plan['virtual_targets'].items()}
    known.update(out)
    require(len(out) == 63, 'Virtual-MCA private binding count changed.')
    dn,da = fast_symbols(d)
    kn,ka = fast_symbols(k)
    for a,names in da.items():
        targets = {kn[n] for n in names if n in kn}
        if len(targets) == 1:
            known[a] = next(iter(targets))
    for row in plan['review']['private_base_vtables']:
        a,b = int(row['old'],16),int(row['new'],16)
        require(d.read(a,16) == k.read(b,16) == bytes(16), 'Virtual-MCA parent vtable header changed.')
        for i in range(row['slots']):
            x = struct.unpack('<Q',d.read(a+16+i*8,8))[0]
            y = struct.unpack('<Q',k.read(b+16+i*8,8))[0]
            require(known.get(x) == y, 'Virtual-MCA inherited dispatch target changed.')
    parent = 'com.apple.driver.AppleIISController'
    oldseg = next(s for s in d.ksegments(parent) if s['name']=='__TEXT_EXEC')
    newseg = next(s for s in k.ksegments(parent) if s['name']=='__TEXT_EXEC')
    _,oldwords,_ = normalize(d,oldseg)
    _,newwords,_ = normalize(k,newseg)
    for row in plan['review']['complete_nonvirtual_helpers']:
        a,b,size = int(row['old'],16),int(row['new'],16),row['full_normalized_bytes']
        require(out[a] == b, 'Virtual-MCA constructor mapping changed.')
        oi,ni = (a-oldseg['addr'])//4,(b-newseg['addr'])//4
        require(oldwords[oi:oi+size//4] == newwords[ni:ni+size//4], 'Virtual-MCA complete constructor body differs.')
    return out, {'private_targets': len(out), 'checked_private_vtables': len(plan['review']['private_base_vtables']),
                 'normalized_complete_helpers': len(plan['review']['complete_nonvirtual_helpers']),
                 'class_sizes_locked_by_full_input_hashes': plan['review']['unchanged_parent_instance_sizes']}
