myron iOS27 真机测试配套工具（2026-11-13，ADB 二进制读取修复）

旧版升级：关闭菜单，将本包文件解压覆盖原工具目录中的同名文件。
保留已有 package、state、results 和所有原 ZIP；不需要重新下载 22 个分卷或重新解压设备包。
修复 GPT/boot 备份/安装回读中 dd 统计信息混入二进制输出的问题。
隔离在手机端进行；读取失败仍停止，长度、GPT CRC、双次读取及 SHA256 校验全部保留。
重新运行 MYRON-IOS27.cmd，选 2，输入 ANDROID；不要删除已有 state 绕过检查。

适用：yuwenhua653/UniXNU，codex/myron-iphone27，成功构建 43165530177。
当前结论：设备包完成编译、签名校验、镜像重装配及导出；尚未证明真机开机或进入桌面。
配套工具经过主机模拟测试，尚未在 Windows 实机与手机上执行。遇到 STOP 请保留错误日志，不跳过检查。

下载设备包（约 10.36 GB，保留至北京时间 2026-11-19 14:50）：
https://github.com/yuwenhua653/UniXNU/actions/runs/43165530177/artifacts/13922666696
原 ZIP 的 SHA256：
5147cdae6353d979ff5dcb3472cd9a71cbce3399aaf0119dc4e87b2ea87d34b0

准备
1. 将本工具包完整解压至电脑本地 NTFS 盘，例如 D:\myron-ios27-test。
2. 将上述 GitHub 原 ZIP 放在工具同目录，文件名保持 myron-ios27-device-root-package.zip。
   不要用其它工具重新压缩该 ZIP，工具会核对完整 SHA256。
   原 ZIP 加解压文件约占 26 GB；运行前建议此盘至少留有 18 GB 可用空间。
3. 安装 Python 3.11 或更新版。adb/fastboot 可直接使用系统 PATH，也可放在同目录/platform-tools 目录。
   使用 Android SDK Platform-Tools：https://developer.android.com/tools/releases/platform-tools
4. 只连接这一部 myron。手机已解锁，Android 仍能正常启动；先自行进入 Recovery 主界面。
   Recovery ADB 必须已有 uid=0 权限。这不要求 Android 安装 Magisk/KernelSU，也不会执行 adb root 或 su。
   如果手机当前 boot 已经是旧 iOS/测试镜像，先按原方法恢复可正常开机的 Android，不能把旧测试 boot 当恢复备份。

本轮建议先执行 1、2，确认现场条件
双击 MYRON-IOS27.cmd。
选 1：校验原 ZIP、解压并核对四个镜像的大小与 SHA256。
选 2：在 Recovery 下输入 ANDROID，确认刚才可正常启动 Android。
      工具会读取主备 GPT、核对 CRC/分区 GUID/32GB unixnu 边界与构建绑定，
      将当前槽位 boot 读取两遍、确认内容一致，再保存 state\boot_a.img 或 boot_b.img。
      此步骤不写手机分区、不重启、不切槽。
      成功提示为 Current GPT matched; Android boot backup saved. Device writes: 0.
      首次使用建议把结果告诉我，再继续写入测试。
      如果 GPT 不一致，请停在这里；工具不会重新分区或缩减 userdata。

完整测试步骤（选择写入项时需再次输入明确操作短语）
选 3：仍在 Recovery 主界面，输入 INSTALL UNIXNU。
      只替换已有 unixnu 中的 iOS 根镜像与尾部签名载体，不改变 GPT/userdata/Android boot。
      每次最多传输 64 MiB 到 Recovery 的 /tmp，再写入 unixnu 的预定偏移并完整回读核对。
      每块写入前重读 GPT。已匹配的块会跳过；USB 断开或校验失败会停止，保留备份与进度。
      原有 unixnu 内容会被覆盖，本工具不备份或恢复旧 iOS 根分区。
      若中断，可重新进入 Recovery 后再次选 3；程序会重新校验并逐块回读，不盲目续写。
      Android boot 此时仍未修改，可以直接恢复 Android 使用。
选 4：第 3 步完全成功后，自行进入 bootloader fastboot（不是 fastbootd），输入 START IOS。
      再核对同一设备、同一槽位、已解锁状态和 boot 容量；仅向备份对应的 boot_a/boot_b 写入 root-startup.img 后重启。
      使用带启动探针的镜像，以便拍下停住前的屏幕。不要连续反复启动测试。
      不修改 vbmeta、不禁用校验、不刷 vendor_boot/recovery、不切换槽位。
      如果 bootloader 拒绝镜像，不会尝试绕过；请保留报错并执行恢复。
选 5：测试完成或卡住时，长按电源配合音量下进入 bootloader fastboot，输入 RESTORE ANDROID。
      工具只把 state 中核对过 SHA256 的 Android boot 写回原槽位并重启。
      恢复不依赖 10GB 原包、解压 package 或安装进度，因此可优先恢复 Android。
      恢复只还原 boot；unixnu 保留本轮测试根镜像。
选 6：随时离线复查设备包完整性。

务必保留
- 整个 state 目录，尤其 boot_a.img/boot_b.img 和 backup.json。不要用第二次备份覆盖它。
- results 中的错误日志。不要删除 state 后重跑选项 2 来绕过检查。
- 手机卡住时，先恢复 Android；采集屏幕或日志不应耽误恢复。
- 反馈时先提供选项编号、终端结果、屏幕最后停留内容；不要上传整个备份镜像或整个 10GB 包。

限制
- bootloader 若不提供 is-userspace/unlocked/partition-size 等必要信息，工具会停止，不猜测。
- 没有连接手机时无法验证 Recovery 命令、USB 驱动与厂商 bootloader 的实际兼容性。
- 选项 3 覆盖 unixnu 后只提供 Android boot 恢复，不承诺旧 iOS 数据回滚。
- 旧采集只用于构建绑定；本轮现场检查用于发现分区或槽位变化。
