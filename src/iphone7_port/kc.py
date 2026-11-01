"""Legacy prelinked kernel reader; Apple XML IDREF support is required."""
import struct
import xml.etree.ElementTree as ET
import base64
from pathlib import Path

def plist(data):
    root=ET.fromstring(data.rstrip(b'\0'))
    ids={e.attrib['ID']:e for e in root.iter() if 'ID' in e.attrib}
    def val(e):
        if 'IDREF' in e.attrib:return val(ids[e.attrib['IDREF']])
        if e.tag=='dict':
            a=list(e);return {a[i].text:val(a[i+1]) for i in range(0,len(a),2)}
        if e.tag in ('array','set'):return [val(x) for x in e]
        if e.tag=='integer':return int(e.text or '0',16 if (e.text or '').startswith('0x') else 10)
        if e.tag=='data':return base64.b64decode(e.text or '')
        if e.tag=='true':return True
        if e.tag=='false':return False
        return e.text or ''
    return val(root)

def macho(b,base):
    assert b[base:base+4]==bytes.fromhex('cffaedfe')
    off=base+32;out=[]
    for _ in range(struct.unpack_from('<I',b,base+16)[0]):
        cmd,size=struct.unpack_from('<II',b,off)
        if cmd==25:
            name=b[off+8:off+24].split(b'\0')[0].decode()
            va,vs,fo,fs,mx,prot,ns,flags=struct.unpack_from('<QQQQiiII',b,off+24)
            sec=[]
            for j in range(ns):
                q=off+72+80*j;sn=b[q:q+16].split(b'\0')[0].decode()
                sa,ss,sf=struct.unpack_from('<QQI',b,q+32)
                sec.append(dict(name=sn,addr=sa,size=ss,offset=sf))
            out.append(dict(name=name,addr=va,size=fs,offset=fo,vmsize=vs,sections=sec))
        off+=size
    return out

class KC:
    def __init__(self,p):
        self.data=Path(p).read_bytes();self.base=0
        if self.data[:4]==bytes.fromhex('cafebabe'):self.base=struct.unpack_from('>I',self.data,16)[0]
        self.segments=macho(self.data,self.base)
        s=next(s for s in self.segments if s['name']=='__PRELINK_INFO')
        self.xml=self.data[self.base+s['offset']:self.base+s['offset']+s['size']].rstrip(b'\0')
        self.kexts={k['CFBundleIdentifier']:k for k in plist(self.xml)['_PrelinkInfoDictionary']}
    def offset(self,va):
        for s in self.segments:
            if s['addr']<=va<s['addr']+s['size']:return self.base+s['offset']+va-s['addr']
        raise ValueError(hex(va))
    def ksegments(self,n):
        va=self.kexts[n].get('_PrelinkExecutableLoadAddr')
        return macho(self.data,self.offset(va)) if va else []
    def read(self,va,size):
        o=self.offset(va);return self.data[o:o+size]
