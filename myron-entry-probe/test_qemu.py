#!/usr/bin/env python3
"""Execute the exact patched XNU prefix in QEMU; no CPU instruction hooks.

Synthetic boot args cover the real prefix's loads. No C initialization or root
media is executed. QEMU virt is not a model of the phone or its hypervisor.
"""
import argparse,json,re,struct,subprocess,time
from pathlib import Path
import probe
p=argparse.ArgumentParser(description=__doc__)
for n in ('probe','out','clang','qemu'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
r=json.loads((a.probe/'probe.json').read_text());b=(a.probe/'kernel.macho').read_bytes()
probe.need(probe.sha(b)==r['output_sha256'],'Changed probe image')
ss=probe.segments(b);VA=min(x[0] for x in ss);PA=0x8c0004000;ARGS=0x8c6000000
slide=PA-VA;labels={k:int(v,16)+slide for k,v in r['labels'].items() if int(v,16)>=VA}
loaded=bytearray(max(v+f for v,z,o,f in ss)-VA)
for v,z,o,f in ss:loaded[v-VA:v-VA+f]=b[o:o+f]
args=bytearray(4096);struct.pack_into('<HHI4Q',args,0,2,2,0,VA,PA,0x80000000,ARGS+4096)
struct.pack_into('<6Q',args,40,0xfc800000,1,4800,1200,2608,32)
(a.out/'args.bin').write_bytes(args)
start=a.out/'start.S';start.write_text(f'.text\n.global _start\n_start:\n ldr x0, ={ARGS}\n ldr x1, ={probe.ENTRY+slide}\n br x1\n')
link=a.out/'start.ld';link.write_text('ENTRY(_start)\nSECTIONS { . = 0x40080000; .text : { *(.text) } }\n')
elf=a.out/'start.elf';subprocess.run([str(a.clang),'--target=aarch64-none-elf','-fuse-ld=lld','-nostdlib','-Wl,-T,'+str(link),str(start),'-o',str(elf)],check=True)
results=[]
for name,fault,phase in [('prefix',None,0x2716),('undefined_before_tables',probe.FIRST+0x20,0x27ee)]:
    out=a.out/name;out.mkdir();data=bytearray(loaded)
    if fault:struct.pack_into('<I',data,fault-VA,0)
    (out/'loaded.bin').write_bytes(data)
    ram=out/'ram.bin'
    q=[str(a.qemu),'-M','virt,gic-version=3,memory-backend=ram0','-cpu','max','-m','38G','-object',f'memory-backend-file,id=ram0,size=38G,mem-path={ram.resolve()},share=on,prealloc=off','-nodefaults','-nographic','-monitor','none','-serial','none','-kernel',str(elf.resolve()),'-qmp','stdio','-S',
       '-device',f'loader,file={(out/"loaded.bin").resolve()},addr={PA},force-raw=on',
       '-device',f'loader,file={(a.out/"args.bin").resolve()},addr={ARGS},force-raw=on']
    with (out/'qemu.log').open('w') as log:
        proc=subprocess.Popen(q,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
        try:
            json.loads(proc.stdout.readline())
            def call(cmd,arguments=None):
                proc.stdin.write((json.dumps(dict(execute=cmd,arguments=arguments or {}))+'\n').encode());proc.stdin.flush()
                while True:
                    line=proc.stdout.readline();probe.need(bool(line),'QEMU exited')
                    msg=json.loads(line)
                    if 'return' in msg:return msg['return']
                    if 'error' in msg:raise ValueError(msg)
            call('qmp_capabilities');call('cont');deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                time.sleep(.1)
                regs=call('human-monitor-command',{'command-line':'info registers'})
                pc=int(re.search(r'PC=([0-9a-fA-F]+)',regs)[1],16)
                if labels['ProbePark']<=pc<=labels['ProbePark']+8:break
            else:raise ValueError('Prefix did not reach terminal observer: '+regs)
            call('stop');(out/'registers.txt').write_text(regs)
            memory=call('human-monitor-command',{'command-line':f'xp /17gx {labels["Context"]}'})
            (out/'context.txt').write_text(memory)
            values=[int(x,16) for x in re.findall(r'0x([0-9a-fA-F]{16})(?!:)',memory)]
            probe.need(len(values)==17 and values[1]==phase,'Wrong terminal phase: '+memory)
            if fault:probe.need(values[14]==fault+slide and values[16]==0x2711,'Fault location/stage mismatch')
            # Use a memory backend, after stopping the VM, to inspect rendered glyphs.
            with ram.open('rb') as f:
                f.seek(0xfc800000+4800*(2608//4)-0x40000000);pixels=f.read(4800*28)
            # Reuse only independent expected-font checker, not the CPU emulator harness.
            import importlib.util,sys
            oldargv=sys.argv;sys.argv=['test_observer','--probe',str(a.probe)]
            spec=importlib.util.spec_from_file_location('observer_checks',Path(__file__).with_name('test_observer.py'))
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);sys.argv=oldargv
            mod.check_pixels(pixels,phase)
            results.append(dict(name=name,result='passed',phase=hex(phase),pc=hex(pc),rendered_phase_checked=True))
            call('quit');proc.wait(timeout=3)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
            ram.unlink(missing_ok=True)
    (out/'loaded.bin').unlink()
report=dict(result='passed',kernel_sha256=probe.sha(b),cases=results,
    actual_xnu_prefix_executed=True,pac_hooks=False,instruction_hooks=False,
    first_c_prologue_executed=False,boot_args_synthetic=True,phone_tested=False,desktop_reached=False)
(a.out/'qemu-prefix.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
