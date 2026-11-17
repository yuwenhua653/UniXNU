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

def inspect(path,info):
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
    report=dict(format=1,photo='1000149643.jpg',tested_run='43975218126',launchd=info,uuid=exe.uuid,
                static_index=dict(text_range=[exe.low,exe.high],function_starts=exe.starts,
                                  symbols=exe.symbols,import_stubs=exe.stubs,
                                  callsite_target_owner=call_index),
                executable_slide_observed=False,candidate_count=len(cs),candidates=chosen,
                functions=[exe.describe(o) for o in owners],
                limitations=['Candidate slide is inferred, not a recorded runtime load address.',
                 'Uncertain photographed digits are enumerated; return addresses are decremented by four.',
                 'Direct-call matches do not establish the runtime branch condition.',
                 'String references cover ADR and adjacent ADRP+ADD only.',
                 'This does not prove a reboot root cause or modify the phone.'])
    require(len(json.dumps(report).encode())<=MAX_REPORT,'Analysis exceeds bounded report')
    return report

def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('device','upstream','work','output','archive-tool'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();require(sys.platform=='darwin' and os.geteuid()==0,'Read-only inspection requires macOS')
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
        launchd=volume.regular(mounted['path']/'sbin/launchd');info=audit.macho(launchd,trust,2)
        report=inspect(launchd,info)
    report.update(source_volume=raw,source_commit=os.environ.get('GITHUB_SHA'),result='passed',
                  phone_accessed=False,kernel_built=False,original_files_modified=False)
    payload=(json.dumps(report,indent=2)+'\n').encode();require(len(payload)<=MAX_REPORT,'Report exceeds bound')
    (out/'launchd-reboot-analysis.json').write_bytes(payload)
    print('PASS signed original launchd analysis; candidates:',report['candidate_count'],flush=True)

if __name__=='__main__':main()
