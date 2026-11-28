#!/usr/bin/env python3
"""Static API/launch evidence from hash-verified 24A446; never invokes resize."""
from bisect import bisect_right
import hashlib,json,plistlib,re,struct
from xml.parsers.expat import ExpatError

APFS='/System/Library/PrivateFrameworks/APFS.framework/APFS'
TOKENS=('APFSContainerResize','APFSContainerGetMinimalSize')

def require(ok,why):
    if not ok:raise ValueError(why)

def write_cache(cache,path,index):
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
    from capstone.arm64 import ARM64_OP_IMM
    matches=[x for x in cache.images if x['path']==APFS]
    require(len(matches)==1,'Exact donor APFS image absent or ambiguous')
    image=matches[0];meta=cache.macho(image);starts=sorted(set(meta['starts']));names={}
    for a,n,source in cache.symbols(image,strict=False):
        if n and n!='<redacted>':names.setdefault(a,set()).add(n)
    entries={n:sorted(a for a,ns in names.items() if '_'+n in ns) for n in TOKENS}
    require(all(len(v)==1 for v in entries.values()),'Required APFS API export missing/ambiguous')
    require(all(v[0] in starts for v in entries.values()),'APFS entry lacks exact function boundary')
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);decoder.detail=True
    selected=set(a for a,ns in names.items() if any('APFSContainer' in n and any(t in n for t in ('Resize','MinimalSize','Size','Space')) for n in ns))
    selected|={v[0] for v in entries.values()};queue=sorted(selected);seen=set();rows=[]
    while queue and len(rows)<48:
        start=queue.pop(0)
        if start in seen:continue
        seen.add(start);i=bisect_right(starts,start)-1
        if i<0 or starts[i]!=start:continue
        end=starts[i+1] if i+1<len(starts) else start+1024
        end=min(end,start+4096);raw=cache.read(start,end-start,executable=True)[0]
        ops=list(decoder.disasm(raw,start));calls=[]
        for op in ops:
            if op.mnemonic not in ('bl','b') or not op.operands or op.operands[-1].type!=ARM64_OP_IMM:continue
            target=op.operands[-1].imm
            if start<=target<end:continue
            dest=cache.image_for(target);label=cache.symbol_for(target,dest,strict=False) if dest else None
            calls.append(dict(offset=hex(op.address-start),target=hex(target),image=dest['path'] if dest else None,symbol=label))
            if target in starts and target not in seen and len(queue)<64:queue.append(target)
        rows.append(dict(start=hex(start),names=sorted(names.get(start,())),bytes_inspected=len(raw),
            truncated=i+1>=len(starts) or end<starts[i+1],sha256=hashlib.sha256(raw).hexdigest(),calls=calls[:128],
            flow=index.setup_method_flow(cache,image,decoder,names,start,end,string_limit=256),
            # Exact register/branch operations for ABI review; no executable bytes.
            instructions=[dict(offset=hex(o.address-start),op=o.mnemonic,args=o.op_str) for o in ops[:256]]))
    record=dict(format=1,image=image,entries=entries,symbol_warnings=meta.get('symbol_warnings',[]),
        container_exports=[dict(address=hex(a),names=sorted(ns)) for a,ns in names.items() if any('APFSContainer' in n for n in ns)],
        functions=rows,unvisited_functions=len(queue),phone_accessed=False,resize_called=False,
        limitation='Static iOS 27 API evidence; neither execution nor successful growth is established.')
    payload=(json.dumps(record,indent=2)+'\n').encode();require(len(payload)<4*1024*1024,'APFS report too large');path.write_bytes(payload)
    return dict(image=image['path'],uuid=image['uuid'],functions=len(rows),bytes=len(payload))

def embedded_plists(raw):
    result=[]
    for m in re.finditer(rb'<\?xml[^\x00]*?</plist>',raw,re.DOTALL):
        blob=m.group();require(len(blob)<2*1024*1024,'Embedded plist exceeds bound')
        try:r=plistlib.loads(blob)
        except (ValueError,plistlib.InvalidFileException,ExpatError):continue
        if isinstance(r,dict):result.append(dict(offset=m.start(),sha256=hashlib.sha256(blob).hexdigest(),value=r))
    require(len(result)<32,'Too many embedded plists');return result

def early_boot_slot(mount,plists):
    """Describe an original optional task; never install or execute a program."""
    configs=[p['value'] for p in plists if isinstance(p['value'].get('Boot'),dict)]
    require(len(configs)==1,'Ambiguous original boot configuration')
    task=configs[0]['Boot'].get('restore-datapartition')
    require(isinstance(task,dict),'Original optional boot task missing')
    require(task.get('Program')=='/usr/libexec/HorizonSetup','Unexpected original task path')
    import stat
    directory=mount/'usr/libexec';target=directory/'HorizonSetup'
    require(directory.is_dir() and not directory.is_symlink(),'Invalid original executable directory')
    try:st=target.lstat()
    except FileNotFoundError:kind='absent'
    else:kind='symlink' if stat.S_ISLNK(st.st_mode) else 'regular' if stat.S_ISREG(st.st_mode) else 'other'
    return dict(task=task,path_kind=kind,original_modified=False,
        warning='RequireSuccess requires handling helper refusal without returning a boot-task failure; crashes remain unqualified.')

def write_launch(mount,audit,trust,launch,out):
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
    binary=mount/'sbin/launchd';info=audit.macho(binary,trust,2);raw=binary.read_bytes();exe=launch.Executable(raw,info)
    require(info['sha256']=='c640246d38aaeb2d2372aff1e5aa0de59dec267f53c0dfc155f7837e717af68b','Unexpected launchd')
    chosen=set();descriptions={}
    for start in exe.starts:
        d=exe.describe(start);descriptions[start]=d
        if any(any(k in r['text'] for k in ('cache protected','system services must','launchd_no_cache=','Unable to load cache','launchd.plist')) for r in d['string_references']):chosen.add(start)
    initial=set(chosen)
    for start,d in descriptions.items():
        if any(c['target'] in initial for c in d['direct_and_indirect_calls']):chosen.add(start)
    require(len(chosen)<=40,'Unexpected launch cache call graph')
    cs=Cs(CS_ARCH_ARM64,CS_MODE_ARM);rows=[]
    for start in sorted(chosen):
        d=descriptions[start];end=int(d['end'],16);off=exe.text['offset']+start-exe.low
        ops=list(cs.disasm(raw[off:off+min(end-start,2048)],start))
        rows.append(dict(**d,truncated=end-start>2048,instructions=[dict(offset=hex(x.address-start),op=x.mnemonic,args=x.op_str) for x in ops]))
    # Read-only native plist parser roundtrip independently checks the Python merge.
    import subprocess,tempfile
    from data_launch_cache import build
    original=(mount/'System/Library/xpc/launchd.plist').read_bytes();merged,merge_report=build(original)
    native=[]
    with tempfile.TemporaryDirectory(prefix='myron-cache-parser-') as tmp:
        from pathlib import Path
        for name,data in [('original',original),('merged',merged)]:
            p=Path(tmp)/(name+'.plist');p.write_bytes(data)
            r=subprocess.run(['/usr/bin/plutil','-convert','xml1','-o','-',str(p)],capture_output=True)
            require(r.returncode==0,'Apple plist parser rejected '+name)
            decoded=plistlib.loads(r.stdout);require(decoded==plistlib.loads(data),'Native plist roundtrip changed '+name)
            native.append(dict(name=name,parsed=True,job_count=len(decoded['LaunchDaemons'])))
    plists=embedded_plists(raw)
    early=set()
    for start,d in descriptions.items():
        if any(any(k in r['text'] for k in ('optional boot task not present','RequireSuccess','RequireRun','restore-datapartition')) for r in d['string_references']):early.add(start)
    require(len(early)<=24,'Unexpected early-boot function count')
    early_rows=[]
    for start in sorted(early):
        d=descriptions[start];end=int(d['end'],16);off=exe.text['offset']+start-exe.low
        ops=list(cs.disasm(raw[off:off+min(end-start,16384)],start))
        early_rows.append(dict(**d,truncated=end-start>16384,instructions=[dict(offset=hex(x.address-start),op=x.mnemonic,args=x.op_str) for x in ops]))
    result=dict(format=2,launchd_sha256=info['sha256'],uuid=exe.uuid,embedded_plists=plists,functions=rows,
        early_boot_slot=early_boot_slot(mount,plists),early_boot_functions=early_rows,
        merge=merge_report,native_plist_parser=native,phone_accessed=False,resize_called=False,original_files_modified=False,
        limitation='Native macOS plist acceptance is not iOS launchd runtime qualification.')
    payload=(json.dumps(result,indent=2)+'\n').encode();require(len(payload)<4*1024*1024,'Launch report exceeds bound')
    (out/'growth-launch-analysis.json').write_bytes(payload)
