#!/usr/bin/env python3
"""Offline verification for this exact resumed CI candidate, not a phone test."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib
from pyfatfs.PyFat import PyFat
from myron_continuous_contract import require_buffer_trace, require_exit_trace, require_lockdown_state

root = Path(sys.argv[1])
candidate = root / 'candidate'
native = root / 'native'
sha = lambda data: hashlib.sha256(data).hexdigest()
read_json = lambda path: json.loads(path.read_text())
m = read_json(candidate / 'deployment.json')
r = read_json(candidate / 'continuous-report.json')
p = read_json(native / 'producer.json')
image = (candidate / 'root-startup.img').read_bytes()
original = (native / 'root-startup.img').read_bytes()
assert r['producer'] == p
assert p['source_commit'] == '899b2488685eb464f2c69818457474da89dae420'
assert p['run_id'] == '44014423552'
assert r['assembly_commit'] == '289430f515c5ee9549ef7b12e3a4ffb854edd420'
assert r['assembly_run'] == '44036554616'
assert r['result'] == r['firmware_verification']['result'] == r['root_handoff']['result'] == 'passed'
assert r['intentional_stop'] is False and r['phone_tested'] is False and r['desktop_reached'] is False
assert len(image) == len(original) == 95428608
assert sha(image) == r['boot_sha256'] == m['files']['root-startup.img']['sha256']
assert image[:8192] == original[:8192] and image[3153920:] == original[3153920:]
assert sha(image[8192:3153920]) == r['firmware_verification']['fd_sha256']
assert r['firmware_verification']['full_fd_unpacked']
assert r['firmware_verification']['efi_capsule_matches_qemu_executed_bytes']
assert r['root_handoff']['byte_equality_at_handoff']
assert r['root_handoff']['root_sidecar_failure_cases'] == 12
assert r['root_install_reusable']
old = read_json(native / 'deployment.json')
for name in ('root-container.raw', 'policy-carrier.bin'):
    assert m['files'][name] == old['files'][name]
fat_path = root / 'final-payload.img'
fat_path.write_bytes(image[3153920:])
fat = PyFat()
fat.open(str(fat_path), read_only=True)
def read_fat(name):
    entry = fat.root_dir.get_entry(name)
    return b''.join(fat.read_cluster_contents(c) for c in fat.get_cluster_chain(entry.get_cluster()))[:entry.filesize]
try:
    for name, digest in m['image_reports']['root-startup.img']['embedded_files'].items():
        assert sha(read_fat('/' + name)) == digest, name
    kernel = read_fat('/EFI/UniXNU/Payloads/kernel.macho')
    assert sha(kernel) == r['kernel_sha256'] == 'bd3194597f13f90c4df3684c41550424ffe31945eeeb83a778ecc30de500c549'
    assert require_buffer_trace(kernel) == r['buffer_trace_definitions']
    assert require_exit_trace(kernel) == r['exit_trace_definitions']
    assert require_lockdown_state(kernel) == r['lockdown_state_definitions']
    menu = tomllib.loads(read_fat('/EFI/UniXNU/unixnu.toml').decode())
    entry, = [e for e in menu['entry'] if e['id'] == menu['boot']['default']]
    assert menu['boot']['timeout'] == -1
    assert 'launchd_log_serial=1' in entry['args'].split()
    assert entry['args'] == r['root_handoff']['kernel_args']
finally:
    fat.close()
report = dict(result='passed', native_run=p['run_id'], assembly_run=r['assembly_run'],
              boot_sha256=sha(image), kernel_sha256=sha(kernel),
              native_payload_preserved=True, installed_root_reusable=True,
              launchd_console_enabled=True, retained_reason_definitions_checked=True,
              phone_tested=False, desktop_reached=False)
(root / 'final-verification.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
