#!/usr/bin/env python3
"""Package a qualified terminal observer with the established restore guards."""
import argparse,hashlib,importlib.util,json,re,sys,tempfile,zipfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--checks',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--run',type=int,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();source=Path(__file__).resolve().parents[1]/'myron-device-test'
sys.path.insert(0,str(source));import myron_boot_update as old
sha=lambda x:hashlib.sha256(x).hexdigest()
mraw=(a.candidate/'deployment.json').read_bytes();m=json.loads(mraw)
r=json.loads((a.candidate/'entry-report.json').read_text());image=(a.candidate/'root-startup.img').read_bytes()
assert r['result']=='passed' and r['probe']['terminal_stop'] is True
assert r['probe']['input_sha256']=='8c1dca686c9a99126402e59b1e5e553beb88abe4dbcf2d2a40b335bfc4e97718'
assert sha(image)==r['boot_sha256']==m['files']['root-startup.img']['sha256']
assert len(image)==old.BOOT_BYTES==m['files']['root-startup.img']['bytes']
assert m['entry_observer']['terminal_stop'] is True
assert r['root_handoff']['result']=='passed' and r['firmware_verification']['result']=='passed'
qr=json.loads(a.checks.read_text())
assert qr['result']=='passed' and qr['actual_xnu_prefix_executed'] is True
assert qr['kernel_sha256']==r['probe']['output_sha256']
assert [(x['name'],x['phase'],x['result']) for x in qr['cases']]==[('prefix','0x2716','passed'),('undefined_before_tables','0x27ee','passed')]
assert r['probe']['output_sha256']==m['entry_observer']['kernel_sha256']==r['root_handoff']['kernel_sha256']
for name,descriptor in old.RETAINED.items():assert m['files'][name]==descriptor
code=(source/'myron_boot_update.py').read_text()
for before,after in [('RUN = '+str(old.RUN),'RUN = '+str(a.run)),(old.MANIFEST_SHA,sha(mraw)),(old.BOOT_SHA,sha(image))]:
 assert code.count(before)==1;code=code.replace(before,after)
code=code.replace('Record the last B001-B017 / B0FF / 2700-2704 phase, text or coloured lines.',
                  'Record the last phase. 2716 is the intentional C-entry stop, not a desktop boot.')
folder='entry-probe-'+str(a.run)
menu=(source/'UPDATE-BOOT.cmd').read_text().replace('boot-update-'+str(old.RUN),folder).replace(str(old.RUN),str(a.run)).replace('Linux/Clang 18 boot comparison','XNU entry observer - intentional stop at 2716').replace('START-IOS27-LINUX-README-CN.txt','START-XNU-ENTRY-README-CN.txt')
guide='''myron iOS27：2704 之后的 XNU 入口定位包

这是阶段定位包，不是桌面启动包。2716 是设计中的停止点，不是新的卡死。
复用已安装的 unixnu；只更新备份对应槽位的 boot。不需要重装根镜像。

1. 解压到原测试目录，使 START-XNU-ENTRY.cmd 与原 package、state 同层。
   保留所有原文件、Android boot 备份和 root-install.json。
2. 打开 START-XNU-ENTRY.cmd，先选 1 校验。
3. 手机进入 bootloader fastboot，选 2，完整输入 START IOS。
4. 在 UniXNU 菜单选择第 1 项：按住音量＋约 1 秒，再松开。
5. 拍下最后的阶段数字及色条。2716 到达后不会继续进入系统。
6. 回 bootloader fastboot，选 3，输入 RESTORE ANDROID 恢复原 Android boot。

2710：已执行 XNU 的实际入口
2711：已设置早期异常向量，即将读取启动参数
2712：已完成初始页表构建
2713：即将安装内核的指针认证密钥
2714：即将开启 MMU
2716：已到达 C 初始化入口，主动停止（尚未执行 C 初始化）
27EE：捕获到早期异常，主动停止
仍为 2704：尚未观察到 XNU 的入口标记

模拟器检查不等于真机通过。原菜单标题仍显示 dyld startup；本包内核在
首次 C 入口主动停止，不会执行到 dyld。没有自动重启、切槽或分区操作。
安装后如果改动过 unixnu、分区或更换手机/槽位，不要使用旧安装记录。
任何校验失败都应保留 results 错误日志，不修改 state 绕过检查。
'''
with tempfile.TemporaryDirectory() as temp:
 d=Path(temp);(d/'myron_boot_update.py').write_text(code)
 spec=importlib.util.spec_from_file_location('entry_update',d/'myron_boot_update.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
 u.verify_release(a.candidate)
 with zipfile.ZipFile(a.output,'w',compression=zipfile.ZIP_DEFLATED) as z:
  for name,text in [('START-XNU-ENTRY.cmd',menu),('START-XNU-ENTRY-README-CN.txt',guide)]:z.writestr(name,text.replace('\r\n','\n').replace('\n','\r\n').encode())
  z.writestr(folder+'/myron_boot_update.py',code)
  for name in ['myron_device_test.py','device_layout.py','prepare_root_bundle.py']:z.write(source/name,folder+'/'+name)
  for name in ['deployment.json','root-startup.img','entry-report.json']:z.write(a.candidate/name,folder+'/'+name)
  z.write(a.checks,folder+'/qemu-prefix.json')
 with zipfile.ZipFile(a.output) as z:
  assert z.testzip() is None
  z.extractall(d/'check')
 u.verify_release(d/'check'/folder)
print(json.dumps(dict(file=str(a.output),bytes=a.output.stat().st_size,sha256=sha(a.output.read_bytes())),indent=2))
