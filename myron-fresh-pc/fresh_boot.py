#!/usr/bin/env python3
"""Standalone fresh-PC boot backup, live root verification and boot-only update."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import traceback
import device_io as io

RUN = 43544518065
MANIFEST_SHA = 'a8b96f2b88fee710f03dd7c92fcab58d08921e1c5340a3c6faf8e6405bbb52f9'
BOOT_SHA = '3e695357466baa38523b7673841d0125f1b035faba2292127e6de3d9f73b71c1'
REPORT_SHA = '60f67ea7c62f45caeee9d0d6a6ffc9d66e9a0d7538c84663421b64a7c46e8051'
BOOT_BYTES = 95428608
BASE = Path(__file__).resolve().parent.parent
require = io.require


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def tool(name):
    for p in (BASE/'platform-tools'/(name+'.exe'), BASE/(name+'.exe')):
        if p.is_file():
            return str(p.resolve())
    found = shutil.which(name)
    require(found, '未找到 '+name+'。将 platform-tools 文件夹放在 START-IOS27.cmd 旁，或加入系统 PATH。')
    return found


def verify_release(package):
    package = Path(package)
    require(io.sha(io.regular(package/'deployment.json')) == MANIFEST_SHA, 'deployment.json 不匹配本轮构建')
    require(io.sha(io.regular(package/'continuous-report.json')) == REPORT_SHA, '构建报告不匹配')
    m = io.load(package/'deployment.json')
    r = io.load(package/'continuous-report.json')
    image = io.regular(package/'root-startup.img')
    require(image.stat().st_size == BOOT_BYTES and io.sha(image) == BOOT_SHA, '启动镜像不完整或已改变')
    require(m['files']['root-startup.img'] == dict(bytes=BOOT_BYTES, sha256=BOOT_SHA), '启动镜像描述不匹配')
    require(m.get('device') == 'myron' and m.get('partition') == 'unixnu' and m.get('device_bound') is True,
            '不是本机适配包')
    require(r.get('result') == 'passed' and r.get('assembly_run') == str(RUN) and
            r.get('boot_sha256') == BOOT_SHA and r.get('intentional_stop') is False, '不是本轮连续启动构建')
    with image.open('rb') as f:
        header = f.read(4096)
    require(header[:8] == b'ANDROID!' and struct.unpack_from('<I', header, 40)[0] == 4, '启动镜像头错误')
    return m


class Android:
    def __init__(self, adb):
        self.adb = adb
        rows = [line.split() for line in io.invoke([adb, 'devices']).decode().splitlines()[1:] if line.strip()]
        require(len(rows) == 1 and rows[0][1] == 'device', '请连接一台已授权 USB 调试、能正常使用的 Android 手机')
        self.serial = rows[0][0]
        require(re.fullmatch('[A-Za-z0-9_-]+', self.serial), '需要 USB 序列号')
        require(self.shell('getprop', 'ro.product.device') == 'myron', '设备不是 myron')
        require(self.shell('getprop', 'sys.boot_completed') == '1' and
                self.shell('getprop', 'ro.bootmode') != 'recovery' and
                self.shell('getprop', 'init.svc.recovery') != 'running' and
                self.shell('uname', '-s') == 'Linux', '必须先进入正常 Android，不能把 iOS/Recovery 当成 Android 备份来源')
        self.slot = self.shell('getprop', 'ro.boot.slot_suffix').lstrip('_')
        require(self.slot in ('a', 'b'), 'Android 当前槽位未知')

    def shell(self, *args):
        return io.invoke([self.adb, '-s', self.serial, 'shell', *args]).decode().strip()

    def reboot_recovery(self):
        io.invoke([self.adb, '-s', self.serial, 'reboot', 'recovery'])


def observe_android(package, state, device):
    verify_release(package)
    state = Path(state)
    require(not (state/'backup.json').exists(), '已有备份，请保留；不要重新建立备份覆盖它')
    state.mkdir(parents=True, exist_ok=True)
    proof = dict(format=1, run=RUN, serial=device.serial, slot=device.slot, observed_at=now(),
                 manifest_sha256=MANIFEST_SHA, android_boot_completed=True,
                 fingerprint=device.shell('getprop', 'ro.build.fingerprint'))
    require(bool(proof['fingerprint']), 'Android 系统指纹为空')
    io.save(state/'android-proof.json', proof)
    device.reboot_recovery()
    print('Android 身份已记录，已请求重启 Recovery。进入 Recovery 主界面后选择 2；不要进入 sideload。')


class Recovery(io.Recovery):
    def hash_region(self, path, offset, size):
        require(re.fullmatch(r'/dev/block/sda[1-9][0-9]*', path), '只允许读取 unixnu 所在分区')
        require(offset >= 0 and offset % 4096 == 0 and size > 0 and size % 4096 == 0, '校验范围未对齐')
        # Fixed, validated block path and integer ranges only. Matching the full
        # expected digest also rejects short/error-contaminated dd output.
        cmd = f'dd if={path} bs=4096 skip={offset//4096} count={size//4096} 2>/dev/null | sha256sum'
        proc = subprocess.Popen([self.adb, '-s', self.serial, 'exec-out', cmd],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        started = time.monotonic()
        try:
            while True:
                try:
                    out, err = proc.communicate(timeout=10)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = int(time.monotonic()-started)
                    print(f'手机端仍在只读计算 SHA256，已等待 {elapsed} 秒...', flush=True)
                    require(elapsed < 1800, '手机端校验超时，尚未写入 boot')
        except BaseException:
            proc.kill(); proc.communicate()
            raise
        require(proc.returncode == 0, '手机端校验失败: '+err.decode(errors='replace')[-500:])
        match = re.fullmatch(rb'([0-9a-f]{64})\s+-\s*', out)
        require(match is not None, 'Recovery 未返回有效 SHA256；不会继续刷写')
        return match[1].decode()


def backup_state(state):
    state = Path(state)
    b = io.load(state/'backup.json')
    require(b.get('format') == 1 and b.get('run') == RUN and b.get('device') == 'myron' and
            b.get('android_confirmed') is True and b.get('double_read_verified') is True, '没有本包重新采集的有效 Android boot 备份')
    require(b.get('slot') in ('a', 'b') and b.get('boot_name') == 'boot_'+b['slot'] and
            re.fullmatch('[A-Za-z0-9_-]+', b.get('serial', '')), '备份身份/槽位错误')
    boot = io.regular(state/(b['boot_name']+'.img'))
    require(type(b.get('boot_bytes')) is int and 16*1024**2 <= b['boot_bytes'] <= 256*1024**2 and
            boot.stat().st_size == b['boot_bytes'] and io.sha(boot) == b.get('boot_sha256'), 'boot 备份已损坏或不完整')
    return b


def prepare(package, state, device):
    m = verify_release(package); state = Path(state)
    proof = io.load(state/'android-proof.json')
    require(proof.get('run') == RUN and proof.get('manifest_sha256') == MANIFEST_SHA and
            proof.get('android_boot_completed') is True and bool(proof.get('fingerprint')), '先选择 1，从正在运行的 Android 建立本次记录')
    require((device.serial, device.slot) == (proof.get('serial'), proof.get('slot')), 'Recovery 设备/槽位与刚才 Android 不一致')
    require(shutil.disk_usage(state).free > 512*1024**2, '本地至少需要 512 MiB 空间保存备份')
    if not (state/'backup.json').exists():
        capture = state/('capture-'+str(time.time_ns()))
        disk, binding, target = device.capture(capture)
        io.match_layout(disk, m['layout'], capture, state)
        name, path, size = device.boot()
        require(BOOT_BYTES <= size, 'boot 分区不足以容纳本轮镜像')
        dest = state/(name+'.img'); partial = state/(name+'.img.partial')
        require(not dest.exists() and not partial.exists(), '发现备份或中断的备份；保留当前文件，使用新的解压目录重新开始')
        print('重新读取当前 '+name+'，并进行第二次读取比对...', flush=True)
        with partial.open('xb') as f:
            digest = io.read_hash(device, path, size, f); f.flush(); os.fsync(f.fileno())
        require(digest == io.read_hash(device, path, size), '两次读取 boot 不一致；未进行设备写入')
        data = partial.read_bytes()
        require(data[:8] == b'ANDROID!' and struct.unpack_from('<I', data, 40)[0] in (3, 4), '备份不是 Android boot v3/v4')
        require(digest != BOOT_SHA and not any(marker in data for marker in
                (b'UniXNU', b'MYRON iOS27', b'Payloads/kernel.macho', b'MYRON BUFFER TRACE')), '当前 boot 含 iOS/UniXNU 镜像，不能作为 Android 恢复备份')
        require(io.live(device, m, state)[0] == binding, '备份期间 GPT 改变')
        partial.rename(dest)
        io.save(state/'backup.json', dict(format=1, run=RUN, device='myron', serial=device.serial,
                slot=device.slot, boot_name=name, boot_path=path, boot_bytes=size, boot_sha256=digest,
                manifest_sha256=MANIFEST_SHA, layout=disk, capture_binding=binding,
                android_confirmed=True, double_read_verified=True, created_at=now()))
        print('新 Android boot 备份已保存：'+str(dest), flush=True)
    b = backup_state(state)
    require((b['serial'], b['slot'], b['manifest_sha256']) == (device.serial, device.slot, MANIFEST_SHA), '备份会话不匹配')
    binding, target = io.live(device, m, state)
    require(binding == b['capture_binding'] and b['layout'] == m['layout'], '当前 GPT 与新备份不匹配')
    name, boot, size = device.boot()
    require((name, size) == (b['boot_name'], b['boot_bytes']) and io.read_hash(device, boot, size) == b['boot_sha256'], '手机 boot 已改变；停止操作')
    (state/'root-check.json').unlink(missing_ok=True)
    verified = []
    for row in m['root_writes']:
        print(f"只读校验手机现有 {row['file']} ({row['bytes']/1024**3:.2f} GiB)，不传回电脑、不重装分区...", flush=True)
        require(row['partition_offset']+row['bytes'] <= m['layout']['partition_bytes'], '根分区校验范围错误')
        digest = device.hash_region(target, row['partition_offset'], row['bytes'])
        require(digest == m['files'][row['file']]['sha256'], '手机现有 '+row['file']+' 与本轮不匹配；已保留新 boot 备份，未刷入任何东西')
        verified.append(dict(file=row['file'], bytes=row['bytes'], sha256=digest, partition_offset=row['partition_offset']))
    require(io.live(device, m, state)[0] == binding and io.read_hash(device, boot, size) == b['boot_sha256'], '校验期间分区或 boot 发生改变')
    io.save(state/'root-check.json', dict(format=1, run=RUN, complete=True, serial=b['serial'], slot=b['slot'],
            manifest_sha256=MANIFEST_SHA, capture_binding=binding, boot_sha256=b['boot_sha256'],
            verified=verified, verified_at=now(), method='live-recovery-full-region-sha256'))
    print('新备份和现有 unixnu 全量校验通过。现在手动进入 bootloader fastboot，再选择 3。设备写入：0。')


def ready(package, state):
    m = verify_release(package); b = backup_state(state); r = io.load(Path(state)/'root-check.json')
    require(b.get('manifest_sha256') == MANIFEST_SHA and b.get('layout') == m['layout'] and BOOT_BYTES <= b['boot_bytes'], '备份与当前镜像不匹配')
    require(r.get('complete') is True and r.get('run') == RUN and
            r.get('method') == 'live-recovery-full-region-sha256', '请先完成本次 Recovery 全量校验')
    for key in ('serial', 'slot', 'manifest_sha256', 'capture_binding', 'boot_sha256'):
        require(r.get(key) == b.get(key), '现场校验记录不属于当前备份：'+key)
    expected = [dict(file=x['file'], bytes=x['bytes'], partition_offset=x['partition_offset'],
                     sha256=m['files'][x['file']]['sha256']) for x in m['root_writes']]
    require(r.get('verified') == expected, '根分区现场校验记录不完整')
    return b


def start(package, state, factory):
    b = ready(package, state); fb = factory(b)
    attempt = dict(run=RUN, serial=b['serial'], slot=b['slot'], boot_sha256=BOOT_SHA,
                   flash_started=True, flash_completed=False, reboot_completed=False, time=now())
    path = Path(state)/'boot-attempt.json'; io.save(path, attempt)
    fb.flash(b['boot_name'], Path(package)/'root-startup.img')
    attempt['flash_completed'] = True; io.save(path, attempt)
    fb.reboot(); attempt['reboot_completed'] = True; io.save(path, attempt)
    print('已刷入本轮 boot 并重启。若停住，拍摄最后一屏；回到 fastboot 选择 4 恢复 Android。')


def restore(state, factory):
    # Intentionally independent of payload, deployment and root-check files.
    b = backup_state(state); fb = factory(b)
    fb.flash(b['boot_name'], Path(state)/(b['boot_name']+'.img'))
    fb.reboot()
    io.save(Path(state)/'restore.json', dict(run=RUN, serial=b['serial'], slot=b['slot'],
            boot_sha256=b['boot_sha256'], restored_at=now()))
    print('本次新备份的 Android boot 已恢复。')


def action(name, package, state):
    if name == 'android':
        observe_android(package, state, Android(tool('adb')))
    elif name == 'prepare':
        prepare(package, state, Recovery(tool('adb')))
    elif name == 'check':
        verify_release(package)
        if (state/'backup.json').exists(): backup_state(state)
        print('文件检查通过；这不代表手机已通过启动实测。')
    else:
        phrase = 'START IOS' if name == 'start' else 'RESTORE ANDROID'
        require(input('输入 '+phrase+' 确认：').strip() == phrase, '已取消，未刷写')
        (start(package, state, lambda b: io.Fastboot(tool('fastboot'), b)) if name == 'start'
         else restore(state, lambda b: io.Fastboot(tool('fastboot'), b)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('menu', 'android', 'prepare', 'check', 'start', 'restore'), nargs='?', default='menu')
    p.add_argument('--package', type=Path, default=BASE/'payload')
    p.add_argument('--state', type=Path, default=BASE/'state')
    a = p.parse_args()
    while True:
        name = a.action
        if name == 'menu':
            print('\nmyron iOS27 新电脑独立包 / '+str(RUN)+'\n1 确认正常 Android，并重启到 Recovery\n2 重新备份 boot + 只读校验手机现有 unixnu\n3 在 bootloader fastboot 刷入本轮 boot 并启动\n4 恢复本次备份的 Android boot\n5 检查本包文件\n0 退出')
            selected = input('选择：').strip()
            if selected == '0': return
            name = {'1':'android','2':'prepare','3':'start','4':'restore','5':'check'}.get(selected)
            if name is None: continue
        try:
            action(name, a.package, a.state)
        except (Exception, KeyboardInterrupt) as e:
            logs = BASE/'results'; logs.mkdir(exist_ok=True)
            report = logs/('error-'+str(time.time_ns())+'.txt')
            report.write_text(traceback.format_exc(), encoding='utf-8')
            print('STOP:', str(e) or '操作中断', '\n错误日志：', report)
            print('保留 state 中的新 boot 备份。不会自动重试刷写、切槽或重分区。')
            if a.action != 'menu': raise SystemExit(1)
        if a.action != 'menu': return


if __name__ == '__main__':
    main()
