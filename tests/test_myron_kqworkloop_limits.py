#!/usr/bin/env python3
"""Check Darwin 26 workloop limit compatibility on the selected XNU source."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--xnu',type=Path,required=True)
p.add_argument('--device',type=Path,required=True)
p.add_argument('--cc',default='clang')
p.add_argument('--check-source-only',action='store_true')
a=p.parse_args()
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    source=root/'bsd/kern/kern_proc.c'
    source.parent.mkdir(parents=True)
    original=(a.xnu/'bsd/kern/kern_proc.c').read_text()
    source.write_text(original)
    patch=(a.device/'patches/xnu/myron-reboot-evidence.patch').resolve()
    subprocess.run(['git','apply','--include=bsd/kern/kern_proc.c',str(patch)],cwd=root,check=True)
    updated=source.read_text()
    start=updated.index('int\nproc_set_kqworkloop_limits(')
    end=updated.index('\n}\n',start)+3
    function=updated[start:end]
    old_start=original.index('int\nproc_set_kqworkloop_limits(')
    old_end=original.index('\n}\n',old_start)+3
    assert updated[:start]+updated[end:]==original[:old_start]+original[old_end:]
    assert 'kqworkloop_check_limit_exceeded(fdp);' in function
    assert '#define KQWL_LIMIT_SENTINEL ((int) (-1))' in (a.xnu/'bsd/sys/filedesc.h').read_text()
    print('PASS selected patch applies and changes only workloop limit assignment',flush=True)
    if a.check_source_only:
        raise SystemExit(0)
    shim=r'''
#include <assert.h>
#define KQWL_LIMIT_SENTINEL ((int) (-1))
struct filedesc { int fd_kqhashlock,kqwl_dyn_soft_limit,kqwl_dyn_hard_limit; };
struct proc { struct filedesc p_fd; };
typedef struct proc *proc_t;
static unsigned checked;
static void lck_mtx_lock_spin_always(int *lock) { assert(!*lock);*lock=1; }
static void lck_mtx_unlock(int *lock) { assert(*lock);*lock=0; }
static void kqworkloop_check_limit_exceeded(struct filedesc *fd) { assert(fd->fd_kqhashlock);checked++; }
'''
    tests=r'''
int main(void) {
 struct proc process={0};
 int limits[][2]={{5,10},{3,10},{0,0},{-1,-1},{64,256}};
 for(unsigned i=0;i<sizeof(limits)/sizeof(limits[0]);++i) {
  assert(proc_set_kqworkloop_limits(&process,limits[i][0],limits[i][1])==0);
  assert(!process.p_fd.fd_kqhashlock && checked==i+1);
#if defined(MYRON_EARLY_PROGRESS)
  assert(process.p_fd.kqwl_dyn_soft_limit==-1 && process.p_fd.kqwl_dyn_hard_limit==-1);
  /* kern_event.c only enforces strictly positive limits. */
  assert(!(process.p_fd.kqwl_dyn_hard_limit>0 && 11>process.p_fd.kqwl_dyn_hard_limit));
#else
  assert(process.p_fd.kqwl_dyn_soft_limit==limits[i][0]);
  assert(process.p_fd.kqwl_dyn_hard_limit==limits[i][1]);
#endif
 }
 return 0;
}
'''
    unit=root/'limits.c'
    unit.write_text(shim+function+tests)
    for label,flags in [('myron',['-DMYRON_EARLY_PROGRESS=1']),('baseline',[])]:
        exe=root/('test-'+label)
        subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',*flags,str(unit),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True,timeout=20)
        print('PASS '+label+' limit values, repeat assignment, lock ownership and reevaluation',flush=True)
