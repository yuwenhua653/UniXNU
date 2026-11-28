#!/usr/bin/env python3
"""Read-only, bounded attribution of the November 17 launchd reboot stack.

The executable slide is not photographed. Enumerate page-aligned candidates
and report ambiguity; never apply the shared-cache slide to launchd.
"""
import argparse
from bisect import bisect_right
import hashlib
import importlib.util
import itertools
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tomllib
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
# Alternatives preserve uncertain photographed glyphs instead of choosing a fit.
FRAMES=((0x10062429c,0x10062423c),(0x100624280,),
        (0x1006240e8,0x1006240a8),(0x100624080,),
        (0x1006631ec,),(0x10063c59c,),(0x10065af80,))
MAX_REPORT=8*1024*1024

def require(ok,why):
    if not ok:raise ValueError(why)

def take(data,offset,size):
    require(0<=offset<=len(data) and 0<=size<=len(data)-offset,'Range outside executable')
    return data[offset:offset+size]

def unpack(fmt,data,offset=0):
    return struct.unpack(fmt,take(data,offset,struct.calcsize(fmt)))

def signed(value,bits):
    return value-(1<<bits) if value&(1<<(bits-1)) else value

class Executable:
    def __init__(self,data,info):
        self.data=data;self.sections=[];self.symbols=[];self.stubs={};self.starts=[]
        limit=max(d['code_limit'] for d in info['code_directories'] if d['original_trust_match'])
        self.limit=limit
        magic,cpu,sub,kind,count,size,_,_=unpack('<8I',data)
        require(magic==0xfeedfacf and cpu==0x100000c and sub&0xffffff==2 and kind==2,'Not arm64e executable')
        require(0<count<=4096 and 32+size<=limit<=len(data),'Invalid command range')
        pos=32;starts=None;symtab=None;indirect=None;self.uuid=None;base=None
        for _ in range(count):
            cmd,length=unpack('<2I',data,pos)
            require(length>=8 and length%8==0 and pos+length<=32+size,'Invalid load command')
            if cmd==0x19:
                name,va,vs,off,fs,mp,prot,n,flags=unpack('<16s4Q4I',data,pos+8)
                require(length==72+80*n and fs<=vs,'Invalid segment')
                if name.rstrip(b'\0')==b'__TEXT':
                    require(base is None,'Duplicate text segment');base=va
                for i in range(n):
                    name,parent,addr,sz,fo,align,rel,nrel,fl,r1,r2,r3=unpack('<16s16sQQ8I',data,pos+72+80*i)
                    require(va<=addr and addr+sz<=va+vs,'Section outside segment')
                    if name.rstrip(b'\0')==b'__text' or fl&255 in (2,8):
                        require(off<=fo and fo+sz<=min(off+fs,limit) and addr-va==fo-off,'Unsigned section')
                        self.sections.append(dict(name=name.rstrip(b'\0').decode(),address=addr,size=sz,offset=fo,flags=fl,first=r1,stride=r2,protection=prot))
            elif cmd==0x26:
                require(length==16 and starts is None,'Invalid function starts command')
                off,sz=unpack('<2I',data,pos+8);require(off+sz<=limit,'Unsigned starts');starts=take(data,off,sz)
            elif cmd==2:
                require(length==24 and symtab is None,'Invalid symbols');symtab=unpack('<4I',data,pos+8)
            elif cmd==0xb:
                require(length==80 and indirect is None,'Invalid dynamic symbols');indirect=unpack('<2I',data,pos+56)
            elif cmd==0x1b:
                require(length==24 and self.uuid is None,'Invalid UUID');self.uuid=take(data,pos+8,16).hex()
            pos+=length
        require(pos==32+size,'Unconsumed commands')
        text=[s for s in self.sections if s['name']=='__text']
        require(len(text)==1 and base is not None and starts,'Missing text/function table')
        self.text=text[0];self.low=self.text['address'];self.high=self.low+self.text['size']
        require(self.text['protection']&4 and self.low%4==self.text['size']%4==0,'Nonexecutable or unaligned text')
        cursor=0;value=base;terminated=False
        while cursor<len(starts):
            delta=0;shift=0
            while True:
                require(cursor<len(starts) and shift<64,'Truncated/oversized ULEB')
                b=starts[cursor];cursor+=1;delta|=(b&127)<<shift;shift+=7
                require(delta<1<<64,'ULEB overflow')
                if not b&128:break
            if not delta:
                require(not any(starts[cursor:]),'Invalid starts padding');terminated=True;break
            value+=delta;require(self.low<=value<self.high and value%4==0,'Invalid function address');self.starts.append(value)
        require(terminated and self.starts,'Missing function terminator')
        names=[]
        if symtab:
            no,nc,so,ss=symtab
            require(nc<=1000000 and no+16*nc<=limit and so+ss<=limit,'Unsigned symbols')
            strings=take(data,so,ss)
            for i in range(nc):
                si,typ,sect,desc,addr=unpack('<IBBHQ',data,no+16*i)
                require(si<ss,'Bad symbol name');end=strings.find(b'\0',si)
                require(si<=end<=si+4096,'Invalid symbol string');name=strings[si:end].decode(errors='replace');names.append(name)
                if not typ&0xe0 and typ&0xe==0xe and self.low<=addr<self.high:self.symbols.append((addr,name))
        if indirect:
            off,n=indirect;require(off+4*n<=limit,'Unsigned indirect symbols')
            for s in self.sections:
                if s['flags']&255!=8:continue
                step=s['stride'];require(step and s['size']%step==0,'Bad stub stride')
                require(s['first']+s['size']//step<=n,'Stub outside indirect table')
                for i in range(s['size']//step):
                    index=unpack('<I',data,off+4*(s['first']+i))[0]
                    if index&0xc0000000:continue
                    require(index<len(names),'Bad indirect index');self.stubs[s['address']+step*i]=names[index]

    def owner(self,pc):
        i=bisect_right(self.starts,pc)-1
        return self.starts[i] if i>=0 and self.low<=pc<self.high else None

    def word(self,pc):
        require(self.low<=pc<=self.high-4 and pc%4==0,'Instruction outside text')
        return unpack('<I',self.data,self.text['offset']+pc-self.low)[0]

    def call(self,pc):
        w=self.word(pc)
        if w&0xfc000000==0x94000000:return dict(kind='BL',target=pc+signed(w&0x3ffffff,26)*4)
        if w&0xfffffc1f==0xd63f0000:return dict(kind='BLR',target=None)
        # BLRAA/BLRAB and their zero-modifier variants; only classify, not authenticate.
        if w&0xfffff800==0xd73f0800 or w&0xfffffc1f in (0xd63f081f,0xd63f0c1f):return dict(kind='authenticated indirect call',target=None)
        return None

    def branch(self,pc):
        w=self.word(pc)
        if w&0xfc000000==0x14000000:
            return pc+signed(w&0x3ffffff,26)*4
        return None

    def string(self,addr):
        for s in self.sections:
            if s['flags']&255==2 and s['address']<=addr<s['address']+s['size']:
                off=s['offset']+addr-s['address'];end=self.data.find(b'\0',off,min(off+512,s['offset']+s['size']))
                if end>=off:return self.data[off:end].decode(errors='replace')
        return None

    def describe(self,start):
        end=min([v for v in self.starts if v>start]+[self.high]);calls=[];refs=[]
        require(end-start<=65536,'Function exceeds analysis bound')
        for pc in range(start,end,4):
            w=self.word(pc);call=self.call(pc)
            if call:calls.append(dict(address=hex(pc),**call,import_name=self.stubs.get(call['target'])))
            target=None
            if w&0x9f000000==0x10000000:
                target=pc+signed((w>>5&0x7ffff)<<2|(w>>29&3),21)
            elif w&0x9f000000==0x90000000 and pc+4<end:
                add=self.word(pc+4)
                if add&0xffc00000==0x91000000 and (add>>5&31)==w&31 and w&31!=31:
                    target=(pc&~4095)+(signed((w>>5&0x7ffff)<<2|(w>>29&3),21)<<12)+(add>>10&4095)
            string=self.string(target) if target is not None else None
            if string is not None:refs.append(dict(address=hex(pc),text=string))
        off=self.text['offset']+start-self.low
        return dict(start=hex(start),end=hex(end),symbols=[n for a,n in self.symbols if a==start],
                    sha256=hashlib.sha256(take(self.data,off,end-start)).hexdigest(),direct_and_indirect_calls=calls,string_references=refs)

def candidates(exe,frames=FRAMES):
    result=[]
    for selected in itertools.product(*frames):
        if any(pc%4 for pc in selected):continue
        low=max(0,max(pc-4-(exe.high-4) for pc in selected));high=min(pc-4-exe.low for pc in selected)
        require(high-low<=256*1024*1024,'Slide search too large')
        for slide in range((low+4095)&~4095,high+1,4096):
            pcs=[pc-slide-4 for pc in selected];calls=[exe.call(pc) for pc in pcs]
            if not all(calls):continue
            owners=[exe.owner(pc) for pc in pcs]
            if not all(owners):continue
            edges=[dict(caller=i+2,callee=i+1,target=calls[i+1]['target'],
                        direct_function_match=calls[i+1]['target']==owners[i]) for i in range(len(pcs)-1)]
            result.append(dict(slide=hex(slide),return_addresses=[hex(p) for p in selected],
                               callsites=[hex(p) for p in pcs],owners=owners,edges=edges,
                               first_import=exe.stubs.get(calls[0]['target']),
                               matched_edges=sum(e['direct_function_match'] for e in edges)))
    result.sort(key=lambda r:(r['first_import'] in ('_reboot','___reboot','_reboot_np'),r['matched_edges']),reverse=True)
    return result

def shutdown_context(exe,owners):
    """Static callers include tail branches; none are claimed to have executed."""
    descriptions={a:exe.describe(a) for a in exe.starts}
    edges=[]
    for pc in range(exe.low,exe.high,4):
        call=exe.call(pc);target=call['target'] if call else exe.branch(pc)
        owner=exe.owner(pc)
        if target is not None and owner is not None:
            # Intra-function B edges are not tail-call relationships.
            if call or exe.owner(target)!=owner:
                edges.append(dict(pc=hex(pc),owner=hex(owner),target=hex(target),
                                  kind='call' if call else 'tail_branch',
                                  import_name=exe.stubs.get(target)))
    chosen=set(owners);levels=[]
    for _ in range(6):
        new={int(e['owner'],16) for e in edges if int(e['target'],16) in chosen}-chosen
        levels.append([hex(a) for a in sorted(new)]);chosen|=new
        require(len(chosen)<=256,'Caller traversal exceeds bound')
        if not new:break
    pattern=re.compile(r'reboot|shut.?down|watchdog|critical|console|launchd.*log|log.*launchd',re.I)
    keyword_functions=[a for a,d in descriptions.items() if any(pattern.search(s['text']) for s in d['string_references'])]
    chosen.update(keyword_functions)
    # Add immediate helpers, including log formatting and final reboot wrappers.
    chosen.update(int(e['target'],16) for e in edges if int(e['owner'],16) in set(owners)
                  and int(e['target'],16) in descriptions)
    # The phone still has no serial reasons. Inspect the actual boolean parser,
    # log routing and /dev/console open/fcntl wrappers, not just their callers.
    console_roots={0x10004b268,0x1000444c0,0x10004d420,0x10004d560,0x10004dd98}
    console_helpers={a for a in console_roots if a in descriptions}
    console_helpers.update(int(e['target'],16) for e in edges
                           if int(e['owner'],16) in console_roots
                           and int(e['target'],16) in descriptions)
    chosen.update(console_helpers)
    require(len(chosen)<=256,'Shutdown context exceeds bound')
    literals=[]
    for s in exe.sections:
        if s['flags']&255!=2:continue
        raw=take(exe.data,s['offset'],s['size']);off=0
        for part in raw.split(b'\0'):
            value=part.decode(errors='replace')
            if len(part)<=512 and pattern.search(value):
                literals.append(dict(address=hex(s['address']+off),text=value))
            off+=len(part)+1
    return dict(console_helpers=[hex(a) for a in sorted(console_helpers)],caller_levels=levels,keyword_functions=[hex(a) for a in keyword_functions],
                relevant_literals=literals,edges=edges,
                functions=[descriptions[a] for a in sorted(chosen)],
                all_string_references=[dict(owner=hex(a),references=d['string_references'])
                                       for a,d in descriptions.items() if d['string_references']])

def parse_disassembly(text,exe,functions):
    """Only address-indexed instructions in audited function ranges are exported."""
    wanted={pc for f in functions for pc in range(int(f['start'],16),int(f['end'],16),4)}
    require(len(wanted)<=20000,'Disassembly exceeds instruction bound')
    rows={}
    for line in text.splitlines():
        match=re.match(r'^\s*([0-9a-fA-F]{16})\s+(.+)$',line)
        if not match:continue
        pc=int(match[1],16)
        if pc not in wanted:continue
        instruction=match[2].strip()
        require(pc not in rows and len(instruction)<=1024,'Invalid disassembly row')
        # otool -tvV displays mnemonics, not binary words. Fail closed on other formats.
        require(re.match(r'^[A-Za-z_.][A-Za-z0-9_.]*\b',instruction) is not None,'Unexpected disassembly format')
        rows[pc]=instruction
    require(set(rows)==wanted,'Incomplete original launchd disassembly')
    return [dict(address=hex(pc),instruction=rows[pc]) for pc in sorted(rows)]

def inspect(path,info,disassemble=False):
    raw=Path(path).read_bytes();require(hashlib.sha256(raw).hexdigest()==info['sha256'],'Executable changed after audit')
    exe=Executable(take(raw,info['slice_offset'],info['slice_bytes']),info);cs=candidates(exe)
    chosen=cs[:8];owners=sorted({o for c in chosen for o in c['owners']})
    require(len(owners)<=56,'Unbounded stack attribution')
    # Retain compact address metadata for re-attribution if a photographed digit
    # is corrected. Original executable bytes are never exported.
    call_index=[]
    for pc in range(exe.low,exe.high,4):
        call=exe.call(pc)
        if call:call_index.append([pc,call['target'],exe.owner(pc)])
    context=shutdown_context(exe,owners)
    if disassemble:
        result=subprocess.run(['/usr/bin/otool','-tvV',str(path)],capture_output=True,text=True)
        require(result.returncode==0,'Original launchd disassembly failed')
        context['instructions']=parse_disassembly(result.stdout,exe,context['functions'])
    report=dict(format=2,photo='1000149643.jpg',tested_run='43975218126',launchd=info,uuid=exe.uuid,
                static_index=dict(text_range=[exe.low,exe.high],function_starts=exe.starts,
                                  symbols=exe.symbols,import_stubs=exe.stubs,
                                  callsite_target_owner=call_index),
                executable_slide_observed=False,candidate_count=len(cs),candidates=chosen,
                functions=[exe.describe(o) for o in owners],
                shutdown_context=context,
                limitations=['Candidate slide is inferred, not a recorded runtime load address.',
                 'Uncertain photographed digits are enumerated; return addresses are decremented by four.',
                 'Direct-call matches do not establish the runtime branch condition.',
                 'String references cover ADR and adjacent ADRP+ADD only.',
                 'This does not prove a reboot root cause or modify the phone.'])
    require(len(json.dumps(report).encode())<=MAX_REPORT,'Analysis exceeds bounded report')
    return report

def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def inspect_setup_flow(mount, audit, trust):
    import plistlib
    import re
    binary=mount/'Applications/Setup.app/Setup'
    info=audit.macho(binary,trust,2)
    exe=Executable(binary.read_bytes(),info)
    first=exe.owner(0x10004eefc)
    observed={exe.owner(0x100000000+n-4) for n in (0x4ef00,0x4edec,0x4d3c8,0x4cfe0,0x1560d4,0x50838,0x5029c,0xc4c78,0x3dd70,0x3e80c,0x42fe0,0x42f28,0x42e88,0x3d324,0x44f74,0x3ec94,0x3e260)}
    listing=subprocess.check_output(['/usr/bin/otool','-tvV',str(binary)], text=True)
    # Keep selector names, public preference names, and branch edges only.
    funcs={}
    labels=dict(exe.symbols)
    method=None
    for line in listing.splitlines():
        if line.endswith(':') and not line.startswith((' ', '\t')):
            method=line[:-1]
            continue
        m=re.match(r'^\s*([0-9a-fA-F]{12,16})\s+([a-z][a-z0-9.]+)\s*(.*)',line)
        if not m:continue
        addr=int(m[1],16)
        if not exe.low<=addr<exe.high:continue
        start=exe.owner(addr)
        if method:
            labels.setdefault(start,method)
            method=None
        entry=funcs.setdefault(start,[])
        body=m[3]
        if ';' in body:
            annotation=body.split(';',1)[1].strip()
            if any(x in annotation.lower() for x in ('objc','literal','symbol stub','selector')):
                entry.append([hex(addr-start),annotation[:180]])
        if m[2] in ('bl','b','tbz','tbnz','cbz','cbnz') or m[2].startswith('b.'):
            addrto=re.search(r'0x([0-9a-fA-F]+)',body.split(';',1)[0])
            if addrto:entry.append([hex(addr-start),m[2]+' '+hex(int(addrto[1],16))])
    names=re.compile(r'(Multilingual|WrittenAndSpoken|LanguageAndLocale|KeyboardController|KeyboardData)',re.I)
    chosen=observed|{s for s,k in labels.items() if names.search(k)}
    chosen.update(s for s,v in funcs.items() if any('buddyDefaultKeyboards' in a or 'buddySuggestedKeyboards' in a for _,a in v))
    # Selector stubs in this signed app load a bound selector reference with
    # ADRP/LDR. Resolve image-relative chained rebases in the original file.
    data=exe.data
    base=0x100000000
    sections=[]
    cur=32
    for _ in range(unpack('<I',data,16)[0]):
        typ,n=unpack('<II',data,cur)
        if typ==0x19:
            count=unpack('<I',data,cur+64)[0]
            for j in range(count):
                off=cur+72+j*80
                key,seg,va,size,fo=unpack('<16s16sQQI',data,off)
                if fo and fo+size<=len(data):
                    sections.append((va,va+size,fo,key.rstrip(b'\0').decode()))
        cur+=n
    def loc(va):
        for lo,hi,fo,k in sections:
            if lo<=va<hi:return fo+va-lo,k
        return None,None
    def ptr(va):
        o,_=loc(va)
        if o is None:return 0
        v=unpack('<Q',data,o)[0]
        if not v:return 0
        for t in [v,base+(v&0xffffffff),v&0x7ffffffffff,base+(v&0x7ffffffffff)]:
            if loc(t)[0] is not None:return t
        return 0
    def cs(v):
        o,k=loc(v)
        if o is None or k not in ('__cstring','__objc_methname','__objc_classname'):return ''
        e=data.find(b'\0',o,o+400)
        return data[o:e].decode(errors='replace') if e>o else ''
    def adr(pc,w):
        return (pc&~4095)+(signed(((w>>5&0x7ffff)<<2)|(w>>29&3),21)<<12)
    def stub(va):
        o,k=loc(va)
        if k!='__objc_stubs':return ''
        ws=unpack('<4I',data,o)
        for j,w in enumerate(ws[:-1]):
            if w&0x9f00001f!=0x90000001:continue
            z=ws[j+1]
            if z&0xffc003ff==0xf9400021:return cs(ptr(adr(va+j*4,w)+(z>>10&4095)*8))
        return ''
    methods={}
    for lo,hi,fo,k in sections:
        if k!='__objc_classlist':continue
        for va in range(lo,hi,8):
            cls=ptr(va)
            for obj,prefix in [(cls,'-'),(ptr(cls),'+')]:
                ro=ptr(obj+32)&~7
                name=cs(ptr(ro+24))
                m=ptr(ro+32)
                off,_=loc(m)
                if not name or off is None:continue
                flags,count=unpack('<II',data,off)
                if count>10000:continue
                small=bool(flags&0x80000000)
                length=(flags&0xffff)&~3
                if length!=(12 if small else 24):continue
                for i in range(count):
                    item=m+8+i*length
                    io,_=loc(item)
                    if io is None:break
                    if small:
                        ns,_,imp=unpack('<iii',data,io)
                        nm=cs(item+ns) or cs(ptr(item+ns))
                        impl=item+8+imp
                    else:nm=cs(ptr(item));impl=ptr(item+16)
                    if nm and exe.low<=impl<exe.high:methods[impl]=prefix+'['+name+' '+nm+']'
    labels.update(methods)
    match=re.compile(r'Multilingual|DictationSelector|LanguageAndLocale|KeyboardData|WrittenAndSpoken',re.I)
    chosen.update(s for s,k in methods.items() if match.search(k))
    for s,v in funcs.items():
        for i,(at,a) in enumerate(v):
            parts=a.split()
            if len(parts)!=2 or parts[0] not in ('b','bl') or not parts[1].startswith('0x'):continue
            to=int(parts[1],16)
            dest=stub(to) or methods.get(to,'')
            if dest:v[i]=(at,parts[0]+' '+dest)
            if dest in ('buddyDefaultKeyboards','buddySuggestedKeyboards'):chosen.add(s)
        if s not in chosen:continue
        end=next((e for e in exe.starts if e>s),exe.high)
        for pc in range(s,end,4):
            w=exe.word(pc)
            if w&0x7e000000==0x36000000:
                v.append([hex(pc-s),'test bit '+str((w>>19&31)+(w>>26&32))+' reg '+str(w&31)+' -> '+hex(pc+signed(w>>5&0x3fff,14)*4)])
            if w&0x9f000000!=0x90000000 or pc+4>=end:continue
            z=exe.word(pc+4);reg=w&31
            if z>>5&31!=reg:continue
            if z&0xffc00000==0x91000000:t=adr(pc,w)+(z>>10&4095)
            elif z&0xffc00000==0xf9400000:t=ptr(adr(pc,w)+(z>>10&4095)*8)
            else:continue
            _,sk=loc(t)
            literal=cs(t) or (cs(ptr(t+16)) if sk=='__cfstring' else '')
            if literal:v.append([hex(pc-s),'constant '+literal[:150]])
        v.sort(key=lambda r:int(r[0],16))
    jobs=[]
    for p in (mount/'System/Library/LaunchDaemons').glob('*[Cc]omm[Cc]enter*'):
        try: job=plistlib.loads(p.read_bytes())
        except (OSError, ValueError,plistlib.InvalidFileException):continue
        jobs.append({k:v for k,v in job.items() if k in ('Label','_LimitLoadToDeviceTree','Program','ProgramArguments','Disabled','MachServices')})
    return dict(uuid=exe.uuid,query_owner=hex(first),jobs=jobs,
        method_count=len(methods), method_names={hex(k):v for k,v in sorted(methods.items())}, sites=[dict(start=hex(s),name=labels.get(s),events=funcs.get(s,[])[:500]) for s in sorted(chosen) if s])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('device','upstream','work','output','archive-tool'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--backboard-wait',action='store_true')
    p.add_argument('--data-helper-startup',action='store_true')
    p.add_argument('--prepare-helper-cache',action='store_true')
    a=p.parse_args();require(sys.platform=='darwin' and os.geteuid()==0,'Read-only inspection requires macOS')
    require(sum((a.backboard_wait,a.data_helper_startup,a.prepare_helper_cache))<=1,'Select one analysis mode')
    work=a.work.resolve();out=a.output.resolve();require(not work.exists() and not out.exists(),'Fresh output required')
    work.mkdir(parents=True,mode=0o700);out.mkdir(parents=True)
    extract=load('myron27-fault-extract')
    sys.path[:0]=[str(a.device.resolve()),str(a.upstream.resolve()/'scripts')]
    import prepare_userland as user
    import prepare_data_volume as volume
    import userland_audit as audit
    from qualify_original_root import ROOT_PINS
    from unixnu.ipsw import Ipsw
    from unixnu import userdata
    require(subprocess.check_output(['git','-C',str(a.upstream),'rev-parse','HEAD'],text=True).strip()==extract.UPSTREAM,'Wrong upstream')
    require(shutil.disk_usage(work).free>24*1024**3,'Insufficient private workspace')
    cfg=tomllib.loads((a.device/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1/profile.toml').read_text())
    source=Ipsw(SimpleNamespace(board=cfg,out_root=work),cfg['ipsw']['url'])
    try:
        user.validate_manifest(source);require(source.info('OS')[:2]==user.MEMBERS['OS'],'Wrong original OS')
        trust=audit.trust_entries(source.extract('StaticTrustCache'))
        print('Reading pinned original OS for launchd; no kernel build',flush=True)
        encrypted=source.extract('OS');require(encrypted.stat().st_size==user.MEMBERS['OS'][1],'Truncated OS')
    finally:source.zip.close();source.stream.close()
    decoded=work/'decoded';decoded.mkdir()
    r=subprocess.run([str(a.archive_tool),'fw','aea',str(encrypted),'--output',str(decoded)],capture_output=True)
    require(r.returncode==0,'Original OS decode failed; private tool output withheld')
    image=volume.regular(decoded/Path(user.MEMBERS['OS'][0]).with_suffix('').name)
    encrypted.unlink();raw=extract.check_raw_image(image,userdata,ROOT_PINS['OS'])
    with volume.attached(image,work/'mount',True) as mounted:
        require(mounted['uuid']==ROOT_PINS['OS'][0],'Wrong OS volume UUID')
        if a.prepare_helper_cache:
            sys.path.insert(0,str(ROOT/'myron-gpu'))
            from data_launch_cache import prepare as prepare_cache
            report=prepare_cache(volume.regular(mounted['path']/'System/Library/xpc/launchd.plist'),out)
            report.update(source_volume=raw,source_commit=os.environ.get('GITHUB_SHA'),kernel_built=False)
            (out/'cache-build.json').write_text(json.dumps(report,indent=2)+'\n')
            print('PASS one owner service added; all original cache entries preserved; no phone changes',flush=True)
            return
        if a.data_helper_startup:
            report=load('myron27-data-helper-analysis').inspect(mounted['path'],audit,trust,sys.modules[__name__])
            report.update(source_volume=raw,source_commit=os.environ.get('GITHUB_SHA'),kernel_built=False)
            payload=(json.dumps(report,indent=2)+'\n').encode()
            require(len(payload)<=MAX_REPORT,'Report exceeds bound')
            (out/'data-helper-startup.json').write_bytes(payload)
            print('PASS static Data helper startup-source analysis; no phone changes',flush=True)
            return
        if a.backboard_wait:
            binary=volume.regular(mounted['path']/'usr/libexec/backboardd')
            report=load('myron27-backboard-wait').inspect(binary,audit.macho(binary,trust,2),sys.modules[__name__])
            report.update(source_volume=raw,source_commit=os.environ.get('GITHUB_SHA'),kernel_built=False)
            (out/'backboard-wait.json').write_text(json.dumps(report,indent=2)+'\n')
            print('PASS backboard wait address attribution',flush=True)
            return
        setup_report=inspect_setup_flow(mounted['path'],audit,trust)
        setup_report.update(source_commit=os.environ.get('GITHUB_SHA'), source_volume=raw)
        (out/'setup-keyboard.json').write_text(json.dumps(setup_report,indent=2)+'\n')
        launchd=volume.regular(mounted['path']/'sbin/launchd');info=audit.macho(launchd,trust,2)
        report=inspect(launchd,info,disassemble=True)
    report.update(source_volume=raw,source_commit=os.environ.get('GITHUB_SHA'),result='passed',
                  phone_accessed=False,kernel_built=False,original_files_modified=False)
    payload=(json.dumps(report,indent=2)+'\n').encode();require(len(payload)<=MAX_REPORT,'Report exceeds bound')
    (out/'launchd-reboot-analysis.json').write_bytes(payload)
    print('PASS signed original launchd analysis; candidates:',report['candidate_count'],flush=True)

if __name__=='__main__':main()
