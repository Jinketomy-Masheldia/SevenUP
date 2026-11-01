"""Native-parent UART/STMB class reconstruction with reviewed field changes."""

import struct
from .core import load_json
from .kernel_chestnut import relocations, adrp_page, encode_adrp
from .kernel_transplant import fast_symbols
from .kernel_maggie import adr, bl
from .kernel_base import branch
from .kernel_abi import load_plan

N='com.apple.driver.AppleHIDTransportUART'
PAIRS=[('AppleHIDTransportProtocolUART','AppleHIDTransportProtocol'),('AppleHIDTransportDeviceUART','AppleHIDTransportDevice'),('AppleHIDTransportBootloaderSTMB','AppleHIDTransportBootloader')]

def prepare(d,k,profile):
 plan_data=load_json(profile)
 old,new=plan_data['classes15'],plan_data['classes16']
 candidates=plan_data
 comparisons=plan_data['comparisons']
 private={int(a,16):int(v['target'],16)for a,v in candidates['bindings'].items()}
 for n,r in old.items():
  if n in new:private[int(r['metaclass'],16)]=int(new[n]['metaclass'],16)
 # Named XML keys used by the STMB loader. Pin both name and array position;
 # unlike a function-address guess, a key-pointer cell is verified by its string.
 keys={0xfffffff006de4330:0xfffffff006dc8e08,0xfffffff006de4340:0xfffffff006dc8e18,
       0xfffffff006de4348:0xfffffff006dc8e20,0xfffffff006de4358:0xfffffff006dc8e30,
       0xfffffff006de4360:0xfffffff006dc8e38,0xfffffff006de43e0:0xfffffff006dc8ec0,
       0xfffffff006de4ce8:0xfffffff006dc9818}
 keyreview=[]
 for a,b in keys.items():
  x=struct.unpack('<Q',d.read(a,8))[0];y=struct.unpack('<Q',k.read(b,8))[0]
  left=d.read(x,100).split(b'\0')[0];right=k.read(y,100).split(b'\0')[0];assert left==right and left
  private[a]=b;keyreview.append(dict(old=hex(a),new=hex(b),key=left.decode()))
 # Entire native parent vtables are retained, including the new virtual methods.
 maps={};tables=[];skip=set();src_tables={}
 cursor=(next(s for s in d.ksegments(N)if s['name']=='__DATA_CONST')['size']+15)&~15
 for child,parent in PAIRS:
  o,n=old[parent],new[parent]
  row=next(r for r in comparisons if r['old']==o['vtable'] and r['new']==n['vtable'])
  mapping={int(a):b for a,b in row['slot_correspondence'].items()}
  if child=='AppleHIDTransportDeviceUART':
   expected={i:i if i<186 else i+1 if i<190 else i+2 for i in range(218)}
   assert mapping==expected and o['instance_size']==n['instance_size']==248
  elif child=='AppleHIDTransportProtocolUART':
   assert mapping=={i:i for i in range(208)} and o['instance_size']==n['instance_size']==224
  else:
   assert o['instance_size']==288 and n['instance_size']==296
   assert set(mapping)==set(range(228))-{201}
   assert mapping[168]==168 and mapping[179]==180 and mapping[225]==230
  cv=old[child];head=int(cv['vtable'],16);point=head+16
  prefix=struct.unpack('<'+'Q'*o['virtual_slots'],d.read(int(o['vtable'],16)+16,o['virtual_slots']*8))
  ov=struct.unpack('<'+'Q'*cv['virtual_slots'],d.read(point,cv['virtual_slots']*8))
  nv=[dict(kind='native',target=x)for x in struct.unpack('<'+'Q'*n['virtual_slots'],k.read(int(n['vtable'],16)+16,n['virtual_slots']*8))]
  overrides=[]
  for i,fn in enumerate(ov):
   if i>=o['virtual_slots']:
    j=n['virtual_slots']+i-o['virtual_slots'];mapping[i]=j;nv.append(dict(kind='local',target=fn))
   elif fn!=prefix[i]:
    assert i in mapping; j=mapping[i]
    assert any(s['addr']<=fn<s['addr']+s['size']for s in d.ksegments(N)if s['name']=='__TEXT_EXEC')
    nv[j]=dict(kind='local',target=fn);overrides.append(dict(old=i,new=j,target=hex(fn)))
  assert len(nv)==cv['virtual_slots']+n['virtual_slots']-o['virtual_slots']
  assert struct.unpack('<QQ',d.read(head-16,16))==(int(cv['metaclass'],16),int(cv['super_metaclass'],16))
  assert d.read(head,16)==bytes(16)
  skip.update(range(head-16,point+8*cv['virtual_slots'],8))
  maps[child]=mapping;maps[parent]={i:j for i,j in mapping.items()if i<o['virtual_slots']}
  src_tables[point]=cursor+32
  tables.append(dict(child=child,parent=parent,head=head,point=point,dest_offset=cursor,
                     entries=nv,overrides=overrides,old_slots=cv['virtual_slots'],new_slots=len(nv)))
  cursor=(cursor+32+8*len(nv)+15)&~15
 # Only the interface-ID getter is invoked by the legacy UART protocol.
 iface=next(r for r in comparisons if r['old']==old['AppleHIDTransportInterface']['vtable'] and r['new']==new['AppleHIDTransportInterface']['vtable'])
 maps['AppleHIDTransportInterface']={int(i):j for i,j in iface['slot_correspondence'].items()}
 assert maps['AppleHIDTransportInterface'][195]==194
 patches,pairs=load_plan(d,profile)
 pairpatch=[dict(pc=r['va'],word=r['old'],base=r['base_register'],delta=r['delta'],instruction=r['reason']) for r in pairs]
 sizepatch=[r['address'] for r in plan_data['instruction_fields'] if r['reason']=='STMB allocation/metadata size 368 -> 376']
 assert len(sizepatch)==5
 # Confirm every surviving external pointer has a concrete native target.
 db,dr=relocations(d);kn,ka=fast_symbols(k);dn,da=fast_symbols(d);required=set()
 for off in dr:
  a=db+off
  if a in skip or not any(s['addr']<=a<s['addr']+s['size']for s in d.ksegments(N)):continue
  v=struct.unpack('<Q',d.read(a,8))[0]
  if any(s['addr']<=v<s['addr']+s['size']for s in d.ksegments(N)) or any(n in kn for n in da.get(v,[])):continue
  assert v in private,hex(v);required.add(v)
 private={a:private[a]for a in required}
 def finish(k,d,out,local,dst,tail,write):
  records=[];newrel=[];const=dst['__DATA_CONST'];retarget={point:const+off for point,off in src_tables.items()}
  for t in tables:
   base=const+t['dest_offset'];child=old[t['child']];parent=new[t['parent']]
   words=[local(int(child['metaclass'],16)),int(parent['metaclass'],16),0,0]
   words += [local(e['target'])if e['kind']=='local'else e['target']for e in t['entries']]
   assert all(x is not None for x in words)
   write(base,struct.pack('<'+'Q'*len(words),*words));newrel.extend(base+8*i for i,x in enumerate(words)if x)
   # Dead old primary tables are cleared; secondary thunks and all other const data survive.
   write(local(t['head']-16),bytes(32+8*t['old_slots']))
   records.append(dict(new_vtable=hex(base+32),class_name=t['child'],old_vtable=hex(t['point']),old_slots=t['old_slots'],new_slots=t['new_slots'],native_parent=t['parent']))
  pointer_updates=[]
  for off in dr:
   a=db+off;dest=local(a)
   if dest is None or a in skip:continue
   v=struct.unpack('<Q',d.read(a,8))[0]
   if v in retarget:write(dest,struct.pack('<Q',retarget[v]));pointer_updates.append(hex(dest))
  # Constructors/destructors materialize a full vptr using adjacent ADRP+ADD.
  # Rewrite the complete pair; existing generated ADRP veneers become harmless dead code.
  code=next(s for s in d.ksegments(N)if s['name']=='__TEXT_EXEC');raw=d.read(code['addr'],code['size']);pair_updates=[]
  for i in range(0,len(raw)-4,4):
   a=code['addr']+i;w,v=struct.unpack_from('<II',raw,i);reg=w&31
   if w&0x9f000000!=0x90000000 or v&0xffc003ff!=0x91000000|(reg<<5)|reg:continue
   target=adrp_page(w,a)+((v>>10)&4095)
   if target not in retarget:continue
   dest=local(a);to=retarget[target]
   write(dest,struct.pack('<II',encode_adrp(w,dest,to&~4095),(v&~(4095<<10))|((to&4095)<<10)))
   pair_updates.append(dict(source=hex(a),destination=hex(dest),target=hex(to)))
  assert len(pair_updates)>=9,len(pair_updates)
  records.append(dict(vptr_materializations=pair_updates,retargeted_data_pointers=pointer_updates))
  for p in pairpatch:
   pc=local(p['pc']);reg=p['base'];delta=p['delta'];assert delta==8
   body=struct.pack('<III',0x91000000|(delta<<10)|(reg<<5)|reg,p['word'],0xd1000000|(delta<<10)|(reg<<5)|reg)+branch(tail+12,pc+4)
   write(tail,body);write(pc,branch(pc,tail));records.append(dict(source=hex(p['pc']),veneer=hex(tail),reason='Unaligned shifted STMB vector access',instruction=p['instruction']));tail+=16
  # A visible yellow marker calls the original STMB initializer, then logs readiness.
  mark=(tail+15)&~15
  init=next(q for s in d.ksegments(N)for q in s['sections']if q['name']=='__mod_init_func')
  orig=struct.unpack('<Q',d.read(init['addr']+16,8))[0]
  msg=b'\x1b[33mHU1 Homer UART classes ready\x1b[0m\n\0'
  data=struct.pack('<II',0xa9bf7bfd,0x910003fd)+bl(mark+8,local(orig))+struct.pack('<I',adr(mark+12,mark+28,0))+bl(mark+16,kn['_IOLog'])+struct.pack('<II',0xa8c17bfd,0xd65f03c0)+msg
  write(mark,data);write(local(init['addr']+16),struct.pack('<Q',mark))
  records.append(dict(initializer_marker=hex(mark),initializer_original=hex(local(orig))))
  return (mark+len(data)+15)&~15,records,newrel
 report=dict(status='ABI PLAN; HARDWARE UNTESTED',required_native_bindings=len(required),native_parent_reconstruction=True,
  object_sizes={'UART':[520,520],'ProtocolUART':[416,416],'BootloaderSTMB':[368,376]},
  missing_native_interface_direct_accesses=0,interface_id_virtual_getter=[195,194],
  primary_tables=[dict(class_name=t['child'],old=t['old_slots'],new=t['new_slots'],overrides=t['overrides'])for t in tables],
  XML_keys=keyreview,size_instruction_sites=sizepatch,patch_count=len(patches),unaligned_vector_adapters=len(pairpatch),
  skipped_obsolete_primary_vtable_slots=len(skip),extra_const_bytes=cursor-7072)
 return private,report,patches,finish,skip,{'__DATA_CONST':cursor}
