#!/usr/bin/env python3
"""Exercise the actual patched console entry gates, including the mute case."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
for n in ('device','upstream','xnu'):p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--cc',default='cc')
a=p.parse_args()
roots=dict(device=a.device.resolve(),arch=a.upstream.resolve()/'profiles/arch/arm64e',
           os=a.device.resolve()/'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1')
paths=['osfmk/console/serial_console.c','osfmk/kern/boot_progress.h']
with tempfile.TemporaryDirectory() as td:
    w=Path(td);dst=w/paths[0];dst.parent.mkdir(parents=True)
    dst.write_bytes((a.xnu/paths[0]).read_bytes())
    before=None
    for scope in ('arch','os','device'):
        series=roots[scope]/'patches/xnu/series'
        for line in series.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            prefix,sep,tail=line.partition(':')
            patch=roots[prefix]/tail if sep else series.parent/line
            if patch.name=='myron-console-route.patch':before=dst.read_text()
            if any('+++ b/'+n in patch.read_text() for n in paths):
                subprocess.run(['git','apply',*['--include='+n for n in paths],str(patch)],cwd=w,check=True)
    text=dst.read_text()
    buffered='\tif (myron_boot_console_write(str, size, disableConsoleOutput)) { return; }\n'
    raw='\tif (myron_boot_console_write(&c, 1, disableConsoleOutput)) { return; }\n'
    assert text.count(buffered)==text.count(raw)==1
    assert text.replace(buffered,'').replace(raw,'')==before, 'Native console behavior changed'
    start=text.index('void\nconsole_write(char *str, int size)')
    end=text.index('\n\tassert(str != NULL);',start)
    # Compile the exact entry/gate region; later ring-buffer work is a sentinel.
    write=text[start:end]+'\n ++native_calls;\n}\n'
    start=text.index('void\nconsole_write_unbuffered(char c)')
    end=text.index('\n}\n',start)+3
    unbuffered=text[start:end]
    shim=r'''
#include <assert.h>
#include <stdbool.h>
static int disableConsoleOutput,active,native_calls,recorder_calls,muted_calls;
static char observed;
static int myron_boot_console_write(const char *s,int n,int muted) {
 if(!active)return 0;
 ++recorder_calls;if(muted)++muted_calls;
 if(n>0)observed=s[0];
 return 1;
}
static void _cnputc(char c,bool poll){assert(poll);observed=c;++native_calls;}
'''
    main=r'''
int main(void) {
 char data[]="reason";
 active=0;disableConsoleOutput=1;
 console_write(data,6);console_write_unbuffered('x');
 assert(!native_calls && !recorder_calls);
 disableConsoleOutput=0;console_write(data,6);console_write_unbuffered('y');
 assert(native_calls==2 && !recorder_calls && observed=='y');
 active=1;disableConsoleOutput=1;
 console_write(data,6);assert(observed=='r');console_write_unbuffered('z');
 assert(native_calls==2 && recorder_calls==2 && muted_calls==2 && observed=='z');
 disableConsoleOutput=0;console_write(data,6);console_write_unbuffered('w');
 assert(native_calls==2 && recorder_calls==4 && muted_calls==2 && observed=='w');
 return 0;
}
'''
    (w/'test.c').write_text(shim+write+unbuffered+main)
    subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    str(w/'test.c'),'-o',str(w/'test')],check=True)
    subprocess.run([str(w/'test')],check=True,timeout=20,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
print('PASS buffered/unbuffered capture before native mute; inactive mute and native fallback unchanged; no duplicate output')
