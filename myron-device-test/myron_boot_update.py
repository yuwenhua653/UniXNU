#!/usr/bin/env python3
"""Boot-only regression probe for an already verified run 43165530177 install.

Uses the existing Android backup and complete root-install receipt. Does not
read/write unixnu, re-check live GPT, switch slots, or create a new backup.
"""
import argparse
from pathlib import Path
import re
import struct
import myron_device_test as t

RUN = 43349357896
MANIFEST_SHA = '09454c2348ec41420d2a9c90656bc9746d11b18a9352f9b572e96eedceac6429'
BOOT_SHA = 'a251b4eaf6f17feff09aed144259aafbc28dde01ec9508269184b6a1cb2b1735'
BOOT_BYTES = 95428608
RETAINED = {
    'root-container.raw': dict(bytes=15092154368, sha256='7d3b1200d14e4f27f12ef1680184033b0f95035475635f57c5b4130c28cdb81c'),
    'policy-carrier.bin': dict(bytes=117911552, sha256='4e733b6230b29d409860a0d2cd8d05d23a60ab9b54ab6cb1662c777a4205da16'),
}


def verify_release(update):
    update = Path(update)
    t.require(t.sha(t.regular(update/'deployment.json')) == MANIFEST_SHA,
              'Wrong boot-update deployment manifest')
    m = t.load(update/'deployment.json')
    t.require(m.get('format') == 1 and m.get('device') == 'myron' and
              m.get('partition') == 'unixnu' and m.get('device_bound') is True and
              m.get('qualification_only') is False, 'Wrong boot-update device')
    for name, expected in RETAINED.items():
        t.require(m['files'][name] == expected, 'Boot update needs a different installed '+name)
    t.require(m['files']['root-startup.img'] == dict(bytes=BOOT_BYTES, sha256=BOOT_SHA),
              'Wrong startup image descriptor')
    image = t.regular(update/'root-startup.img')
    t.require(image.stat().st_size == BOOT_BYTES and t.sha(image) == BOOT_SHA,
              'Startup image changed or incomplete')
    with image.open('rb') as f:
        header = f.read(4096)
    t.require(len(header) >= 44 and header[:8] == b'ANDROID!' and
              struct.unpack_from('<I', header, 40)[0] == 4, 'Expected Android boot v4')
    return m


def check(package, state, update):
    package, state = Path(package), Path(state)
    b = t.backup_state(state)
    t.require(t.sha(t.regular(package/'deployment.json')) == b['manifest_sha256'],
              'Original deployment differs from Android backup session')
    old = t.load(package/'deployment.json')
    m = verify_release(update)
    for key in ('layout', 'geometry', 'root_writes', 'trusted_anchor_sha256',
                'root_bundle_sha256', 'history_binding_sha256'):
        t.require(key in old and old[key] == m[key], 'Installed root identity differs: '+key)
    t.require(b['layout'] == m['layout'], 'Backup layout differs from update')
    for name, expected in RETAINED.items():
        t.require(old['files'][name] == expected, 'Installed file differs: '+name)
    r = t.load(state/'root-install.json')
    t.require(r.get('format') == 1 and r.get('complete') is True and r.get('run') == t.RUN,
              'Root installation is incomplete or from another build')
    for key in ('serial', 'slot', 'manifest_sha256', 'capture_binding'):
        t.require(r.get(key) == b[key], 'Root installation session differs: '+key)
    expected_chunks = []
    for row in m['root_writes']:
        for offset in range(0, row['bytes'], t.CHUNK):
            expected_chunks.append((row['file'], offset, min(t.CHUNK, row['bytes']-offset)))
    chunks = r.get('chunks', [])
    t.require(len(chunks) == len(expected_chunks), 'Incomplete root readback receipt')
    for chunk, expected in zip(chunks, expected_chunks):
        t.require((chunk.get('file'), chunk.get('offset'), chunk.get('bytes')) == expected and
                  re.fullmatch('[0-9a-f]{64}', chunk.get('sha256', '')) is not None,
                  'Invalid root readback chunk receipt')
    t.require(BOOT_BYTES <= b['boot_bytes'], 'Startup image exceeds backed-up boot partition')
    print('Boot update, original Android backup and completed install receipt verified.')
    print('Installed unixnu is reused; this check does not re-read the phone or its GPT.')
    return b


def start(package, state, update, fastboot_factory):
    b = check(package, state, update)
    fb = fastboot_factory(b)  # Same serial, product, slot, unlock and partition-size checks.
    record = dict(format=1, run=RUN, source_run=t.RUN, serial=b['serial'], slot=b['slot'],
                  manifest_sha256=MANIFEST_SHA, boot_sha256=BOOT_SHA,
                  flash_started=True, flash_completed=False, reboot_completed=False)
    path = Path(state)/'boot-update-attempt.json'
    t.save(path, record)
    fb.flash(b['boot_name'], Path(update)/'root-startup.img')
    record['flash_completed'] = True
    t.save(path, record)
    fb.reboot()
    record['reboot_completed'] = True
    t.save(path, record)
    print('Boot probe started. Record the last 2700-2704 phase, text or coloured lines.')
    print('If stuck, enter bootloader fastboot and restore the saved Android boot.')


def fastboot(backup):
    # Also support platform-tools beside the original menu, not only this subfolder.
    for path in (Path('fastboot.exe'), Path('platform-tools/fastboot.exe')):
        if path.is_file():
            return t.Fastboot(str(path.resolve()), backup)
    return t.Fastboot(t.tool('fastboot'), backup)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('check', 'start', 'restore'))
    p.add_argument('--package', type=Path, default=Path('package'))
    p.add_argument('--state', type=Path, default=Path('state'))
    p.add_argument('--update', type=Path, default=Path(__file__).resolve().parent)
    a = p.parse_args()
    if a.action == 'check':
        check(a.package, a.state, a.update)
    elif a.action == 'start':
        print('This replaces the backed-up current boot slot. Keep state and the Android backup.')
        t.confirm('START IOS')
        start(a.package, a.state, a.update, fastboot)
    else:
        t.confirm('RESTORE ANDROID')
        # Restore must work even when the update or original package is missing.
        t.restore(a.state, fastboot)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as e:
        import datetime
        import traceback
        logs = Path('results'); logs.mkdir(exist_ok=True)
        report = logs/('boot-update-error-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.txt')
        report.write_text(traceback.format_exc(), encoding='utf-8')
        print('STOP:', str(e) or 'Interrupted')
        print('Error log:', report)
        print('Keep state and Android backup. No automatic retry or slot switch.')
        raise SystemExit(1)
