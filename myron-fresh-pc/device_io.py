"""Read-only recovery and single-slot boot transport, derived from the checked companion."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import zipfile
import device_layout as layout

BLOCK = 4096
CHUNK = 16 * 1024**2
require = layout.require

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def regular(path):
    p = Path(path)
    require(p.is_file() and (not p.is_symlink()), 'Missing or non-regular file: ' + str(p))
    return p

def save(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.new')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def load(path):
    p = regular(path)
    require(p.stat().st_size <= 2 * 1024 ** 2, 'Oversized metadata')
    return json.loads(p.read_text(encoding='utf-8'))

def invoke(command, timeout=120):
    r = subprocess.run(list(map(str, command)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    require(r.returncode == 0, 'Command failed: ' + str(command[0]) + ' ' + r.stderr.decode(errors='replace')[-1500:])
    return r.stdout

class Recovery:

    def __init__(self, adb):
        self.adb = adb
        rows = [r.split() for r in invoke([adb, 'devices']).decode().splitlines()[1:] if r.strip()]
        require(len(rows) == 1 and rows[0][1] in ('device', 'recovery'), 'Connect exactly one authorized recovery device')
        self.serial = rows[0][0]
        require(re.fullmatch('[A-Za-z0-9_-]+', self.serial) is not None, 'Require a USB device serial')
        require(self.shell('getprop', 'ro.product.device') == 'myron', 'Device is not myron')
        require(self.shell('id', '-u') == '0', 'Recovery needs root ADB; Android does not need root')
        require(self.shell('getprop', 'ro.bootmode') == 'recovery' or self.shell('getprop', 'init.svc.recovery') == 'running', 'Enter recovery main screen, not Android/sideload')
        self.slot = self.shell('getprop', 'ro.boot.slot_suffix').lstrip('_')
        require(self.slot in ('a', 'b'), 'Unknown recovery boot slot')

    def call(self, *args, timeout=120):
        return invoke([self.adb, '-s', self.serial, *args], timeout)

    def shell(self, *args):
        return self.call('shell', *args).decode().strip()

    def capture(self, directory):
        layout.capture(self.adb, directory, self.serial)
        disk, binding = layout.read_capture(directory)
        target = '/dev/block/sda' + str(disk['partition_index'])
        require(self.shell('readlink', '-f', '/dev/block/by-name/unixnu') == target, 'unixnu mapping changed')
        require(self.shell('cat', '/sys/class/block/' + Path(target).name + '/start') == str(disk['first'] * 8), 'Kernel start differs from GPT')
        require(self.shell('cat', '/sys/class/block/' + Path(target).name + '/size') == str(disk['partition_bytes'] // 512), 'Kernel size differs from GPT')
        devno = self.shell('cat', '/sys/class/block/' + Path(target).name + '/dev')
        mounts = self.shell('cat', '/proc/self/mountinfo')
        require(re.fullmatch('[0-9]+:[0-9]+', devno) is not None, 'Invalid unixnu device number')
        require(not any((len(line.split()) > 2 and line.split()[2] == devno for line in mounts.splitlines())), 'unixnu is mounted')
        return (disk, binding, target)

    def boot(self):
        name = 'boot_' + self.slot
        path = self.shell('readlink', '-f', '/dev/block/by-name/' + name)
        require(re.fullmatch('/dev/block/sd[a-z][1-9][0-9]*', path) is not None, 'Unexpected boot mapping')
        size = int(self.shell('blockdev', '--getsize64', path))
        require(16 * 1024 ** 2 <= size <= 256 * 1024 ** 2 and size % BLOCK == 0, 'Unexpected boot capacity')
        return (name, path, size)

    def read(self, path, offset, size):
        require(re.fullmatch('/dev/block/sd[a-z][1-9][0-9]*', path) is not None, 'Invalid block read path')
        require(offset >= 0 and offset % BLOCK == 0 and (0 < size <= CHUNK) and (size % BLOCK == 0), 'Invalid block read range')
        return layout.read_blocks(lambda *args: self.call(*args, timeout=300), path, offset // BLOCK, size // BLOCK)

def read_hash(device, path, size, output=None):
    h = hashlib.sha256()
    for off in range(0, size, CHUNK):
        raw = device.read(path, off, min(CHUNK, size - off))
        h.update(raw)
        if output:
            output.write(raw)
    return h.hexdigest()

def match_layout(disk, expected, capture, parent):
    if disk == expected:
        return
    results = Path(parent) / 'results'
    results.mkdir(exist_ok=True)
    saved = Path(tempfile.mkdtemp(prefix='gpt-mismatch-', dir=results))
    shutil.copytree(capture, saved, dirs_exist_ok=True)
    raise ValueError('Current GPT differs from successful build; capture saved: ' + str(saved))

def live(device, m, parent):
    with tempfile.TemporaryDirectory(prefix='gpt-', dir=parent) as tmp:
        capture = Path(tmp) / 'capture'
        disk, binding, target = device.capture(capture)
        match_layout(disk, m['layout'], capture, parent)
    return (binding, target)

class Fastboot:

    def __init__(self, executable, backup):
        self.exe = executable
        self.serial = backup['serial']
        rows = [r.split() for r in invoke([executable, 'devices']).decode().splitlines() if r.strip()]
        require(len(rows) == 1 and rows[0][0] == self.serial, 'Connect the same single device in bootloader fastboot')
        require(self.get('product') == 'myron', 'Fastboot product differs')
        require(self.get('is-userspace') == 'no', 'Use bootloader fastboot, not fastbootd')
        require(self.get('unlocked') in ('yes', 'true'), 'Bootloader must already be unlocked')
        require(self.get('current-slot') == backup['slot'], 'Fastboot slot changed; do not switch slots')
        require(int(self.get('partition-size:' + backup['boot_name']), 16) == backup['boot_bytes'], 'Boot partition size differs')

    def get(self, name):
        r = subprocess.run([self.exe, '-s', self.serial, 'getvar', name], capture_output=True, timeout=30)
        require(r.returncode == 0, 'Unsupported fastboot variable: ' + name)
        text = (r.stdout + r.stderr).decode(errors='replace')
        values = re.findall('^(?:\\(bootloader\\)\\s*)?' + re.escape(name) + ':\\s*(\\S+)\\s*$', text, re.M)
        require(len(values) == 1, 'Cannot parse fastboot variable: ' + name)
        return values[0]

    def flash(self, name, path):
        require(name in ('boot_a', 'boot_b'), 'Only a named boot slot may be flashed')
        invoke([self.exe, '-s', self.serial, 'flash', name, str(path)], 300)

    def reboot(self):
        invoke([self.exe, '-s', self.serial, 'reboot'])
