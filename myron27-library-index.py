#!/usr/bin/env python3
"""Export a bounded static symbol index from the pinned original SystemOS.

No device addresses or user captures are inputs. Original images stay private.
The index is reusable for offline attribution without recompiling the kernel.
"""
import argparse,importlib.util,json,os,shutil,subprocess,sys,tomllib
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
MAX_BYTES=16*1024*1024
def load(name):
 spec=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/(name+'.py'))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def selected(path):
 return path.startswith('/usr/lib/system/') or path in (
  '/usr/lib/libobjc.A.dylib', '/usr/lib/libc++abi.dylib',
  '/usr/lib/libc++.1.dylib', '/usr/lib/libSystem.B.dylib',
  '/System/Library/Frameworks/Foundation.framework/Foundation',
  '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
def write_index(cache,path):
 result=dict(format=1,target='iPhone12,1/27.0.1/24A446',runtime_observation=False,
  region_start=hex(cache.region_start),max_slide=hex(cache.max_slide),images=cache.images,selected=[])
 for image in cache.images:
  if not selected(image['path']):continue
  meta=cache.macho(image);symbols=[];seen=set()
  for address,name,source in cache.symbols(image,strict=False):
   if name in ('<redacted>','') or (address,name) in seen:continue
   seen.add((address,name));symbols.append((address,name,source))
  row=dict(path=image['path'],uuid=image['uuid'],address=hex(image['address']),size=image['size'],
   starts=meta['starts'],symbols=symbols,warnings=meta.get('symbol_warnings',[]))
  # One named ABI compatibility query, independent of any device observation.
  targets=[address for address,name,_ in symbols if name.lstrip('_')=='os_lockdown_mode_enabled']
  row['lockdown_query']=[cache.describe(address,128) for address in sorted(set(targets))]
  result['selected'].append(row)
 encoded=json.dumps(result,separators=(',',':')).encode()
 if len(encoded)>MAX_BYTES:raise ValueError(f'Symbol index {len(encoded)} bytes exceeds {MAX_BYTES} byte limit')
 Path(path).write_bytes(encoded)
 return dict(images=len(result['images']),indexed=len(result['selected']),bytes=len(encoded))
# Static attribution for the first-frame path in the pinned iPhone system image.
# Keep this separate from the capped general index and emit no original code.
def setup_method_flow(cache, image, decoder, names, start, end, string_limit=110):
    """Branch destinations and referenced selectors/configuration keys, without image bytes."""
    import struct
    from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM
    def refer(address):
        try:
            data = cache.read(address, max(24,string_limit+1))[0]
        except (ValueError, RuntimeError):
            return None
        for indirect in [None, 0, 16]:
            if indirect is None:
                texts = [data]
            else:
                pointer = struct.unpack_from('<Q', data, indirect)[0]
                if not pointer:
                    continue
                texts = []
                for va in [pointer, cache.region_start+(pointer & 0x3ffffffff)]:
                    try:
                        texts.append(cache.read(va,string_limit+1)[0])
                    except (ValueError, RuntimeError):
                        pass
            for value in texts:
                key, sep, _ = value.partition(bytes(1))
                if sep and 3 <= len(key) <= string_limit and all(32 <= b < 127 for b in key):
                    return key.decode()
    def references(instructions):
        pages = {}
        for op in instructions:
            operands = op.operands
            if op.mnemonic == 'adrp':
                pages[operands[0].reg] = operands[1].imm
            elif op.mnemonic == 'add' and len(operands)==3 and operands[2].type==ARM64_OP_IMM and operands[1].reg in pages:
                yield op.address, refer(pages[operands[1].reg]+operands[2].imm)
            elif op.mnemonic == 'adr':
                yield op.address, refer(operands[1].imm)
            elif op.mnemonic == 'ldr' and operands[1].type==ARM64_OP_MEM and operands[1].mem.base in pages:
                yield op.address, refer(pages[operands[1].mem.base]+operands[1].mem.disp)
    ops = list(decoder.disasm(cache.read(start, min(end-start,2048), executable=True)[0], start))
    events = {addr:key for addr,key in references(ops) if key}
    for op in ops:
        if not op.operands or op.operands[-1].type != ARM64_OP_IMM:
            continue
        target = op.operands[-1].imm
        if op.mnemonic in ('b','bl') and not start <= target < end:
            labels = set(names.get(target,()))
            try:
                stub = list(decoder.disasm(cache.read(target,24,executable=True)[0], target))
                if stub and stub[0].mnemonic=='adrp' and stub[0].reg_name(stub[0].operands[0].reg)=='x1':
                    labels.update(v for _,v in references(stub[:3]) if v)
            except (ValueError, RuntimeError):
                pass
            if not labels and any('iscommcentersupported' in n.lower() for n in names.get(start,())):
                try:
                    insns=list(decoder.disasm(cache.read(target,12,executable=True)[0],target))
                    dest=insns[0].operands[0].imm if insns and insns[0].mnemonic=='b' else target
                    img=cache.image_for(dest)
                    if img and img['uuid']!=image['uuid']:
                        sym=cache.symbol_for(dest,img,strict=False)
                        if sym and sym.get('address')==hex(dest) and sym.get('name'):labels.add(sym['name'])
                except (ValueError, RuntimeError):
                    pass
            events[op.address] = 'call '+(', '.join(sorted(labels)) or hex(target))
        elif op.mnemonic in ('cbz','cbnz','tbz','tbnz','b') or op.mnemonic.startswith('b.'):
            events[op.address] = op.mnemonic+' -> '+hex(target-start)
    if any('iscommcentersupported' in n.lower() for n in names.get(start,())):
        for op in ops:
            if op.mnemonic in ('mov','movz','ret','tst','cmp','cset','and','orr','eor'):
                events.setdefault(op.address,op.mnemonic+' '+op.op_str)
    return [(hex(addr-start), events[addr]) for addr in sorted(events)]


def write_setup_queries(cache, path):
    """Resolve 24A446 Setup call sites, retaining names and offsets only."""
    from bisect import bisect_right
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    from capstone.arm64 import ARM64_OP_IMM
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    decoder.detail = True
    targets = {
        '94dfc60c765d3f20b8aa376bdb44b49b': (0x2394, 0x4cec, 0x14890, 0x40b8, 0x10c38),
        '2371d1a4791c3de7a866b202c590847b': (0x28160,),
        '80d108988f9034f0b37102f80621e835': (0x2b64, 0x2cf4, 0x2ebc),
    }
    images = {image['uuid']: image for image in cache.images}
    rows = []
    for uuid, offsets in targets.items():
        image = images[uuid]
        base = image['address']
        starts = cache.macho(image)['starts']
        names = {}
        for address, name, _ in cache.symbols(image, strict=False):
            if name and name != '<redacted>':
                names.setdefault(address, set()).add(name)
        if uuid=='94dfc60c765d3f20b8aa376bdb44b49b':
            # Record the native unsupported-service gate and its initializers.
            owners = [addr for addr, ns in names.items() if any(
                'iscommcentersupported' in n.lower() or 'setCommCenterSupported:' in n or
                ('CoreTelephonyClientMux ' in n and (' init' in n or 'shared' in n))
                for n in ns)]
            gate={addr for addr,ns in names.items() if any('iscommcentersupported' in n.lower() for n in ns)}
            active=set(gate)
            for depth in range(3):
                following=set()
                for addr in active:
                    idx=bisect_right(starts,addr)-1
                    if idx<0 or idx+1>=len(starts) or starts[idx]!=addr:continue
                    ops=decoder.disasm(cache.read(addr,min(starts[idx+1]-addr,1024),executable=True)[0],addr)
                    for op in ops:
                        if op.mnemonic in ('bl','b') and op.operands[-1].type==ARM64_OP_IMM:
                            dst=op.operands[-1].imm
                            if dst in names and dst not in gate and any('CT' in n or 'upport' in n or 'ellular' in n for n in names[dst]):
                                following.add(dst)
                gate.update(following);active=following
                if len(gate)>40:raise ValueError('Unexpected support gate call graph')
            offsets = tuple(sorted(set(offsets)|{a-base+4 for a in set(owners)|gate if a in starts}))
        for offset in offsets:
            # Stacks hold return PCs. Attribute the preceding instruction.
            idx = bisect_right(starts, base+offset-4)-1
            if idx < 0 or idx+1 >= len(starts):
                raise ValueError('Setup site outside documented function boundaries')
            start, end = starts[idx:idx+2]
            calls = []
            code, _ = cache.read(start, min(end-start, 32768), executable=True)
            for op in decoder.disasm(code, start):
                if op.mnemonic in ('b', 'bl') and len(op.operands)==1 and op.operands[0].type==ARM64_OP_IMM:
                    target = op.operands[0].imm
                    if names.get(target):
                        calls.append(dict(site=hex(op.address-base), names=sorted(names[target])))
            rows.append(dict(image=image['path'], uuid=uuid, return_offset=hex(offset),
                             start=hex(start-base), names=sorted(names.get(start,())),
                             calls=calls[:128], flow=setup_method_flow(cache,image,decoder,names,start,end)))
    path.write_text(json.dumps(rows, indent=2)+'\n')
    for row in rows:
        print('Setup CT site', row['return_offset'], row['start'], row['names'], flush=True)


def write_compositor_sites(cache, path):
 from bisect import bisect_right
 from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
 from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_REG
 image=next(i for i in cache.images if i['path']=='/System/Library/Frameworks/QuartzCore.framework/QuartzCore')
 if image['uuid']!='76ce2a6edba4335da5ac77a1c1b286a6':
  raise ValueError('Unexpected compositor UUID')
 base=image['address']
 starts=cache.macho(image)['starts']
 if not starts:raise ValueError('Missing compositor function boundaries')
 names={}
 for addr,name,_ in cache.symbols(image,strict=False):
  if name and name!='<redacted>':names.setdefault(addr,set()).add(name)
 write_async_options(cache,image,starts,names,path.with_name("asynchronous-surface-options.json"))
 offsets=(0x2c3d14,0x2db7a8,0x2c8c2c,0x2d8004,0x2dc834,0x2ded50,0x2df2c4,
          0x2e3ae8,0x202ddc,0x2033d8,0x2e0a38,0xb0064,0xb8584,0xad51c,0xb3478,0xb8b4c,
          0x7d2a8,0x17e2dc,0xaafcc,0xaa818,0xabc18,0xab318)
 cs=Cs(CS_ARCH_ARM64,CS_MODE_ARM);cs.detail=True
 rows=[]
 for offset in offsets:
  ix=bisect_right(starts,base+offset)-1
  if ix<0 or ix+1>=len(starts):raise ValueError('Compositor site outside function index')
  start,end=starts[ix:ix+2]
  # Bound work on large routines, keeping the region containing the site.
  lo=max(start,base+offset-4096);hi=min(end,base+offset+4096)
  raw,_=cache.read(lo,hi-lo,executable=True)
  literals=set();calls=set();pages={}
  for ins in cs.disasm(raw,lo):
   ops=ins.operands
   if ins.mnemonic=='adrp' and len(ops)==2:
    pages[ops[0].reg]=(ops[1].imm,ins.address)
   elif ins.mnemonic=='add' and len(ops)==3 and ops[1].type==ARM64_OP_REG and ops[2].type==ARM64_OP_IMM:
    page=pages.get(ops[1].reg)
    if page and ins.address-page[1]<=12 and not ops[2].shift.value:
     try: b=cache.read(page[0]+ops[2].imm,128)[0].split(bytes(1),1)
     except ValueError: continue
     except RuntimeError: continue
     if len(b)==2 and 4<=len(b[0])<=100 and all(32<=x<127 for x in b[0]):literals.add(b[0].decode())
   elif ins.mnemonic=='bl' and len(ops)==1 and ops[0].type==ARM64_OP_IMM:
    calls.update(names.get(ops[0].imm,()))
  # The assertion caller is a return PC adjusted to the calling instruction.
  # Keep individual literal references near that call distinct from function-wide hints.
  near_call=[]
  if offset==0x7d2a8:
   literal_pages={}
   site=base+offset
   window=max(start,site-96)
   block=cache.read(window,site+4-window,executable=True)[0]
   for ins in cs.disasm(block,window):
    ops=ins.operands
    if ins.mnemonic=='adrp' and len(ops)==2:
     literal_pages[ops[0].reg]=ops[1].imm
    elif ins.mnemonic=='add' and len(ops)==3 and ops[1].type==ARM64_OP_REG and ops[2].type==ARM64_OP_IMM:
     page=literal_pages.get(ops[1].reg)
     if page is None or ops[2].shift.value:continue
     try: value=cache.read(page+ops[2].imm,512)[0].split(bytes(1),1)
     except (ValueError,RuntimeError):continue
     if len(value)==2 and value[0] and all(32<=c<127 for c in value[0]):
      near_call.append(dict(at=hex(ins.address-base),register=ins.reg_name(ops[0].reg),literal=value[0].decode()))
    elif ins.mnemonic=='mov' and len(ops)==2 and ins.reg_name(ops[0].reg)=='w2' and ops[1].type==ARM64_OP_IMM:
     near_call.append(dict(at=hex(ins.address-base),register='w2',immediate=ops[1].imm))
  rows.append(dict(offset=hex(offset),function=hex(start-base),exact_names=sorted(names.get(start,())),
                   near_call=near_call,named_calls=sorted(calls)[:40],possible_literals=sorted(literals)[:40]))
 Path(path).write_text(json.dumps(dict(uuid=image['uuid'],sites=rows),indent=2)+'\n')

def write_async_options(cache, image, starts, names, path):
 """Identify configuration names and callers related to asynchronous surfaces in the pinned library."""
 import re
 import struct
 from bisect import bisect_right
 from collections import defaultdict
 base=image['address']
 raw=cache.read(base,image['size'])[0]
 key_pattern=rb'(?:CA[A-Z_][A-Za-z0-9_]{3,100}|[a-z][a-z_]{5,90})'
 keys={}
 for match in re.finditer(rb'(?<![ -~])('+key_pattern+rb')\x00',raw):
  key=match[1].decode()
  if 'async' in key.lower():
   keys[base+match.start(1)]=key
 # Some configuration names are reached through a CFString or a pointer
 # table. Keep indirect candidates separate from direct string references.
 direct=keys.copy()
 slots={}
 for seg in cache.macho(image)['segments']:
  if not seg['name'].startswith(('__DATA','__AUTH')) or not seg['file_bytes']:continue
  data=cache.read(seg['address'],seg['file_bytes'])[0]
  for off in range(0,len(data)-7,8):
   value=struct.unpack_from('<Q',data,off)[0]
   if not value:continue
   for address in (value,cache.region_start+(value&0x3ffffffff)):
    if address in direct:
     slot=seg['address']+off; slots[slot]=direct[address]
     if off>=16 and off+16<=len(data) and struct.unpack_from('<Q',data,off+8)[0]==len(direct[address]):
      keys[slot-16]='CFString: '+direct[address]
     break
 keys.update((a,'pointer slot: '+v) for a,v in slots.items())
 refs=defaultdict(list)
 calls=defaultdict(set)
 for i,(lo,hi) in enumerate(zip(starts,starts[1:])):
  if not base<=lo<hi<=base+len(raw):continue
  pages={}
  for pc in range(lo,hi,4):
   op=struct.unpack_from('<I',raw,pc-base)[0]
   if op&0x9f000000==0x90000000: # ADRP
    imm=((op>>29)&3)|(((op>>5)&0x7ffff)<<2)
    if imm&0x100000:imm-=0x200000
    pages[op&31]=((pc&~4095)+(imm<<12),pc)
   elif op&0x9f000000==0x10000000: # ADR
    imm=((op>>29)&3)|(((op>>5)&0x7ffff)<<2)
    if imm&0x100000:imm-=0x200000
    if pc+imm in keys:refs[lo].append((pc,keys[pc+imm]))
   elif op&0xffc00000==0xf9400000: # LDR Xt,[Xn,#imm]
    item=pages.get((op>>5)&31)
    if item and pc-item[1]<=64:
     address=item[0]+8*((op>>10)&4095)
     if address in keys:refs[lo].append((pc,keys[address]))
   elif op&0xffc00000==0x91000000: # ADD Xd,Xn,#imm12
    item=pages.get((op>>5)&31)
    if item and pc-item[1]<=48:
     address=item[0]+((op>>10)&4095)
     if address in keys:refs[lo].append((pc,keys[address]))
   elif op&0xfc000000 in (0x94000000,0x14000000):
    offs=op&0x3ffffff
    if offs&0x2000000:offs-=0x4000000
    dest=pc+4*offs
    if dest!=lo and dest in names:calls[lo].add(dest)
 def node(a):
  return sorted(names.get(a,())) or [hex(a-base)]
 def async_lifecycle(a):
  return any(any(q in n for q in ('AsynchronousItem','AsynchronousNode','AsynchronousState')) for n in names.get(a,()))
 seed=set(refs)|{a for a in names if async_lifecycle(a) or a-base==0x61f98}
 result=[]
 for lo in sorted(seed|{a for a,v in calls.items() if v&seed}):
  relevant=(calls[lo] if lo in seed else calls[lo]&seed)
  result.append(dict(function=node(lo),offset=hex(lo-base),references=[(hex(p-base),s) for p,s in refs[lo]],
                     calls=[n for a in sorted(relevant) for n in node(a)][:160]))
 # Keep named calls and conditionals in the one routine that constructs
 # the asynchronous state. For references to global bytes, identify writers.
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
 from capstone.arm64 import ARM64_OP_MEM,ARM64_OP_REG,ARM64_OP_IMM
 cs=Cs(CS_ARCH_ARM64,CS_MODE_ARM);cs.detail=True
 host=base+0x61f98; end=starts[bisect_right(starts,host)]
 pages={};uses={};events=[]
 for op in cs.disasm(cache.read(host,end-host,executable=True)[0],host):
  os_=op.operands; detail=None
  if op.mnemonic=='adrp':pages[os_[0].reg]=os_[1].imm
  elif op.mnemonic.startswith('ldr') and len(os_)>1 and os_[1].type==ARM64_OP_MEM and os_[1].mem.base in pages:
   target=pages[os_[1].mem.base]+os_[1].mem.disp; uses[target]=[];detail='global '+hex(target)
  elif op.mnemonic=='bl' and os_[0].type==ARM64_OP_IMM:detail='call '+','.join(node(os_[0].imm))
  elif op.mnemonic in ('tbz','tbnz','cbz','cbnz') or op.mnemonic.startswith('b.'):detail=op.mnemonic+' '+op.op_str
  if detail:events.append([hex(op.address-base),detail])
 for lo,hi in zip(starts,starts[1:]):
  if not base<=lo<hi<=base+len(raw):continue
  pages={}
  for pc in range(lo,hi,4):
   op=struct.unpack_from('<I',raw,pc-base)[0]
   if op&0x9f000000==0x90000000:
    imm=((op>>29)&3)|(((op>>5)&0x7ffff)<<2)
    pages[op&31]=((pc&~4095)+((imm-(0x200000 if imm&0x100000 else 0))<<12),pc)
   elif op&0x3fc00000==0x39000000: # STR unsigned immediate
    item=pages.get((op>>5)&31)
    if item and pc-item[1]<=96:
     target=item[0]+(((op>>10)&4095)<<(op>>30))
     if target in uses and len(uses[target])<16:
      uses[target].append([hex(pc-base),node(lo),refs.get(lo,[])])
 path.with_name('hosted-context-options.json').write_text(json.dumps(dict(events=events,possible_writers={hex(k):v for k,v in uses.items()}),indent=2)+'\n')
 path.write_text(json.dumps(dict(uuid=image['uuid'],possible_keys=sorted(set(direct.values())),indirect_slots={hex(a):v for a,v in slots.items()},functions=result),indent=2)+'\n')

def write_posterboard_queries(cache, path):
 """Bounded static attribution for the repeated 24A446 wallpaper trap."""
 from bisect import bisect_right
 from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
 install='/System/Library/PrivateFrameworks/PosterBoard.framework/PosterBoard'
 expected='2ce463af35a63164ac6cb7a007e81d10'
 images=[row for row in cache.images if row['path']==install]
 if len(images)!=1 or images[0]['uuid']!=expected:raise ValueError('PosterBoard source UUID differs')
 image=images[0];base=image['address'];starts=cache.macho(image)['starts'];names={}
 for address,name,_ in cache.symbols(image,strict=False):
  if name and name!='<redacted>':names.setdefault(address,set()).add(name)
 decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);decoder.detail=True;rows=[]
 for offset in (0x266858,0x6be84,0x6a4b0):
  pc=base+offset;index=bisect_right(starts,pc)-1
  if index<0 or index+1>=len(starts) or not starts[index]<=pc<starts[index+1]:
   raise ValueError('PosterBoard target has no bounded function')
  # Include the initializer's earlier predicates and full bounded assertion
  # strings. A small PC window omitted the path into the cold assertion.
  start,end=starts[index:index+2];low=start;high=min(end,start+2048)
  rows.append(dict(image_offset=hex(offset),function_offset=hex(start-base),
   offset_in_function=hex(pc-start),exact_start_names=sorted(names.get(start,())),
   window_offset=hex(low-base),window_bytes=high-low,function_bytes=end-start,
   truncated=high<end,
   references=setup_method_flow(cache,image,decoder,names,low,high,string_limit=512)))
 Path(path).write_text(json.dumps(dict(target='iPhone12,1/27.0.1/24A446',
  image=install,uuid=expected,sites=rows,runtime_observation=False,
  raw_image_bytes_exported=False),indent=2)+'\n')
 context=load('myron_posterboard_context').collect(cache,image,starts,names,decoder,setup_method_flow)
 context.update(target='iPhone12,1/27.0.1/24A446',image=install,uuid=expected)
 encoded=json.dumps(context,indent=2)+'\n'
 if len(encoded.encode())>4*1024*1024:raise ValueError('PosterBoard context exceeds bound')
 Path(path).with_name('posterboard-context.json').write_text(encoded)


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ('device','upstream','work','output','archive-tool'):p.add_argument('--'+key,type=Path,required=True)
 a=p.parse_args();work=a.work.resolve();out=a.output.resolve()
 if sys.platform!='darwin' or os.geteuid()!=0:raise ValueError('Requires read-only macOS image inspection')
 if work.exists() or out.exists():raise ValueError('Require fresh directories')
 work.mkdir(parents=True,mode=0o700);out.mkdir(parents=True)
 extract=load('myron27-fault-extract');symbolicate=load('myron27-fault-symbolicate')
 sys.path[:0]=[str(a.device.resolve()),str(a.upstream.resolve()/'scripts')]
 import prepare_userland
 import prepare_data_volume as volume
 from unixnu.ipsw import Ipsw
 from unixnu import userdata
 require=extract.require
 require(subprocess.check_output(['git','-C',str(a.upstream),'rev-parse','HEAD'],text=True).strip()==extract.UPSTREAM,'Wrong helper revision')
 require(shutil.disk_usage(work).free>11*1024**3,'Insufficient temporary space')
 config=tomllib.loads((a.device/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1/profile.toml').read_text())
 source=Ipsw(SimpleNamespace(board=config,out_root=work),config['ipsw']['url'])
 try:
  prepare_userland.validate_manifest(source)
  require(source.info('Cryptex1,SystemOS')[:2]==extract.MEMBER,'Wrong source image')
  print('Downloading pinned original SystemOS; no kernel build',flush=True)
  encrypted=source.extract('Cryptex1,SystemOS')
  require(encrypted.stat().st_size==extract.MEMBER[1],'Truncated image')
 finally:
  source.zip.close();source.stream.close()
 dest=work/'decoded';dest.mkdir()
 decoded=subprocess.run([str(a.archive_tool),'fw','aea',str(encrypted),'--output',str(dest)],capture_output=True)
 require(decoded.returncode==0,'Image decode failed; private output withheld')
 image=volume.regular(dest/Path(extract.MEMBER[0]).with_suffix('').name)
 raw=extract.check_raw_image(image,userdata)
 print('PASS original raw volume identity; indexing libraries',flush=True)
 with volume.attached(image,work/'mount',True) as mounted:
  require(mounted['uuid']==extract.SYSTEMOS[0],'Wrong original volume UUID')
  with symbolicate.CacheSet(mounted['path']/'System/Library/Caches/com.apple.dyld') as cache:
   # Match pkd's install name against the actual read-only donor volume.
   install = '/System/Library/PrivateFrameworks/PlugInKitDaemon.framework/PlugInKitDaemon'
   donor = mounted['path'].resolve(strict=True)
   matches = []
   for directory, _, names in os.walk(donor, followlinks=False):
    if 'PlugInKitDaemon' not in names:
     continue
    path = Path(directory) / 'PlugInKitDaemon'
    item = {'path': '/' + str(path.relative_to(donor))}
    try:
     binary = path.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
     binary = None
    if binary and binary.is_relative_to(donor) and binary.is_file():
     item.update(bytes=binary.stat().st_size, sha256=extract.sha(binary))
     deps = subprocess.run(['/usr/bin/otool','-L',str(binary)], capture_output=True, text=True, check=True)
     item['dependencies'] = [line.strip().split(' (compatibility version')[0] for line in deps.stdout.splitlines() if line.startswith('\t')]
    matches.append(item)
   record = dict(install_name=install, volume_uuid=mounted['uuid'], files=matches,
                 cached_paths=[row['path'] for row in cache.images if 'PlugInKitDaemon' in row['path']])
   (out/'pluginkit-layout.json').write_text(json.dumps(record,indent=2)+'\n')
   print('PlugInKitDaemon donor lookup:', json.dumps(record), flush=True)
   write_setup_queries(cache,out/'setup-telephony-sites.json')
   summary=write_index(cache,out/'library-index.json')
   write_compositor_sites(cache,out/'compositor-sites.json')
   write_posterboard_queries(cache,out/'posterboard-sites.json')
 summary.update(result='passed',source_volume=raw,kernel_built=False,phone_accessed=False,
  original_files_modified=False,source_commit=os.environ.get('GITHUB_SHA','unknown'))
 (out/'index-report.json').write_text(json.dumps(summary,indent=2)+'\n')
 print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
