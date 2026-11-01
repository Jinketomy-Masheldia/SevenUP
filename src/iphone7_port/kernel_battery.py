"""Checked SN2400 battery ABI binding; all driver bytes come from the donor."""

import struct
from .core import load_json
from .kernel_transplant import fast_symbols
from .kernel_chestnut import relocations, adrp_page
from .kernel_d2333 import bind_private

NAME='com.apple.driver.AppleSN2400Charger'

def prepare(d,k,profile,battery_profile):
    private,review=bind_private(d,k,profile)
    alignment={int(a,16):int(b,16) for a,b in load_json(battery_profile)['instruction_alignment'].items()}
    # Two charger-event dispatchers retain exactly the same 7 instructions.
    for a,b in [(0xfffffff005d4852c,0xfffffff005c9b5bc),
                (0xfffffff005d48548,0xfffffff005c9b5d8)]:
        assert alignment[a]==b and d.read(a,28)==k.read(b,28)
        private[a]=b
    # Native temperature factory and ARM-platform type metadata. The latter is
    # independently located by the aligned 15/16 ADRP+ADD pair below.
    private[0xfffffff005c661dc]=0xfffffff005ca41d4
    private[0xfffffff006ce2300]=0xfffffff006ca40f8
    assert alignment[0xfffffff0059815f4]==0xfffffff0058561e4
    assert alignment[0xfffffff0059815f8]==0xfffffff0058561e8
    for image,pc,want in [(d,0xfffffff0059815f4,0xfffffff006ce2300),
                          (k,0xfffffff0058561e4,0xfffffff006ca40f8)]:
        words=struct.unpack('<II',image.read(pc,8))
        assert adrp_page(words[0],pc)+((words[1]>>10)&4095)==want
    # The ARMPMU data/common/bss layout is identical; the shared cell has an
    # independent native16 consumer in AppleSMC. Preserve the native cell.
    olddata=next(s for s in d.ksegments('com.apple.driver.AppleARMPMU') if s['name']=='__DATA')
    newdata=next(s for s in k.ksegments('com.apple.driver.AppleARMPMU') if s['name']=='__DATA')
    shape=lambda s:[(t['name'],t['addr']-s['addr'],t['size']) for t in s['sections']]
    assert shape(olddata)==shape(newdata)
    cell=0xfffffff007a35d20
    nativecell=newdata['addr']+cell-olddata['addr']
    assert nativecell==0xfffffff007aecee0
    assert d.read(cell,8)==k.read(nativecell,8)==bytes(8)
    assert struct.unpack('<Q',k.read(0xfffffff006dc0780,8))[0]==nativecell
    private[cell]=nativecell
    dn,da=fast_symbols(d);kn,ka=fast_symbols(k)
    # Charger-function base has no inserted slots: compare the complete table.
    oldvt,newvt=0xfffffff006dd5978,0xfffffff006db6738
    count=0
    for i in range(128):
        a=struct.unpack('<Q',d.read(oldvt+8*i,8))[0]
        b=struct.unpack('<Q',k.read(newvt+8*i,8))[0]
        if a==b==0:break
        assert b in {kn[n] for n in da.get(a,[]) if n in kn} or alignment.get(a)==b or d.read(a,16)==k.read(b,16),(i,hex(a),hex(b))
        count+=1
    assert count==46
    assert struct.unpack('<I',d.read(0xfffffff005d48398,4))[0]==0x52800803
    assert struct.unpack('<I',k.read(0xfffffff005c9b428,4))[0]==0x52800803
    ds=d.ksegments(NAME);db,dr=relocations(d);used={}
    for off in dr:
        slot=db+off
        if not any(s['addr']<=slot<s['addr']+s['size'] for s in ds):continue
        target=struct.unpack('<Q',d.read(slot,8))[0]
        if any(s['addr']<=target<s['addr']+s['size'] for s in ds):continue
        if any(n in kn for n in da.get(target,[])):continue
        assert target in private,hex(target)
        used[target]=private[target]
    assert len(used)==20
    review.update(charger_base_slots=count,charger_base_allocation_size=64,
        private_unique_targets_used=len(used),private_bindings={hex(a):hex(b) for a,b in used.items()},
        added_event_dispatchers_byte_identical=True,ARMPMU_data_sections_identical=True,
        shared_cell_native_consumer='AppleSMC relocation at 0xfffffff006dc0780',
        hardware_compatibility_not_proven=True)
    return used,review
