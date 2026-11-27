#!/usr/bin/env python3
"""Build and qualify real iOS27 Turnip, Metal bridge and signed plugin on macOS.

Output is a userspace component artifact, never a flashable phone package.
Original trust modules, accelerator bindings and display handoff must be
qualified separately before adding it to a boot image.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from prepare_userspace import fetch


def run(command, **kw):
    subprocess.run([str(x) for x in command], check=True, **kw)


def prepare_dependencies(root):
    sys.path.insert(0, str(root/'scripts'))
    from mesa_patch_identity import validate_recorded_patches
    pins = json.loads((root/'scripts/data/adreno-compiler-inputs.json').read_text())
    mesa = root/'.cache/mesa-work'
    if not (mesa/'.git').exists():
        mesa.mkdir(parents=True, exist_ok=True)
        run(['git', 'init', '-q', mesa])
        run(['git', '-C', mesa, 'fetch', '--depth=1', '--filter=blob:none',
             pins['mesa']['mirror'], pins['mesa']['commit']])
        run(['git', '-C', mesa, 'sparse-checkout', 'set', *pins['mesa']['sparse_directories']])
        run(['git', '-C', mesa, 'checkout', '-q', '--detach', 'FETCH_HEAD'])
    read = lambda args: subprocess.check_output(args, text=True).strip()
    for ref, expected in [('HEAD', pins['mesa']['commit']), ('HEAD^{tree}', pins['mesa']['tree'])]:
        if read(['git', '-C', mesa, 'rev-parse', ref]) != expected:
            raise ValueError('Mesa commit/tree differs')
    clean = subprocess.run(['git','-C',mesa,'diff','--quiet','HEAD']).returncode == 0
    if clean and not read(['git','-C',mesa,'ls-files','--others','--exclude-standard']):
        for patch in pins['patches']: run(['git','-C',mesa,'apply',root/patch])
    validate_recorded_patches(root, mesa, pins)
    venv = root/'.cache/mesa-venv'
    if not (venv/'bin/python').exists(): run([sys.executable,'-m','venv',venv])
    run([venv/'bin/pip','install','-r',root/'scripts/requirements-adreno-compiler.txt'])
    prefix = Path(read(['brew','--prefix','bison']))
    bison = prefix/'bin/bison'
    version = read([str(bison),'--version']).splitlines()[0]
    if not re.search(r'\b3\.(?:[7-9]|[1-9][0-9])', version):
        raise ValueError('Bison 3.7 or newer required')
    tools = root/'.cache/mesa-tools/bin'
    tools.mkdir(parents=True, exist_ok=True)
    (tools/'bison').unlink(missing_ok=True)
    (tools/'bison').symlink_to(bison)
    translator = json.loads((root/'scripts/data/gpu-metal-vulkan-inputs.json').read_text())['translator']
    source = root/'.cache/gpu-reference/metal2vulkan'
    # A repeat build may already have the official patches; the bridge recipe
    # verifies their exact intermediate/final git trees before compiling.
    if not (source/'.git').exists():
        fetch(source, dict(url=translator['repository'], commit=translator['commit']))
    if read(['git','-C',source,'rev-parse','HEAD']) != translator['commit']:
        raise ValueError('Translator commit differs')
    for name, digest in translator['files'].items():
        data = subprocess.check_output(['git','-C',source,'show','HEAD:'+name])
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Translator input differs: '+name)


def audit_image(path, expected_type):
    data = path.read_bytes()
    magic, cpu, subtype, kind = struct.unpack_from('<4I',data)
    if (magic,cpu,subtype & 0xffffff,kind) != (0xfeedfacf,0x100000c,2,expected_type):
        raise ValueError('Expected thin arm64e Mach-O of the selected type: '+str(path))
    count, command_bytes = struct.unpack_from('<II',data,16)
    cursor, platforms = 32, []
    if command_bytes > len(data)-32: raise ValueError('Truncated Mach-O commands')
    for _ in range(count):
        if cursor+8 > 32+command_bytes: raise ValueError('Truncated Mach-O command')
        command, size = struct.unpack_from('<II',data,cursor)
        if size < 8 or cursor+size > 32+command_bytes: raise ValueError('Invalid Mach-O command')
        if command == 0x32:
            if size < 24: raise ValueError('Truncated build-version command')
            platforms.append(struct.unpack_from('<II',data,cursor+8))
        cursor += size
    if cursor != 32+command_bytes or platforms != [(2,27 << 16)]:
        raise ValueError('Expected actual iOS 27.0 build target, not a host or iPadOS17 artifact')
    run(['codesign','--verify','--strict',path])
    detail = subprocess.run(['codesign','-d','--verbose=4',path],capture_output=True,text=True,check=True).stderr
    digest = re.search(r'^CDHash=([0-9a-f]{40})$',detail,re.M)
    if not digest or not re.search(r'^Page size=4096$',detail,re.M):
        raise ValueError('Missing 4 KiB owner signature: '+str(path))
    return dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),cdhash=digest[1],
                arm64e=True,platform='iOS',minimum_os='27.0')


def build(root):
    source = json.loads((root/'userspace-source.json').read_text())
    for name,digest in source['source_sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Resolved source changed: '+name)
    prepare_dependencies(root)
    # Exercise the exact patched Mesa macros before starting the macOS build.
    from test_turnip_dynamic_state import check as check_dynamic_state
    check_dynamic_state(root/'.cache/mesa-work', 'clang++')
    from test_heap_contract import check as check_heap_contract
    check_heap_contract(root/'.cache/mesa-work', root/'drivers/NativeAdreno', 'clang++')
    run([sys.executable,root/'scripts/build-turnip-darwin.py','--target','ios27',
         '--native-adreno',root/'drivers/NativeAdreno'],cwd=root)
    run([sys.executable,root/'scripts/build-adreno-metal-plugin.py','--target','ios27','--no-replay'],cwd=root)
    plugin = root/'build/adreno-metal-plugin27'
    bundle = plugin/'NativeAdrenoMetal.bundle'
    trust = json.loads((plugin/'trust.json').read_text())
    images = {}
    for name,kind,key in [('NativeAdrenoMetal',8,'cdhash'),('libvulkan_freedreno.dylib',6,'turnip_cdhash')]:
        images[name] = audit_image(bundle/name,kind)
        if images[name]['cdhash'] != trust[key]: raise ValueError('Plugin trust does not match signed bytes')
    addon = plugin/'gpuaddon-candidate.bin'
    addon.unlink(missing_ok=True)
    run([sys.executable,root/'scripts/make-gpu-addon.py','--no-daemon',addon],
        env=dict(os.environ,ADRENO_PLUGIN_DIR=str(plugin)),cwd=root)
    report = dict(target=source['target'],sources=source['sources'],native_abi=source['native_abi'],
                  images=images,source_manifest_sha256=hashlib.sha256((root/'userspace-source.json').read_bytes()).hexdigest(),
                  addon_sha256=hashlib.sha256(addon.read_bytes()).hexdigest(),
                  addon_bytes=addon.stat().st_size,compiled=True,installed=False,
                  hardware_tested=False,accelerator_published=False,
                  original_trust_bundle_merged=False,data_seed_modified=False)
    (plugin/'myron-userspace-build.json').write_text(json.dumps(report,indent=2)+'\n')
    shutil.copyfile(root/'userspace-source.json',plugin/'myron-userspace-source.json')
    print('PASS: signed arm64e A840 userspace built; not a boot image or hardware validation')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tree',type=Path,required=True)
    a=p.parse_args()
    build(a.tree.resolve())
