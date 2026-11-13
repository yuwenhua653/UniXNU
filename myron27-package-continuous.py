#!/usr/bin/env python3
"""Package a qualified continuous candidate with the existing Android restore guards."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--candidate',type=Path,required=True);p.add_argument('--run',type=int,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();source=Path(__file__).resolve().parent/'myron-device-test'
sys.path.insert(0,str(source));import myron_boot_update as old
sha=lambda x:hashlib.sha256(x).hexdigest()
mraw=(a.candidate/'deployment.json').read_bytes();m=json.loads(mraw)
r=json.loads((a.candidate/'continuous-report.json').read_text());image=(a.candidate/'root-startup.img').read_bytes()
assert r['result']=='passed' and r['kind']=='continuous-xnu-source-boot' and r['intentional_stop'] is False
assert m['continuous_boot']['intentional_stop'] is False and 'entry_observer' not in m
assert sha(image)==r['boot_sha256']==m['files']['root-startup.img']['sha256']
assert len(image)==old.BOOT_BYTES==m['files']['root-startup.img']['bytes']
assert r['root_handoff']['result']==r['firmware_verification']['result']=='passed'
assert r['root_handoff']['kernel_sha256']==r['kernel_sha256']==m['continuous_boot']['kernel_sha256']
assert r['assembly_run']==str(a.run) and r['root_install_reusable'] is True
for name,descriptor in old.RETAINED.items():assert m['files'][name]==descriptor
code=(source/'myron_boot_update.py').read_text()
for before,after in [('RUN = '+str(old.RUN),'RUN = '+str(a.run)),(old.MANIFEST_SHA,sha(mraw)),(old.BOOT_SHA,sha(image))]:
    assert code.count(before)==1;code=code.replace(before,after)
code=code.replace('Record the last B001-B017 / B0FF / 2700-2704 phase, text or coloured lines.',
                  'Continuous boot: record the final visible stage and kernel error; no intentional 2716 stop.')
folder='continuous-boot-'+str(a.run)
menu=(source/'UPDATE-BOOT.cmd').read_text().replace('boot-update-'+str(old.RUN),folder).replace(str(old.RUN),str(a.run)).replace('Linux/Clang 18 boot comparison','continuous XNU boot').replace('START-IOS27-LINUX-README-CN.txt','START-IOS27-CONTINUOUS-README-CN.txt')
guide='''myron iOS27 连续启动版

这版取消 2716 主动停机，从 C 初始化继续运行到后续启动阶段。
显示连续内核日志；真机进入桌面尚未验证。
复用已安装的 unixnu，只更新原备份对应槽位的 boot。

将本包解压到原测试目录，START-IOS27-CONTINUOUS.cmd 与原 package、state 同层。
保留原 Android boot 备份、deployment.json、root-install.json 和全部原状态。
打开 START-IOS27-CONTINUOUS.cmd：
1 校验文件、原备份和安装记录。
2 手机进入 bootloader fastboot 后更新 boot；完整输入 START IOS。
UniXNU 菜单选第一项，按住音量＋约一秒后松开。
若启动停住，拍清最后一屏日志；不要再次重装 unixnu。
需要回 Android 时进入 bootloader fastboot，选 3，输入 RESTORE ANDROID。
恢复功能使用原 Android boot 备份，不依赖新镜像能否启动。

任何校验失败均保留错误日志，不修改 state 绕过检查。
本包不重分区、不切槽，不创建替代 Android 备份。
'''
with tempfile.TemporaryDirectory() as temp:
    d=Path(temp)
    for name in ('myron_device_test.py','device_layout.py','prepare_root_bundle.py','test_boot_update.py','test_companion.py'):
        shutil.copyfile(source/name,d/name)
    (d/'myron_boot_update.py').write_text(code)
    # Execute the packaged helper itself with fake devices before exporting it.
    subprocess.run([sys.executable,str(d/'test_boot_update.py')],cwd=d,check=True)
    spec=importlib.util.spec_from_file_location('continuous_update',d/'myron_boot_update.py')
    u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u);u.verify_release(a.candidate)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,text in [('START-IOS27-CONTINUOUS.cmd',menu),('START-IOS27-CONTINUOUS-README-CN.txt',guide)]:
            z.writestr(name,text.replace('\r\n','\n').replace('\n','\r\n').encode())
        z.writestr(folder+'/myron_boot_update.py',code)
        for name in ('myron_device_test.py','device_layout.py','prepare_root_bundle.py'):z.write(d/name,folder+'/'+name)
        for name in ('deployment.json','root-startup.img','continuous-report.json'):z.write(a.candidate/name,folder+'/'+name)
    with zipfile.ZipFile(a.output) as z:
        assert z.testzip() is None;z.extractall(d/'readback')
    u.verify_release(d/'readback'/folder)
result=dict(file=a.output.name,bytes=a.output.stat().st_size,sha256=sha(a.output.read_bytes()),run=a.run,
            native_producer=r['producer'],phone_tested=False,desktop_reached=False)
a.output.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
