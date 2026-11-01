"""Mirror the XNU physical KCGEN traversal for allocator layout checks."""

import struct

def walk(k):
    pool=next(s for s in k.segments if s['name']=='__PRELINK_TEXT')
    cur=pool['addr'];end=cur+pool['size'];headers=[]
    owners={e['_PrelinkExecutableLoadAddr']:n for n,e in k.kexts.items()
            if e.get('_PrelinkExecutableLoadAddr')}
    while cur<end:
        magic=struct.unpack('<I',k.read(cur,4))[0]
        if magic not in (0xfeedfacf,0xcffaedfe):
            rest=k.read(cur,end-cur)
            terminator=dict(address=hex(cur),magic=hex(magic),
                remaining_bytes=end-cur,remaining_nonzero_bytes=sum(x!=0 for x in rest),
                kind='zero-padding-return' if magic==0 else 'bad-magic-panic')
            break
        count,cmdsize=struct.unpack('<II',k.read(cur+16,8))
        q=cur+32;size=0;split=False;types=[]
        special_kpi=(owners.get(cur) or '').startswith('com.apple.kpi.')
        for _ in range(count):
            if q>=end:break
            cmd,z=struct.unpack('<II',k.read(q,8))
            assert z>=8
            # Original pseudo-kpi images use a compact legacy header whose
            # count can extend into the next image. The target bounds its
            # loop by the whole pool, not sizeofcmds; mirror that behavior.
            if not special_kpi:
                assert q+z<=cur+32+cmdsize, ('bad load command',hex(q))
            if cmd==30:split=True
            if cmd==25:
                name=k.read(q+8,16).split(b'\0')[0]
                if name==b'__TEXT':size=struct.unpack('<Q',k.read(q+48,8))[0]
                if name==b'__DATA_CONST':
                    nsec=struct.unpack('<I',k.read(q+64,4))[0]
                    for j in range(nsec):
                        sec=q+72+80*j;sn=k.read(sec,16).split(b'\0')[0]
                        if sn in (b'__kalloc_type',b'__kalloc_var'):
                            a,s=struct.unpack('<QQ',k.read(sec+32,16))
                            unit=64 if sn==b'__kalloc_type' else 80
                            assert s%unit==0
                            types.append(dict(name=sn.decode(),address=hex(a),bytes=s,views=s//unit))
            q+=z
        if not special_kpi:assert q==cur+32+cmdsize
        assert not size or split, ('non-split image',hex(cur))
        step=((size or cmdsize)+63)&~63
        assert step>0
        headers.append(dict(address=hex(cur),owner=owners.get(cur),TEXT_filesize=size,
                            traversal_bytes=step,kalloc_sections=types))
        cur+=step
    else:
        terminator=dict(address=hex(cur),kind='end-of-pool')
    if cur<end:
        skipped=[dict(address=hex(a),owner=n) for a,n in sorted(owners.items()) if cur<=a<end]
    else:skipped=[]
    return dict(header_count=len(headers),headers=headers,terminator=terminator,
                unvisited_metadata_images=skipped,
                all_remaining_bytes_are_padding=terminator.get('remaining_nonzero_bytes',0)==0)
