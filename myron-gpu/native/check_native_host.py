#!/usr/bin/env python3
"""Run real portable backend algorithms over upstream software hardware peers.

These tests do not compile the kernel service, execute GPU firmware, or render.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
from prepare_sources import stage

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--cxx', default='c++')
    parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    results = {}
    results['hwinit'] = subprocess.check_output([sys.executable,HERE/'test_hwinit.py',
                                                 '--cxx',a.cxx],text=True).strip()
    results['snapshot'] = subprocess.check_output([sys.executable,HERE/'test_snapshot.py',
                                                   '--cxx',a.cxx],text=True).strip()
    results['runtime_snapshot'] = subprocess.check_output([sys.executable,HERE/'test_runtime_snapshot.py',
        '--references',a.references,'--cxx',a.cxx],text=True).strip()
    results['memory_pressure'] = subprocess.check_output([sys.executable,HERE/'test_memory_pressure.py',
        '--references',a.references,'--cxx',a.cxx],text=True).strip()
    results['metal_publication'] = subprocess.check_output([sys.executable,HERE/'test_metal_publish.py',
                                                            '--cxx',a.cxx],text=True).strip()
    for name in ('publish_lifecycle', 'publish_views', 'publish_open'):
        results[name] = subprocess.check_output([sys.executable,HERE/('test_'+name+'.py'),
            '--references',a.references,'--cxx',a.cxx],text=True).strip()
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0')
    with tempfile.TemporaryDirectory(prefix='myron-native-host-') as tmp:
        root = Path(tmp)
        inputs = stage(a.references, root/'source')
        driver, pm4 = root/'source/NativeAdreno', root/'source/AdrenoPM4'
        fixture = (a.references/'NativeAdreno/tests').resolve()
        includes = root/'include'
        for name in ('IOTypes.h', 'IOLib.h'):
            path = includes/'IOKit'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#include "XnuMemoryFixture.h"\n')
        flags = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-g', '-O1']
        obj = root/'pm4.o'
        subprocess.run([a.cc, '-std=c11', *flags, '-c', pm4/'AdrenoPM4.c', '-o', obj], check=True)
        suites = {'ring': ('NativeAdrenoRing',), 'cpinit': ('NativeAdrenoCpInit', 'NativeAdrenoRing'),
                  'irq': ('NativeAdrenoIrq',), 'timer': ('NativeAdrenoTimer',)}
        for suite, names in suites.items():
            exe = root/suite
            command = [a.cxx, '-std=c++17', *flags, '-I', includes, '-I', fixture, '-I', driver, '-I', pm4,
                       fixture/('test_'+suite+'.cpp'), *(driver/(n+'.cpp') for n in names), obj, '-o', exe]
            subprocess.run(command, check=True)
            results[suite] = subprocess.check_output([exe], env=env, text=True).strip()
        exe = root/'policy'
        subprocess.run([a.cc, '-std=c11', *flags, '-Wall', '-Wextra', '-Werror', HERE/'test_policy.c', '-o', exe], check=True)
        results['policy'] = subprocess.check_output([exe], env=env, text=True).strip()
        # Exercise the actual staged free-list functions, beyond the old 512
        # extents. All 20480 possible client allocations must be recoverable.
        memory = (driver/'NativeAdrenoMemory.cpp').read_text()
        block = memory[memory.index('struct PoolExtent'):memory.index('\n}\nsize_t NativeAdrenoMemory::poolBytes()')]
        test = root/'pool.cpp'
        test.write_text('''#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
class IOBufferMemoryDescriptor;
volatile uint32_t native_adreno_pool_stats[8];
''' + block + '''
int main() {
    constexpr unsigned n=20480;
    size_t offsets[n];
    pool.free[0]={0,n*4096}; pool.count=1;
    for(unsigned i=0;i<n;++i)assert(poolTake(4096,&offsets[i]));
    assert(!pool.count && pool.used==n*4096);
    for(unsigned i=0;i<n;i+=2)poolGive(offsets[i],4096);
    assert(pool.count==n/2);
    for(unsigned i=1;i<n;i+=2)poolGive(offsets[i],4096);
    assert(pool.count==1 && !pool.used && pool.free[0].bytes==n*4096);
    size_t all=1;assert(poolTake(n*4096,&all) && !all);
    puts("PASS: 20480 fragmented BO extents coalesce without lost memory");
}
''')
        exe = root/'pool'
        subprocess.run([a.cxx, '-std=c++17', *flags, test, '-o', exe], check=True)
        results['pool_fragmentation'] = subprocess.check_output([exe], env=env, text=True).strip()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(dict(host_tests=results, inputs=inputs,
        board_source_sha256=hashlib.sha256((HERE/'MyronGpuService.cpp').read_bytes()).hexdigest(),
        native_kernel_objects_compiled=False, hardware_tested=False, metal_tested=False), indent=2)+'\n')
    print('\n'.join(results.values()))


if __name__ == '__main__':
    main()
