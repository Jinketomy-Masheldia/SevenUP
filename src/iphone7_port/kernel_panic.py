"""Rebuild the retained MC1D panic formatter and bounded renderer from source."""

import struct
import hashlib
from .core import require
from .kc import KC
from .kernel_base import branch
from .kernel_chestnut import commands
from .kernel_compile import c_helper, assembly

HOOK=0xfffffff0071f56b4
CAVE=0xfffffff0078bb900
RENDER=0xfffffff0064bf000
STATE=0xfffffff0078ebc00
sha = lambda data: hashlib.sha256(data).hexdigest()

def apply(source, battery_source, project, work):
    k = KC(source)
    assert k.read(HOOK-4,8).hex()=='e00080524bad1894'
    assert k.read(0xfffffff0071f5790,20).hex()=='a93700f029dd40f9e82700a940f2ffb000e42591'
    assert k.read(STATE,1024)==bytes(1024)
    assets = project.root / 'resources/kernel'
    render_work = work / 'renderer-build'
    render_work.mkdir()
    render, symbols, base = c_helper(project, assets/'panic_overlay.c', assets/'panic_overlay.s', render_work, '_pd_hook', assembly_first=True, alignment=0x1000, hidden=True, allow_adrp=True)
    require(base % 4096 == RENDER % 4096 == 0 and len(render) == 2495, 'Panic renderer layout differs.')
    rebase = {n: RENDER+a-base for n,a in symbols.items() if base <= a < base+len(render)}
    for value,name in [(0x1111222233334444,'_pd_context'),(0x2222333344445555,'_pd_doprnt'),(0x3333444455556666,'_pd_nested_resume'),(0x4444555566667777,'_pd_save_resume')]:
        needle=struct.pack('<Q',value)
        require(render.count(needle)==1, 'Renderer anchor is not unique.')
        offset=render.index(needle)
        render[offset:offset+8]=struct.pack('<Q',rebase[name])
    require(render.count(b'K1 PANIC')==1, 'Renderer version label changed.')
    render=render.replace(b'K1 PANIC',b'MD PANIC')
    require(not any(k.read(RENDER,len(render))), 'Renderer allocation is occupied.')
    require(k.read(0xfffffff00730e614,8).hex()=='9830009018632791', 'Native console context changed.')
    require(k.read(0xfffffff0072152b8,16).hex()=='e40303aae30302aa210040f982000010', 'Native panic formatter changed.')
    panic_work=work/'panic-build'
    panic_work.mkdir()
    flat,sy,base=assembly(project,assets/'microphone_panic.s',panic_work,'_np_hook')
    ns={n:CAVE+a-base for n,a in sy.items() if base<=a<base+len(flat)}
    for value,name in [(0x7777777777777777,'_np_printf'),(0x8888888888888888,'_np_doprnt'),(0x9999999999999999,'_np_hook'),(0xaaaaaaaaaaaaaaaa,'_np_render')]:
        needle=struct.pack('<Q',value)
        require(flat.count(needle)==1, 'Panic formatter anchor is not unique.')
        off=flat.index(needle)
        flat[off:off+8]=struct.pack('<Q',ns[name])
    needle=struct.pack('<Q',0xbbbbbbbbbbbbbbbb)
    require(flat.count(needle)==1, 'Panic capture anchor is not unique.')
    off=flat.index(needle)
    flat[off:off+8]=struct.pack('<Q',rebase['_pd_capture'])
    assert CAVE+len(flat)<=0xfffffff0078bc000 and not any(k.read(CAVE,len(flat)))
    out=bytearray(k.data);edits=[]
    def edit(a,b,why):
        off=k.offset(a);before=bytes(out[off:off+len(b)]);out[off:off+len(b)]=b
        edits.append({'address':hex(a),'offset':off,'size':len(b),'old':before.hex(),'new_sha256':sha(b),'reason':why})
    edit(CAVE,flat,'Panic formatter and terminal hold, called before platform actions')
    edit(RENDER,render,'Bounded direct framebuffer fallback, invoked only after panic')
    edit(HOOK,struct.pack('<I',struct.unpack('<I',branch(HOOK,CAVE))[0]|0x80000000),'Redirect only panic action stage7')
    # Declare the renderer inside this codec's existing reclaimed executable
    # allocation. No segment start, outer header or other driver is moved.
    name='com.apple.driver.AppleCS42L71Audio';head=k.kexts[name]['_PrelinkExecutableLoadAddr']
    exe=next(s for s in k.ksegments(name) if s['name']=='__TEXT_EXEC')
    limit=KC(battery_source)
    oldseg=next(s for s in limit.ksegments('com.apple.driver.AppleANXDPTX') if s['name']=='__TEXT_EXEC')
    assert exe['addr']<=RENDER and RENDER+len(render)<=oldseg['addr']+oldseg['size']
    newsize=RENDER+len(render)-exe['addr']
    for cmd,q,size in commands(k,head):
        if cmd==25 and k.data[q+8:q+24].split(b'\0')[0]==b'__TEXT_EXEC':
            va=head+q-k.offset(head)
            edit(va+32,struct.pack('<Q',newsize),'Extend only codec executable span within its allocation')
            edit(va+48,struct.pack('<Q',newsize),'Matching executable filesize')
    marker=b'\x1b[33mMC1:%.128s\x1b[0m\n\0';assert k.data.count(marker)==1
    off=k.data.index(marker);seg=next(s for s in k.segments if k.base+s['offset']<=off<k.base+s['offset']+s['size'])
    edit(seg['addr']+off-k.base-seg['offset'],marker.replace(b'MC1:',b'MCD:'),'Distinguish diagnostic version in panic metadata')
    restored=bytearray(out)
    for e in edits:restored[e['offset']:e['offset']+e['size']]=k.data[e['offset']:e['offset']+e['size']]
    assert restored==k.data and len(out)==len(k.data)
    (work/'kernelcache.raw').write_bytes(out);(work/'panic.flat').write_bytes(flat);(work/'renderer.flat').write_bytes(render)
    return bytes(out), {'edits': edits, 'renderer_size': len(render), 'panic_size': len(flat), 'source_compiled': True}
