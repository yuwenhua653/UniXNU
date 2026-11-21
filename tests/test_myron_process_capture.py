#!/usr/bin/env python3
"""Exercise actual upstream sampler code and Myron's nonblocking log adapter.

Kernel/VM APIs are substituted; this does not establish the phone's wait chain.
"""
import argparse,ast,os,subprocess,tempfile,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--device',type=Path,required=True)
p.add_argument('--cc',default='clang')
p.add_argument('--zig',type=Path)
p.add_argument('--sanitize',action='store_true')
a=p.parse_args();device=a.device.resolve();package=device/'package'
cc=[str(a.zig.resolve()),'cc'] if a.zig else [a.cc]
flags=['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if a.sanitize else []
def literals(path):
    tree=ast.parse(path.read_text());result={}
    for n in tree.body:
        if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):
            for target in n.targets:
                if isinstance(target,ast.Name):result[target.id]=n.value.value
    return result

with tempfile.TemporaryDirectory() as tmp:
    out=Path(tmp)
    def run(name,source,extra=()):
        c=out/(name+'.c');exe=out/(name+('.exe' if os.name=='nt' else ''))
        c.write_text(source)
        subprocess.run(cc+['-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-ignored-attributes',
            '-O1','-UNDEBUG','-g','-I',str(package)]+flags+list(extra)+[str(c),'-o',str(exe)],check=True,timeout=90)
        r=subprocess.run([str(exe)],check=True,capture_output=True,text=True,timeout=30)
        print(r.stdout.splitlines()[-1])
    for kind,name in [('process','BootProcessProbe.c'),('ui','BootUiTraceProbe.c')]:
        fixture=literals(Path(__file__).parent/'process-trace-reference'/('check-boot-'+('process-probe' if kind=='process' else 'ui-trace')+'.py'))
        source=(package/name).read_text();main=fixture['main'];prefix=fixture['prefix']
        if kind=='process':
            body=source[source.index('char boot_process_rows'):]
            main=main.replace('boot_process_capture();','capture_and_snapshot();').replace(
                'static void capture_and_snapshot(void){capture_and_snapshot();','static void capture_and_snapshot(void){boot_process_capture();')
        else:
            body=source[source.index('static struct bt_entry samples'):source.index('// One kernel thread found')]
            # Upstream's main-thread formatter gained a kernel-state row. Keep
            # the existing bounds and frame tests, accounting for that new row.
            main=main.replace('got==6&&strstr(live.rows[0]', 'got==7&&strstr(live.rows[0]')
            main=main.replace('strstr(live.rows[5],"STKS#1 x2 p-1")','strstr(live.rows[5],"STKS kern st=")&&strstr(live.rows[6],"STKS#1 x2 p-1")')
            prefix+='#define VM_KERNEL_UNSLIDE(x) (x)\n#define VM_KERNEL_UNSLIDE_OR_PERM(x) (x)\n'
        run(kind,prefix+body+main,['-pthread'] if kind=='ui' else [])
    body=(package/'MyronProcessLog.c').read_text().replace('#include <kern/misc_protos.h>','#include <stdio.h>')
    main=r'''
#include <assert.h>
char boot_process_rows[10][120];
volatile unsigned boot_process_passes,boot_process_seen,boot_process_attempts,boot_process_busy;
volatile unsigned boot_ui_trace_phase,boot_ui_trace_index;
static unsigned sampled,calls,scenario;
void boot_process_snapshot(void){++sampled;}
unsigned boot_ui_trace_role_rows(unsigned r,char rows[][120],unsigned max,unsigned detail){
 assert(r<4 && max==40 && detail==2);++calls;if(scenario)return 0;
 for(unsigned i=0;i<40;++i){memset(rows[i],'x',119);rows[i][119]=0;}return 40;
}
int main(void){
 char buffer[24578];memset(boot_process_rows,'y',sizeof boot_process_rows);
 for(unsigned i=0;i<10;++i)boot_process_rows[i][119]=0;
 boot_process_passes=33;boot_process_attempts=34;boot_process_busy=1;boot_ui_trace_phase=4;
 assert(!myron_process_snapshot(NULL,10));
 for(size_t cap=0;cap<=sizeof(buffer)-1;++cap){
  memset(buffer,'Z',sizeof buffer);size_t n=myron_process_snapshot(buffer,cap);
  assert(buffer[cap]=='Z');assert(!cap || (n<cap && buffer[n]==0));
 }
 size_t n=myron_process_snapshot(buffer,sizeof(buffer));assert(n<24576);
 assert(strstr(buffer,"passes=33")&&strstr(buffer,"busy=1")&&strstr(buffer,"role 3"));
 scenario=1;myron_process_snapshot(buffer,sizeof(buffer));
 assert(strstr(buffer,"no completed stack rows")&&sampled&&calls);
 puts("PASS: actual log adapter; every capacity 0..24577, immutable complete snapshots, four roles, stale/busy markers and no user/task/process reads");
}
'''
    run('adapter',body+main)
    worker=(package/'BootProcessWorker.c').read_text()
    assert 'kernel_thread_start_priority(capture_worker' in worker
    assert 'if (nprocs > 0) boot_process_capture();' in worker
    log=(device.parent/'sm8850/drivers/NativeUfs/MyronBootLog.h').read_text()
    assert 'boot_process_capture(' not in log and 'boot_ui_trace_task(' not in log
    assert log.index('myron_process_snapshot((char *)slot+prefix')<log.index('size_t n=myron_boot_log_snapshot(')
    assert '24576' in log
    for arg in ('boot-ui-trace=1','boot-ui-focus3=chronod','boot-ui-focus4=Setup'):
        assert arg in (device/'boot_assets.py').read_text()
    print('PASS: separate worker, bounded retained stack section and required boot arguments; device execution unverified')
