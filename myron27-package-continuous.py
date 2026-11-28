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
from myron_continuous_contract import DISPLAY_SYMBOLS,DISPLAY_ARGUMENTS
assert all(r['display_definitions'].get(name) for name in DISPLAY_SYMBOLS)
assert set(r['display_arguments'])==DISPLAY_ARGUMENTS and r['display_runtime_qualified'] is False
display_delta=json.loads((Path(__file__).resolve().parent/'myron27-display-delta.json').read_text())
display_license=display_delta['files']['device/myron27/display/LICENSE']
assert sha(display_license['content'].encode())==display_license['sha256']
assert r['result']=='passed' and r['kind']=='continuous-xnu-source-boot' and r['intentional_stop'] is False
assert m['continuous_boot']['intentional_stop'] is False and 'entry_observer' not in m
assert sha(image)==r['boot_sha256']==m['files']['root-startup.img']['sha256']
assert len(image)==old.BOOT_BYTES==m['files']['root-startup.img']['bytes']
assert r['root_handoff']['result']==r['firmware_verification']['result']=='passed'
assert r['root_handoff']['kernel_sha256']==r['kernel_sha256']==m['continuous_boot']['kernel_sha256']
assert r['assembly_run']==str(a.run) and r['root_install_reusable'] is True
for name,descriptor in old.RETAINED.items():assert m['files'][name]==descriptor
# Bind the recovery reader to the same checked deployment and log window.
log_report=json.loads((a.candidate/'persistent-log.json').read_text())
log_files=('myron_read_log.py','device_layout.py','READ-IOS27-LOG.cmd','LOG-CAPTURE.md')
assert log_report['format']==1 and log_report['writer']=='SHLOG001-v5-myron-1'
assert log_report['source_commit']==m['continuous_boot']['source_commit']
assert log_report['partition']=='unixnu' and log_report['blocks']==128 and log_report['block_bytes']==4096
assert set(log_report['files'])==set(log_files)
for name in log_files:assert sha((a.candidate/name).read_bytes())==log_report['files'][name]
spec=importlib.util.spec_from_file_location('checked_log_reader',a.candidate/'myron_read_log.py')
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
assert log_report['first_lba']==reader.window(m)
assert log_report['carrier_gap_bytes']==(log_report['first_lba']-m['layout']['first'])*4096-m['geometry']['carrierOffset']-m['geometry']['carrierCapacity']
log_symbols={'_myron_boot_log_snapshot','_myron_log_state','_myron_log_rounds','_myron_log_errors','_myron_log_first_lba'}
assert all(r['buffer_trace_definitions'].get(name) for name in log_symbols)
log_folder='log-capture-'+str(a.run)
log_menu='\n'.join([
    '@echo off','setlocal',
    'pushd "%~dp0'+log_folder+'"',
    'if errorlevel 1 (','  echo Log reader directory missing. Extract the complete package.','  pause','  exit /b 1',')',
    'call READ-IOS27-LOG.cmd','popd',''])
code=(source/'myron_boot_update.py').read_text()
for before,after in [('RUN = '+str(old.RUN),'RUN = '+str(a.run)),(old.MANIFEST_SHA,sha(mraw)),(old.BOOT_SHA,sha(image))]:
    assert code.count(before)==1;code=code.replace(before,after)
code=code.replace('Record the last B001-B017 / B0FF / 2700-2704 phase, text or coloured lines.',
                  'If the Apple logo persists, collect the existing recovery log before booting iOS again.')
folder='continuous-boot-'+str(a.run)
menu=(source/'UPDATE-BOOT.cmd').read_text().replace('boot-update-'+str(old.RUN),folder).replace(str(old.RUN),str(a.run)).replace('Linux/Clang 18 boot comparison','continuous XNU boot').replace('START-IOS27-LINUX-README-CN.txt','START-IOS27-CONTINUOUS-README-CN.txt')
guide='''myron iOS27 连续启动版

本版保留已有 Metal GPU、CPU 帧缓冲显示和 UFS 持久日志。
停用 46087333358 新增的系统服务缓存覆盖，恢复读取原封存系统缓存；开机恢复仍需真机验证。
保留现有 Data 和 16 GiB 底层设备选择，不回退旧 Data；这不代表 APFS 已扩容。
扩容任务尚未证实执行，应用、黑壁纸与卡顿仍待修复；不要把此包当作扩容完成版。
复用已安装的 unixnu，只更新原备份对应槽位的 boot。

将本包解压到原测试目录，START-IOS27-CONTINUOUS.cmd 与原 package、state 同层。
保留原 Android boot 备份、deployment.json、root-install.json 和全部原状态。
打开 START-IOS27-CONTINUOUS.cmd：
1 校验文件、原备份和安装记录。
2 手机进入 bootloader fastboot 后更新 boot；完整输入 START IOS。
正常启动自动进入 iOS，黑底苹果标志应保持到系统提交首帧。
若一直停在苹果标志，直接进入已有 recovery 采集启动日志。
保持手机处于 recovery，用 USB 连接电脑，运行 READ-IOS27-LOG.cmd。
需 recovery 的 root ADB；Android 本身不需要 root，使用系统 PATH 中的 adb/Python 3.11+。
发回程序显示的 myron-logs-日期时间.zip；即使提示解码失败，也请发回原始采集包。
采集前不要再次启动 iOS，以免下一次启动覆盖日志。不要重新安装或格式化 unixnu。
需要回 Android 时进入 bootloader fastboot，选 3，输入 RESTORE ANDROID。
恢复功能使用原 Android boot 备份，不依赖新镜像能否启动。

任何校验失败均保留错误日志，不修改 state 绕过检查。
本包不重分区、不切槽，不创建替代 Android 备份。
'''
if 'boot-progress=3' not in r['root_handoff']['kernel_args'].split():
    guide=guide.replace('正常启动自动进入 iOS，黑底苹果标志应保持到系统提交首帧。','此历史版本需在 UniXNU 菜单选择第一项。')
    guide=guide.replace('若一直停在苹果标志，','若启动停住，')
    code=code.replace('If the Apple logo persists,','If startup stalls,')
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
        z.writestr('LICENSE-GopFramebuffer.txt',display_license['content'].encode())
        for name,path in [('AppleKeyStoreState','device/myron27/display/AppleKeyStoreState/LICENSE'),('ProcessTrace','device/myron27/package/LICENSE-ProcessTrace.txt')]:
            license_entry=display_delta['files'][path]
            assert sha(license_entry['content'].encode())==license_entry['sha256']
            z.writestr('LICENSE-'+name+'.txt',license_entry['content'].encode())
        for name,text in [('START-IOS27-CONTINUOUS.cmd',menu),('START-IOS27-CONTINUOUS-README-CN.txt',guide),('READ-IOS27-LOG.cmd',log_menu)]:
            z.writestr(name,text.replace('\r\n','\n').replace('\n','\r\n').encode())
        z.writestr(folder+'/myron_boot_update.py',code)
        for name in ('myron_device_test.py','device_layout.py','prepare_root_bundle.py'):z.write(d/name,folder+'/'+name)
        for name in ('deployment.json','root-startup.img','continuous-report.json'):z.write(a.candidate/name,folder+'/'+name)
        for name in (*log_files,'deployment.json','persistent-log.json'):z.write(a.candidate/name,log_folder+'/'+name)
    with zipfile.ZipFile(a.output) as z:
        assert z.testzip() is None;z.extractall(d/'readback')
    u.verify_release(d/'readback'/folder)
    assert (d/'readback'/log_folder/'deployment.json').read_bytes()==mraw
    for name in log_files:assert sha((d/'readback'/log_folder/name).read_bytes())==log_report['files'][name]
    assert (d/'readback'/'READ-IOS27-LOG.cmd').is_file()
result=dict(file=a.output.name,bytes=a.output.stat().st_size,sha256=sha(a.output.read_bytes()),run=a.run,
            native_producer=r['producer'],source_commit=m['continuous_boot']['source_commit'],
            boot_sha256=sha(image),kernel_sha256=r['kernel_sha256'],
            persistent_log=log_report,phone_tested=False,desktop_reached=False)
a.output.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
