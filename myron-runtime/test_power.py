#!/usr/bin/env python3
"""Exercise the actual platform method; firmware poweroff needs a phone test."""
from pathlib import Path
import argparse
import subprocess
import sys
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--cxx',default='c++')
a=p.parse_args()
patch=Path(__file__).with_name('platform-power.patch').read_text()
added='\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
start=added.index('int ArmDTPlatform::haltRestart (unsigned int type)')
brace=added.index('{',start);end=brace+1;depth=1
while depth:
    depth+=(added[end]=='{')-(added[end]=='}');end+=1
method=added[start:end]
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    (root/'test.cpp').write_text('''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
enum { kPEHaltCPU=0,kPERestartCPU=1,kPEHangCPU=2,kPEUPSDelayHaltCPU=3,
       kPEPanicRestartCPU=4,kPEPanicSync=5,kPEPagingOff=6,kPEPanicBegin=7 };
static unsigned calls,delegated;static uint32_t command;static bool conduit;
static int platformPowerCall(bool hvc,uint32_t function) {
    ++calls;command=function;conduit=hvc;return -3;
}
struct IODTPlatformExpert {
    int haltRestart(unsigned type){++delegated;return int(type)+100;}
};
struct ArmDTPlatform:IODTPlatformExpert {
    bool psciKnown=false,psciHvc=false;
    int haltRestart(unsigned type);
};
'''+method+'''
int main() {
    ArmDTPlatform platform;
    assert(platform.haltRestart(kPEHaltCPU)==-1 && calls==0);
    assert(platform.haltRestart(kPERestartCPU)==-1 && calls==0);
    for(unsigned hvc=0;hvc<2;++hvc) {
        platform.psciKnown=true;platform.psciHvc=hvc;
        for(unsigned type: {0u,1u,3u}) {
            unsigned before=calls;
            assert(platform.haltRestart(type)==-3 && calls==before+1);
            assert(command==(type==1?0x84000009u:0x84000008u) && conduit==bool(hvc));
        }
        for(unsigned type: {2u,4u,5u,6u,7u,99u}) {
            unsigned before=calls,old=delegated;
            assert(platform.haltRestart(type)==int(type)+100);
            assert(calls==before && delegated==old+1);
        }
    }
    puts("PASS: actual platform shutdown/restart dispatch, both DT conduits, refusal without a conduit, unchanged panic/paging paths; no hardware exercised");
}
''')
    subprocess.run([a.cxx,'-std=c++17','-Wall','-Wextra','-Werror',root/'test.cpp','-o',root/'test'],check=True)
    subprocess.run([root/'test'],check=True)
    if sys.platform == 'darwin':
        # Cross-compile the actual SMC/HVC register constraints before a full
        # kernel build. This is not a firmware invocation on the build host.
        begin=added.index('static int platformPowerCall (')
        power=added[begin:start]
        (root/'arm64e.cpp').write_text('#include <stdint.h>\n'+power+
            '\nextern "C" int power_probe(bool hvc,uint32_t fn){return platformPowerCall(hvc,fn);}\n')
        subprocess.run(['xcrun','clang++','-target','arm64e-apple-ios27.0',
            '-std=c++17','-Wall','-Wextra','-Werror','-c',root/'arm64e.cpp','-o',root/'arm64e.o'],check=True)
        print('PASS: actual PSCI instruction wrapper cross-compiled for arm64e; not executed')
