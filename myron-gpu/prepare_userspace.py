#!/usr/bin/env python3
"""Resolve the iPhone27/A840 userspace build separately from the boot image.

Use the official arm64e/Rust PAC build, the board's exact 128-IB wire header,
and its recorded Mesa patches. Never import the iPad QuartzCore address writes
or A740 command replay. This does not publish an accelerator or modify Data.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'myron-gpu/native'))
from prepare_sources import pinned, replace
from userspace_contract import verify_abi

RECIPES = (
    'build-adreno-metal-plugin.py', 'build-adreno-metal-bridge.py',
    'gen-turnip-smoke-shaders.py', 'rust-pac-rewrite.py',
    'macho-self-bind-weak-imports.py', 'make-gpu-addon.py',
    'data/gpu-metal-vulkan-inputs.json',
)


def fetch(path, pin):
    if not (path/'.git').exists():
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', path], check=True)
        subprocess.run(['git', '-C', path, 'fetch', '--depth=1', pin['url'], pin['commit']], check=True)
        subprocess.run(['git', '-C', path, 'checkout', '-q', '--detach', 'FETCH_HEAD'], check=True)
    pinned(path, pin)


def prepare(refs, native_refs, out, download=False):
    pins = json.loads((ROOT/'myron-gpu/userspace-inputs.json').read_text())
    native = json.loads((ROOT/'myron-gpu/native/dependencies.json').read_text())
    for name, pin in pins.items():
        if download: fetch(refs/name, pin)
        pinned(refs/name, pin)
    for name in ('NativeAdreno', 'AdrenoPM4'):
        if download: fetch(native_refs/name, native[name])
        pinned(native_refs/name, native[name])
    abi = verify_abi(native_refs/'NativeAdreno')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a fresh userspace output directory; existing sources are not overwritten')
    out.mkdir(parents=True, exist_ok=True)
    def copy(source, relative):
        destination = out/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for name in RECIPES:
        copy(refs/'UniXNU/scripts'/name, 'scripts/'+name)
    for name in ('build-turnip-darwin.py', 'mesa_patch_identity.py',
                 'data/adreno-compiler-inputs.json', 'requirements-adreno-compiler.txt'):
        copy(ROOT/'scripts'/name, 'scripts/'+name)
    for name in json.loads((ROOT/'scripts/data/adreno-compiler-inputs.json').read_text())['patches']:
        copy(ROOT/name, name)
    copy(ROOT/'myron-gpu/native/userspace_contract.py', 'myron-gpu/native/userspace_contract.py')
    # The upstream recipes record the actual component commit through git.
    subprocess.run(['git', 'clone', '-q', '--no-hardlinks', str(refs/'AdrenoMetal'),
                    str(out/'drivers/AdrenoMetal')], check=True)
    for name in ('NativeAdreno', 'AdrenoPM4'):
        prefix = 'drivers/NativeAdreno' if name == 'NativeAdreno' else 'kits/AdrenoPM4'
        for source in (native_refs/name).iterdir():
            if source.is_file() and source.suffix in ('.h', '.c'):
                copy(source, prefix+'/'+source.name)
    copy(ROOT/'myron-gpu/native/MyronGpuMailbox.h', 'drivers/NativeAdreno/MyronGpuMailbox.h')
    recipe = out/'scripts/build-adreno-metal-plugin.py'
    text = recipe.read_text().replace("ROOT / 'drivers/Adreno740'", "ROOT / 'drivers/NativeAdreno'")
    text = replace(text, "args = parser.parse_args()", "args = parser.parse_args()\n"
                   "if args.target != 'ios27': raise SystemExit('This resolved tree is iPhone27/A840 only')\n"
                   "args.no_replay = True")
    text = replace(text, "'-fstack-protector-strong']", "'-fstack-protector-strong', '-DNATIVE_MYRON_IPHONE27=1']")
    recipe.write_text(text)
    plugin = out/'drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm'
    text = plugin.read_text()
    # Exact source boundary: keep common API/env behavior, exclude all of the
    # foreign-address writes AND the delayed direct-address diagnostic reader.
    text = replace(text, '#if !TARGET_OS_OSX\n        // The stored option values',
                   '#if !TARGET_OS_OSX && !defined(NATIVE_MYRON_IPHONE27)\n        // The stored option values')
    plugin.write_text(text)
    frontend = out/'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm'
    text = frontend.read_text()
    start = text.index('static std::string quartzCoreCallers() {')
    end = text.index('// What a creation cost', start)
    text = text[:start] + '#if defined(NATIVE_MYRON_IPHONE27)\n' + \
        'static std::string quartzCoreCallers() { return "qc target-offsets-unavailable"; }\n#else\n' + \
        text[start:end] + '#endif\n' + text[end:]
    frontend.write_text(text)
    transport = out/'drivers/AdrenoMetal/NativeAdrenoUserTest.h'
    text = replace(transport.read_text(), '#include "NativeAdrenoABI.h"',
                   '#include "NativeAdrenoABI.h"\n#include "MyronGpuMailbox.h"')
    text = replace(text, '    uint32_t mailboxSeq = 0;',
                   '    uint32_t mailboxSeq = 0;\n    bool mailboxFailed = false;\n'
                   '    pthread_mutex_t mailboxLock = PTHREAD_MUTEX_INITIALIZER;')
    text = replace(text, 'if (!mailbox || is > 0x700 || os > 0x700)',
                   'if (!mailbox || mailboxFailed || is > MyronMailboxInputBytes || os > MyronMailboxOutputBytes)')
    text = replace(text, 'mailbox) + 0x10, in, is', 'mailbox) + MyronMailboxInputOffset / 4, in, is')
    text = replace(text, 'const uint32_t seq = ++mailboxSeq;',
                   'if (++mailboxSeq == 0) ++mailboxSeq;\n        const uint32_t seq = mailboxSeq;')
    text = replace(text, '        mailbox[1] = seq;',
                   '        __atomic_store_n(mailbox + 1, seq, __ATOMIC_RELEASE);')
    text = text.replace('mailbox[2] != seq', '__atomic_load_n(mailbox + 2, __ATOMIC_ACQUIRE) != seq')
    text = replace(text, 'if (__atomic_load_n(mailbox + 2, __ATOMIC_ACQUIRE) != seq) return -2;',
                   'if (__atomic_load_n(mailbox + 2, __ATOMIC_ACQUIRE) != seq) { mailboxFailed = true; return -2; }')
    text = replace(text, 'mailbox) + 0x200, os', 'mailbox) + MyronMailboxOutputOffset / 4, os')
    text = replace(text, '        if (mailbox) return mailboxMethod(m, in, is, out, os);',
                   '        if (mailbox) {\n            pthread_mutex_lock(&mailboxLock);\n'
                   '            int status = mailboxMethod(m, in, is, out, os);\n'
                   '            pthread_mutex_unlock(&mailboxLock);\n            return status;\n        }')
    text = replace(text, 'return mailbox[0] == 0x4d41494c;',
                   'if (mailbox[0] == MyronMailboxMagic) return true;\n'
                   '        unmap(conn, 0xC0DE, mach_task_self(), address);\n'
                   '        mailbox = nullptr;\n        return false;')
    transport.write_text(text)
    report = dict(target='iPhone12,1/24A446', architecture='arm64e', native_abi=abi,
                  sources={**pins, **{k: native[k] for k in ('NativeAdreno','AdrenoPM4')}},
                  a740_replay=False, foreign_quartzcore_access=False,
                  accelerator_published=False, data_seed_modified=False,
                  source_sha256={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(out.rglob('*')) if p.is_file() and '.git' not in p.parts})
    (out/'userspace-source.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--native-references', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--fetch', action='store_true')
    a = parser.parse_args()
    prepare(a.references.resolve(), a.native_references.resolve(), a.out.resolve(), a.fetch)
    print('Prepared iPhone27/A840 userspace sources; not compiled or installed')
