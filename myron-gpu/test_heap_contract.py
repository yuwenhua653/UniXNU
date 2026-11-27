#!/usr/bin/env python3
"""Check the resolved Darwin heap assignment against the native BO policy."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def check(source, headers, cxx):
    source, headers = Path(source), Path(headers)
    text = (source/'src/freedreno/vulkan/tu_knl_darwin.cc').read_text()
    assert '#include "MyronGpuPolicy.h"' in text
    rows = [line.strip() for line in text.splitlines() if 'device->heap.size =' in line]
    assert len(rows) == 1 and 'myron_gpu_heap_bytes(' in rows[0]
    # Compile the actual resolved assignment and the same policy header the
    # native allocator uses; no Metal/Vulkan device is substituted or claimed.
    fixture = '''#include "MyronGpuPolicy.h"
#include <cassert>
#include <cstdint>
#include <initializer_list>
struct Device { struct { uint64_t size; } heap; };
static uint64_t system_heap;
static uint64_t tu_get_system_heap_size(Device *) { return system_heap; }
static uint64_t advertised() {
 Device object{}; Device *device=&object;
''' + rows[0] + '''
 return device->heap.size;
}
int main() {
 constexpr uint64_t cap=uint64_t(MYRON_GPU_POOL_MIB)*1024*1024+MYRON_GPU_OVERFLOW_BYTES;
 static_assert(cap==384ULL*1024*1024);
 for(uint64_t value:{uint64_t(0),uint64_t(1),cap-1,cap,cap+1,2ULL*1024*1024*1024,UINT64_MAX}) {
  system_heap=value;
  assert(advertised()==(value<cap?value:cap));
 }
}
'''
    # Normalize integer types for platforms whose uint64_t is unsigned long.
    fixture = fixture.replace('2ULL*1024*1024*1024,UINT64_MAX', 'uint64_t(2)*1024*1024*1024,uint64_t(UINT64_MAX)')
    with tempfile.TemporaryDirectory(prefix='myron-heap-') as tmp:
        root=Path(tmp); test=root/'heap.cpp';test.write_text(fixture)
        subprocess.run([cxx,'-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=undefined',
                        '-I',headers,test,'-o',root/'heap'],check=True)
        subprocess.run([root/'heap'],check=True)
    print('PASS: actual Darwin heap assignment matches native capacity and clamps smaller system heaps')


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--headers',type=Path,required=True);p.add_argument('--cxx',default='c++')
    a=p.parse_args();check(a.source,a.headers,a.cxx)
