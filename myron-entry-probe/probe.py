#!/usr/bin/env python3
"""Instrument only a SHA-pinned copy of the retained iOS27 fileset.

Terminal stop at first C entry; no kernel/root rebuild, no automatic reset.
The fixed sites below belong only to this exact prelinked image, never R90.
"""
import argparse,hashlib,json,struct,subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
SHA='8c1dca686c9a99126402e59b1e5e553beb88abe4dbcf2d2a40b335bfc4e97718'
ENTRY=0xfffffff00a3a1488
CAVE=0xfffffff00a3a1500
LOW=0xfffffff00a3a2000
FIRST=0xfffffff00a3a305c
CSTART=0xfffffff00aa744e4
SITES=[(ENTRY,0x140006f5,'ProbeEntry'),
       (FIRST+0x1c,0xf9400696,'LowMark'),
       (0xfffffff00a3a3290,0xd5033b9f,'TablesMark'),
       (0xfffffff00a3a33c8,0xa9400c02,'KeysMark'),
       (0xfffffff00a3a3418,0xd5181000,'MmuMark'),
       (CSTART,0xd503237f,'CStop')]

def need(ok,msg):
    if not ok:raise ValueError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def commands(b,at=0):
    need(struct.unpack_from('<I',b,at)[0]==0xfeedfacf,'Mach-O magic')
    n,sz=struct.unpack_from('<II',b,at+16);p=at+32;end=p+sz
    need(end<=len(b),'Command bounds')
    for _ in range(n):
        c,s=struct.unpack_from('<II',b,p);need(s>=8 and s%8==0 and p+s<=end,'Command length')
        yield c,p,s;p+=s
    need(p==end,'Command envelope')
def segments(b):
    return [struct.unpack_from('<4Q',b,p+24) for c,p,s in commands(b) if c==0x19 and struct.unpack_from('<Q',b,p+32)[0]]
def offset(segs,va,n=4):
    hits=[o+va-v for v,z,o,f in segs if v<=va and va-v+n<=f]
    need(len(hits)==1,'Unique file-backed mapping required');return hits[0]
def branch(site,target):
    d=target-site;need(d%4==0 and -(1<<27)<=d<(1<<27),'Branch range')
    return 0x14000000|((d//4)&0x3ffffff)
def inspect(b):
    need(sha(b)==SHA,'Wrong retained kernel; no changes made')
    ss=segments(b)
    pcs=[struct.unpack_from('<Q',b,p+272)[0] for c,p,n in commands(b) if c==5 and n==288]
    need(pcs==[ENTRY],'Unexpected LC_UNIXTHREAD PC')
    need(not any(b[offset(ss,CAVE,LOW-CAVE):offset(ss,CAVE,LOW-CAVE)+LOW-CAVE]),'Observer cave not empty')
    for va,word,name in SITES:need(struct.unpack_from('<I',b,offset(ss,va))[0]==word,'Instruction mismatch: '+name)
    # Low vectors consist of self loops, not live handlers that may be resumed.
    for i in range(16):need(struct.unpack_from('<I',b,offset(ss,LOW+i*128))[0]==0x14000000,'Low vector is not a self-loop')
    return ss

def build(kernel,out,compiler,zig=False):
    raw=Path(kernel).read_bytes();ss=inspect(raw)
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    defs={'start_first_cpu':FIRST,'low_continue':FIRST+0x20,'tables_continue':0xfffffff00a3a3294,
          'keys_continue':0xfffffff00a3a33cc,'mmu_continue':0xfffffff00a3a341c}
    link=out/'observer.ld';link.write_text('ENTRY(ProbeEntry)\nSECTIONS { . = '+hex(CAVE)+'; .text : { *(.text) } /DISCARD/ : { *(.comment) *(.eh_frame*) } }\n'+'\n'.join(k+' = '+hex(v)+';' for k,v in defs.items()))
    source=Path(__file__).with_name('Observer.S');elf=out/'observer.elf'
    cc=[str(compiler),'cc','-target','aarch64-freestanding'] if zig else [str(compiler),'--target=aarch64-none-elf','-fuse-ld=lld']
    subprocess.run(cc+['-nostdlib','-Wl,-T,'+str(link),str(source),'-o',str(elf)],check=True)
    with elf.open('rb') as f:
        e=ELFFile(f);syms={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        sec=e.get_section_by_name('.text');code=sec.data();need(sec['sh_addr']==CAVE,'Observer address changed')
    need(len(code)<=LOW-CAVE and syms['Context']+136<=CAVE+len(code),'Observer exceeds cave')
    data=bytearray(raw);at=offset(ss,CAVE,len(code));data[at:at+len(code)]=code
    changes=[]
    for va,before,name in SITES+[(LOW+i*128,0x14000000,'LowFault') for i in range(16)]:
        after=branch(va,syms[name]);struct.pack_into('<I',data,offset(ss,va),after)
        changes.append(dict(va=hex(va),before=hex(before),after=hex(after),target=name))
    output=out/'kernel.macho';output.write_bytes(data)
    report=dict(result='passed',input_sha256=SHA,output_sha256=sha(data),bytes=len(data),
        entry=hex(ENTRY),c_entry=hex(CSTART),cave=hex(CAVE),observer_bytes=len(code),
        source_sha256=sha(source.read_bytes()),labels={k:hex(v) for k,v in syms.items() if k},changes=changes,
        phase_meanings={'2710':'Actual XNU entry','2711':'Low vectors installed; boot arguments next',
            '2712':'Bootstrap page tables constructed','2713':'Kernel PAC keys about to be installed',
            '2714':'About to enable MMU','2716':'C entry reached; intentional terminal stop',
            '27EE':'Low exception caught; terminal stop'},
        first_c_prologue_executed=False,terminal_stop=True,automatic_reset=False,phone_tested=False)
    (out/'probe.json').write_text(json.dumps(report,indent=2)+'\n');return report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('kernel','out','compiler'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--zig',action='store_true');a=p.parse_args()
    print(json.dumps(build(a.kernel,a.out,a.compiler,a.zig),indent=2))
