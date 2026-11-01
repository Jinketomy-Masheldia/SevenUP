"""Import Homer HID consumers with native16 parent tables and typed layouts."""

import struct
from .core import load_json
from .kc import KC
from .kernel_chestnut import relocations, encode_adrp, adrp_page
from .kernel_transplant import fast_symbols, apply as transplant
from .kernel_uart import views
from .kernel_compile import imported_c

N='com.apple.driver.AppleHomerDriver'
OLD='com.apple.driver.AppleALSColorSensor'

def apply(source,donor,project,work):
 k,d=KC(source),KC(donor)
 O=work
 assert not any(OLD in e.get('OSBundleLibraries',{})for e in k.kexts.values())
 review=load_json(project.root/'profiles/homer-consumer.json')
 private={int(a,16):int(b,16)for a,b in review['private_bindings'].items()}
 classes=load_json(project.root/'profiles/homer-uart-abi.json')['classes15']
 native=load_json(project.root/'profiles/homer-uart-abi.json')['classes16']
 def compile_blob(address,source,imports,folder,entry):
  return imported_c(project,address,source,imports,folder,entry)
 skip=set();cursor=(next(s for s in d.ksegments(N)if s['name']=='__DATA_CONST')['size']+15)&~15;plans=[]
 for row in review['tables']:
  point=int(row['old_vtable'],16);skip.update(range(point-16,point+217*8,8))
  plans.append(dict(**row,new_offset=cursor));cursor+=32+218*8
 sy,_=fast_symbols(k);base,fix=relocations(d);extra={}
 def finish(k,d,out,local,dst,tail,write):
  newslides=[];tables={};records=[]
  parent=native['IOHIDEventService'];pv=int(parent['vtable'],16)+16
  values=list(struct.unpack('<218Q',k.read(pv,218*8)))
  for p in plans:
   name=p['name'];c=classes[name];oldpoint=int(p['old_vtable'],16);a=dst['__DATA_CONST']+p['new_offset'];v=list(values)
   for r in p['overrides']:v[r['slot']]=local(int(r['target'],16))
   words=[local(int(c['metaclass'],16)),int(parent['metaclass'],16),0,0]+v
   write(a,struct.pack('<'+'Q'*len(words),*words));newslides.extend(a+i*8 for i,x in enumerate(words)if x)
   # Preserve old vptr-32 metadata aliases; only discard old header/functions.
   write(local(oldpoint-16),bytes(16+217*8));tables[oldpoint]=a+32
   assert local(int(c['metaclass'],16))is not None
   records.append(dict(class_name=name,old_vtable=hex(oldpoint),new_vtable=hex(a+32),size=p['size'],overrides=p['overrides']))
  rewritten=[]
  code=next(s for s in d.ksegments(N)if s['name']=='__TEXT_EXEC')
  for off in range(0,code['size']-4,4):
   pc=code['addr']+off;w,v=struct.unpack('<II',d.read(pc,8));reg=w&31
   if w&0x9f000000!=0x90000000 or v&0xffc003ff!=0x91000000|(reg<<5)|reg:continue
   point=adrp_page(w,pc)+((v>>10)&4095)
   if point not in tables:continue
   at=local(pc);to=tables[point]
   write(at,struct.pack('<II',encode_adrp(w,at,to&~4095),(v&~(4095<<10))|((to&4095)<<10)))
   rewritten.append(dict(source=hex(pc),address=hex(at),target=hex(to)))
  assert all(any(int(x['target'],16)==a for x in rewritten)for a in tables.values())
  for off in fix:
   a=base+off;at=local(a)
   if at is None or a in skip:continue
   v=struct.unpack('<Q',d.read(a,8))[0]
   if v in tables:write(at,struct.pack('<Q',tables[v]))
  # Preserve typed allocation prefix shape even when parent size is unchanged.
  dv=views(d,N);dp=views(d,'com.apple.iokit.IOHIDFamily');np=views(k,'com.apple.iokit.IOHIDFamily')
  _,oldp,size=dp['IOHIDEventService'];_,newp,nsize=np['IOHIDEventService'];assert size==nsize==200
  pool=dst['__TEXT']+0x1000;types=[]
  for p in plans:
   a,sig,size=dv[p['name']];assert sig.startswith(oldp)
   new=newp+sig[len(oldp):];assert len(new)*8==size==p['size']
   write(pool,new+b'\0');write(local(a)+32,struct.pack('<Q',pool))
   types.append(dict(class_name=p['name'],view=hex(local(a)),signature=hex(pool),text=new.decode(),size=size));pool+=len(new)+1
  assert pool<dst['__TEXT']+0x2000
  hooks={}
  for p in records:
   name='home'if p['class_name']=='AppleHomerDriver'else 'temperature';vt=int(p['new_vtable'],16)
   for which,slot in [('start',168),('stop',169)]:
    a=vt+slot*8;hooks[name+'_'+which]=dict(slot=a,original=struct.unpack_from('<Q',out,k.offset(a))[0])
  init=next(t for s in d.ksegments(N)for t in s['sections']if t['name']=='__mod_init_func')
  original_init=local(struct.unpack('<Q',d.read(init['addr']+8,8))[0])
  source='typedef unsigned long U;\nextern int hc1_printf(const char*,...);\n#define ARGS U a,U b,U c,U d,U e,U f,U g,U h\n#define PASS a,b,c,d,e,f,g,h\n'
  for name in hooks:
   source+=f'extern U hc1_orig_{name}(ARGS);\nU hc1_{name}(ARGS){{hc1_printf("\\033[36mHC1 {name} begin\\033[0m\\n");U v=hc1_orig_{name}(PASS);hc1_printf("\\033[36mHC1 {name} end=%lx\\033[0m\\n",v);return v;}}\n'
  source+='extern void hc1_orig_init(void);void hc1_init(void){hc1_orig_init();hc1_printf("\\033[36mHC1 Homer event classes ready\\033[0m\\n");}\n'
  (O/'trace.c').write_text(source);imports={'_hc1_printf':sy['_printf'],'_hc1_orig_init':original_init,**{'_hc1_orig_'+n:r['original']for n,r in hooks.items()}}
  tail=(tail+15)&~15;blob,trace=compile_blob(tail,O/'trace.c',imports,O/'trace','_hc1_init');write(tail,blob);tail=(tail+len(blob)+15)&~15
  for n,r in hooks.items():r['target']=int(trace['symbols']['_hc1_'+n],16);write(r['slot'],struct.pack('<Q',r['target']))
  write(local(init['addr']+8),struct.pack('<Q',int(trace['symbols']['_hc1_init'],16)))
  extra.update(tables=records,vptr_materializations=rewritten,typed_allocations=types,hooks=hooks,trace=trace)
  return tail,[dict(HC1=extra)],newslides
 raw,report=transplant(source,donor,work,OLD,N,b'\x1b[33mHCD:%.128s\x1b[0m\n\0',b'\x1b[33mHMD:%.128s\x1b[0m\n\0',private_bindings=private,private_review=review,finalize=finish,skip_donor_slots=skip,expanded_segments={'__DATA_CONST':cursor})
 return raw,{**report,'HC1':extra}
