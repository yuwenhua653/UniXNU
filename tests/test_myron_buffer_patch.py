#!/usr/bin/env python3
"""Verify buffer observers preserve the pinned XNU lifecycle and check failures."""
import argparse,re,shutil,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True);p.add_argument('--upstream',type=Path,required=True);p.add_argument('--xnu',type=Path,required=True);a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
subjects=('bsd/vfs/vfs_bio.c','osfmk/kern/boot_progress.h')
with tempfile.TemporaryDirectory() as tmp:
 w=Path(tmp);dest=w/subjects[0];dest.parent.mkdir(parents=True);shutil.copyfile(a.xnu/subjects[0],dest)
 before=None
 for scope in ('arch','os','device'):
  series=roots[scope]/'patches/xnu/series'
  for line in series.read_text().splitlines():
   line=line.strip()
   if not line or line.startswith('#'):continue
   prefix,sep,tail=line.partition(':');patch=(roots[prefix]/tail if sep else series.parent/line).resolve();text=patch.read_text()
   if not any('--- a/'+n in text or '+++ b/'+n in text for n in subjects):continue
   if patch.name=='myron-buffer-ownership.patch':before=dest.read_text()
   subprocess.run(['git','apply',*[f'--include={n}' for n in subjects],str(patch)],cwd=w,check=True)
 assert before
 s=dest.read_text();header=(w/subjects[1]).read_text()
 assert 'void myron_buffer_event(unsigned, uint64_t, uint64_t, unsigned, unsigned, unsigned, uint64_t);' in header
 assert '#define myron_buffer_event(...) ((void)0)' in header
 # Strip only observer additions, proving buffer flags, return semantics,
 # callback handling and the actual panic condition/body were not changed.
 restored=s.removeprefix('#include <kern/boot_progress.h>\n')
 macro=re.search(r'\n#if defined\(MYRON_EARLY_PROGRESS\)\n#define MYRON_BUF_EVENT.*?#endif\n\n',restored,re.S).group()
 restored=restored.replace(macro,'',1)
 restored=restored.replace('\tbuf_t bp = alloc_io_buf(vp, is_vm_privileged());\n\tif (bp) { MYRON_BUF_EVENT(4, bp); }\n\treturn bp;', '\treturn alloc_io_buf(vp, is_vm_privileged());')
 for kind in (1,2,5,6):
  pattern=r'\t+MYRON_BUF_EVENT\('+str(kind)+r', bp\);\n'
  assert len(re.findall(pattern,restored))==1
  restored=re.sub(pattern,'',restored)
 callback='\t\tMYRON_BUF_CALLBACK(bp, iodone_func, callout);\n'
 assert s.count(callback)==1
 assert callback+'\t\t(*iodone_func)(bp, arg);' in s
 restored=restored.replace(callback,'',1)
 # Capture the original caller on both paths before the panic-only block can
 # be outlined into buf_brelse.cold.N with its own return address.
 release_observer='\t/* Keep return-address capture outside the compiler-outlined panic block. */\n\tMYRON_BUF_EVENT((bp->b_whichq != -1 || !(bp->b_lflags & BL_BUSY)) ? 255 : 3, bp);\n\n'
 assert s.count(release_observer)==1
 assert release_observer+'\tif (bp->b_whichq != -1 || !(bp->b_lflags & BL_BUSY)) {' in s
 restored=restored.replace(release_observer,'',1)
 restored=restored.replace('\n\n\t/* Record our progress. */','\n\t/* Record our progress. */',1)
 assert restored==before, ''.join(__import__('difflib').unified_diff(before.splitlines(True),restored.splitlines(True)))
 # Compile the exact injected macro with deliberately distinct fields. Verify
 # disabled boards never evaluate arguments (including invalid pointers).
 probe='''#include <stdint.h>
#include <assert.h>
struct B { int b_whichq; unsigned b_lflags,b_flags; uint64_t b_lblkno; };
static unsigned calls;
static void myron_buffer_event(unsigned k,uint64_t p,uint64_t c,unsigned q,unsigned l,unsigned f,uint64_t b) {
 assert((k==3 || k==7 || k==8) && p && c && q==~0u && l==0x123 && f==0x456 && b==0xabcdef);
 if(k==7 || k==8)assert(c==0xfeed);
 calls++;
}
'''+macro+'''
int main(void) {
#if defined(MYRON_EARLY_PROGRESS)
 struct B b={-1,0x123,0x456,0xabcdef};MYRON_BUF_EVENT(3,&b);assert(calls==1);
 MYRON_BUF_CALLBACK(&b,0xfeed,1);assert(calls==2);
 MYRON_BUF_CALLBACK(&b,0xfeed,0);assert(calls==3);
#else
 MYRON_BUF_EVENT(3,((struct B *)0));assert(calls==0);
 MYRON_BUF_CALLBACK(((struct B *)0),0,++calls);assert(calls==0);
#endif
 return 0;
}
'''
 (w/'probe.c').write_text(probe)
 for flags in ([],['-DMYRON_EARLY_PROGRESS=1']):
  subprocess.run(['cc','-std=c11',*flags,str(w/'probe.c'),'-o',str(w/'probe')],check=True)
  subprocess.run([str(w/'probe')],check=True)
print('PASS selected buffer patch stack; original lifecycle/assertion unchanged; exact typed field capture; disabled-board no-evaluation')
