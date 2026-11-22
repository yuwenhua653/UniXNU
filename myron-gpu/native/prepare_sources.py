#!/usr/bin/env python3
"""Pin and stage the A8xx backend, with board-specific changes kept explicit."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def pinned(source, pin):
    actual = subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', source, 'status', '--porcelain', '--untracked-files=no'], text=True)
    if actual != pin['commit'] or dirty:
        raise ValueError('GPU dependency revision or tracked contents differ: ' + str(source))


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('GPU patch does not match exactly once: ' + before[:80])
    return text.replace(before, after)


def stage(references, destination):
    pins = json.loads((HERE/'dependencies.json').read_text())
    report = {}
    for name, pin in pins.items():
        source, dest = references/name, destination/name
        pinned(source, pin)
        dest.mkdir(parents=True, exist_ok=True)
        entries = subprocess.check_output(['git', '-C', source, 'ls-tree', '-z', 'HEAD']).split(b'\0')
        files = []
        for entry in entries:
            if not entry:continue
            meta, raw_name = entry.split(b'\t', 1)
            mode, kind, digest = meta.split()
            path = source/raw_name.decode()
            if path.suffix not in ('.c', '.cpp', '.h') and path.name != 'LICENSE':continue
            if kind != b'blob' or mode not in (b'100644', b'100755') or path.is_symlink():
                raise ValueError('Unexpected GPU source entry: '+str(path))
            data = path.read_bytes()
            actual = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if actual != digest.decode():raise ValueError('GPU source blob differs: '+str(path))
            files.append(path)
        extra = {p.name for p in dest.iterdir()} - {p.name for p in files}
        if extra:raise ValueError('Unexpected stale GPU sources: '+str(extra))
        for path in files:
            shutil.copyfile(path, dest/path.name)
        report[name] = dict(commit=pin['commit'], original_sha256={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    adreno = destination/'NativeAdreno'
    path = adreno/'NativeAdrenoMemory.cpp'
    text = path.read_text()
    # Four userspace clients plus the kernel test client, each 4096 objects.
    # Allow one extra free extent beyond every possible live allocation.
    # The old 512-entry limit silently lost freed extents during long sessions.
    text = replace(text, 'PoolExtent free[512];unsigned count=0;',
                   'PoolExtent free[5 * 4096 + 1];unsigned count=0;')
    text = replace(text, 'if(pool.count>=512)', 'if(pool.count>=5 * 4096 + 1)')
    # BOs must stay inside the bounded reservation, including when fragmented.
    # Internal ring/table allocations pass pooled=false and remain independent.
    text = replace(text, '    IOOptionBits options=static_cast<IOOptionBits>(kIODirectionInOut)',
                   '    if(pooled)return kIOReturnNoResources;\n'
                   '    IOOptionBits options=static_cast<IOOptionBits>(kIODirectionInOut)')
    path.write_text(text)
    path = adreno/'NativeAdrenoGpuContext.cpp'
    text = replace(path.read_text(),
                   '    if(!status)status=tables_.allocate(',
                   '    if(!status && native_adreno_pool_mib && !NativeAdrenoMemory::poolBytes())\n'
                   '        status=kIOReturnNoResources;\n'
                   '    if(!status)status=tables_.allocate(')
    path.write_text(text)
    path = adreno/'NativeAdrenoPublish.cpp'
    text = replace(path.read_text(),
                   'extern "C" void proc_selfname(char *, int);',
                   'extern "C" void proc_selfname(char *, int);\n'
                   'extern "C" volatile uint32_t myron_gpu_ready;')
    # Insert into the public connection entry, not a diagnostic/helper path.
    start = text.index('extern "C" IOReturn native_adreno_new_user_client(')
    prefix, body = text[:start], text[start:]
    brace = body.index('{') + 1
    body = body[:brace] + ('\n    if(owningTask!=kernel_task && '
        '!__atomic_load_n(&myron_gpu_ready,__ATOMIC_ACQUIRE)) {\n'
        '        if(handler)*handler=nullptr;\n'
        '        return kIOReturnNotReady;\n    }\n') + body[brace:]
    # Avoid an unresolved authenticated weak-import thunk on arm64e: this
    # board supplies the real rejecting export function in MyronGpuService.
    text = prefix + body
    text = replace(text, 'uint32_t size) __attribute__((weak_import));', 'uint32_t size);')
    text = replace(text, 'valid && boot_log_export_put?boot_log_export_put', 'valid?boot_log_export_put')
    path.write_text(text)
    report['staged_sha256'] = {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in destination.rglob('*') if p.is_file()}
    return report


def fetch(destination):
    for name, pin in json.loads((HERE/'dependencies.json').read_text()).items():
        path = destination/name
        if not (path/'.git').exists():
            path.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', 'init', '-q', path], check=True)
            subprocess.run(['git', '-C', path, 'fetch', '-q', '--depth', '1', pin['url'], pin['commit']], check=True)
            subprocess.run(['git', '-C', path, 'checkout', '-q', '--detach', 'FETCH_HEAD'], check=True)
        pinned(path, pin)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.fetch:
        fetch(args.references)
    if args.out:
        report = stage(args.references, args.out)
        (args.out/'sources.json').write_text(json.dumps(report, indent=2)+'\n')
