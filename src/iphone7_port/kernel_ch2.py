"""Build CH2 power diagnostics from project-owned assembly source."""

import struct
from .core import require
from .kc import KC
from .kernel_base import branch, symbols as kernel_symbols
from .kernel_compile import assembly

CAVE = 0xfffffff0078bb000

def apply(source, project, work):
    k = KC(source)
    flat, symbols, linked_base = assembly(project, project.root / 'resources/kernel/ch2_green_trace.s', work, '_ch2_wait', 0x1000)
    require(len(flat) < 4096, 'CH2 helper exceeds its reserved allocation.')
    addrs = {n:CAVE+v-linked_base for n,v in symbols.items()}
    imports = {
        '_ch2_printf': (0xfffffff007215444,'_printf'),
        '_ch2_data_bytes': (0xfffffff0077676d4,'__ZNK6OSData14getBytesNoCopyEv'),
        '_ch2_string_bytes': (0xfffffff007791944,'__ZNK8OSString16getCStringNoCopyEv'),
        '_ch2_native_wait': (0xfffffff005868ee4,None),
        '_ch2_native_meta': (0xfffffff006c86c5c,None),
        '_ch2_start_resume': (0xfffffff006c860d4,None),
        '_ch2_handle_resume': (0xfffffff006c86818,None),
    }
    exports = kernel_symbols(k)
    for n,(addr,symbol) in imports.items():
        if symbol:
            require(exports.get(symbol) == addr,
                    'Unverified export '+symbol)
        off = addrs[n]-CAVE
        require(flat[off:off+4]==struct.pack('<I',0xd4205840),'Missing import BRK')
        flat[off:off+4]=branch(addrs[n],addr)
    textseg=next(s for s in k.segments if s['name']=='__TEXT_EXEC')
    require(max(s['addr']+s['size'] for s in textseg['sections'])<=CAVE,'Cave overlaps native section')
    require(CAVE+len(flat)<=textseg['addr']+textseg['size'],'Cave outside executable mapping')
    require(k.read(CAVE,4096)==bytes(4096),'Cave is occupied')

    result=bytearray(k.data)
    records=[]
    def change(va,old,new,reason):
        off=k.offset(va)
        require(len(old)==len(new) and k.read(va,len(old))==old,'Hook input mismatch '+hex(va))
        require(result[off:off+len(old)]==old,'Overlapping patch')
        result[off:off+len(new)]=new
        records.append(dict(va=hex(va),offset=off,old=old.hex(),new=new.hex(),reason=reason))
    change(CAVE,bytes(len(flat)),flat,'Position-independent green diagnostic helpers')
    hooks=[
      (0xfffffff005836310,'f5ca0094','_ch2_wait',True,'Trace selected power-provider wait and result; retain native wait'),
      (0xfffffff006c86b7c,'38000094','_ch2_meta',True,'Trace native Chestnut metaclass constructor'),
      (0xfffffff006c860d0,'ffc300d1','_ch2_start_entry',False,'Trace start entry; replay SUB SP'),
      (0xfffffff006c8618c,'c0035fd6','_ch2_start_return',False,'Trace native start boolean after epilogue'),
      (0xfffffff006c86814,'ffc300d1','_ch2_handle_entry',False,'Trace handleStart entry; replay SUB SP'),
      (0xfffffff006c86944,'c0035fd6','_ch2_handle_return',False,'Trace native handleStart IOReturn after epilogue'),
      (0xfffffff006c86178,'00013fd6','_ch2_publish',True,'Trace original registerService BLR x8; preserve arguments/target'),
    ]
    for va,old,name,link,reason in hooks:
        w=struct.unpack('<I',branch(va,addrs[name]))[0] | (0x80000000 if link else 0)
        change(va,bytes.fromhex(old),struct.pack('<I',w),reason)
    # Route the pre-existing provider printf format through the same screen path.
    change(0xfffffff006c86138,bytes.fromhex('e4020094'),
           struct.pack('<I',struct.unpack('<I',branch(0xfffffff006c86138,addrs['_ch2_printf']))[0]|0x80000000),
           'Use printf for the existing native provider message')
    old=b'CH1 AppleDisplayPMU::start: %s I2C=%p\n\0'
    new=b'\x1b[32mCH2 Chestnut provider=%s I2C=%p\x1b[0m\n\0'
    require(k.data.count(old)==1,'Provider marker differs')
    off=k.data.index(old)
    allocation=len(b'AppleDisplayPMU::start: %s _pmuIICNub: %p built 19:29:31 Oct  6 2022\n\0')
    require(len(new)<=allocation and k.data[off:off+allocation]==old.ljust(allocation,b'\0'),'Marker capacity differs')
    # Resolve the containing mapped VA without assuming raw file offset == VA.
    def va_for_offset(off):
        return next(s['addr']+off-k.base-s['offset'] for s in k.segments
                    if k.base+s['offset']<=off<k.base+s['offset']+s['size'])
    change(va_for_offset(off),k.data[off:off+allocation],new.ljust(allocation,b'\0'),'Green native provider marker')
    old=b'\x1b[31mH1:%.128s\x1b[0m\n\0\0'
    new=b'\x1b[32mCH2:%.128s\x1b[0m\n\0'
    require(len(old)==len(new) and k.data.count(old)==1,'Early version marker differs')
    off=k.data.index(old)
    change(va_for_offset(off),old,new,'Green CH2 early boot version marker')
    expected=bytes(result)
    delta={i for i,(a,b) in enumerate(zip(k.data,expected)) if a!=b}
    allowed={r['offset']+i for r in records for i in range(len(bytes.fromhex(r['old'])))}
    require(delta<=allowed,'Unlisted modification')
    (work / 'trace.flat').write_bytes(flat)
    return expected, {'helper_va': hex(CAVE), 'helper_size': len(flat), 'helper_symbols': {n: hex(v) for n,v in addrs.items()}, 'imports': {n: hex(a) for n,(a,_) in imports.items()}, 'edits': records}
