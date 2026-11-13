myron iOS27 Linux/Clang 18 启动对照包 — 43361559288

本次变化：使用 Linux/Clang 18 构建固件，其中 31/35 模块与旧 R90 iOS17 包逐字节相同。
保留已安装的 iOS27 根镜像、内核、完整启动 FAT 和跳转探针。
剩余 SEC、BDS、UniXNU、DarwinBoot 含版本或适配差异。
R90 包本身未标记为真机验证成功；字节一致不等于已经修复卡机。

用途：定位“小米 Logo + 四色线条”停在哪个启动阶段。尚未真机验证；
编译和模拟器通过不能证明已经进入 XNU 或桌面。

只适用于已完成 43165530177 unixnu 安装并显示
“unixnu installed and read back”的同一台 myron。
新旧 root-container.raw 和 policy-carrier.bin 的 SHA256 一致。
本包只更新 boot，不需要重新下载、安装 15GB 根镜像。

使用：
1. 把 ZIP 内容解压到原测试目录，让 START-IOS27-LINUX.cmd 与原来的
   MYRON-IOS27.cmd、package 文件夹、state 文件夹处于同一层。
   原文件不需要覆盖；boot-update-43361559288 是独立子目录。
   必须保留原 state 内 Android boot 备份和 root-install.json。
2. 双击 START-IOS27-LINUX.cmd，先选 1 做离线校验。无需连接手机。
3. 手机手动进入 bootloader fastboot（不要进入 fastbootd），连接同一台设备。
   选 2，完整输入 START IOS。脚本检查序列号、槽位、boot 分区大小和解锁状态，
   刷入备份对应槽位的启动探针，然后重启。不需要 Android root。
4. 录像或拍下最后停住的数字、文字及色条。若仍只有小米 Logo 和色条也请拍下。
5. 若停住，手动回 bootloader fastboot，选 3，完整输入 RESTORE ANDROID。
   也可使用原 MYRON-IOS27.cmd 的选项 5 恢复。不要重新备份当前 iOS boot。

阶段含义（B 开头数字在早期控制台连接前后显示）：
B001：EndOfDxe 事件前
B002：延迟镜像处理前
B003 / B004 / B005：输入 / 输出 / 错误控制台变量设置前
B006：即将从 BeforeConsole 返回，随后由 BDS 连接控制台
B010：AfterConsole 入口
B011：ConnectAll 前
B012：内存发布前
B013：交接检查前
B014：启动 FAT 发布前
B015：控制台文字输出前
B016：UniXNU 启动前
B017：UniXNU 返回成功；B0FF：启动返回错误

之后的跳转探针：
2700：开始缓存维护
2701：开始指针认证密钥访问
2702：开始 EL1 指针认证测试
2703：开始 EL0 / SVC 往返测试
2704：准备跳转 XNU（只证明跳转前，不证明 XNU 已运行）

数字是“即将执行的阶段”，停在该数字可以缩小问题范围。
若没有数字，不能只凭四色线条断定具体阶段。

限制：离线校验复用安装完成记录，不重新读取手机 GPT 或 unixnu。
仅在安装后没有重新分区、改动 unixnu 或更换手机/槽位时使用。
校验失败请保留原目录并提供 results 中的错误日志，不修改记录绕过检查。
刷写失败不会自动重启、重试、切槽或重分区。

本次固件构建：https://github.com/yuwenhua653/UniXNU/actions/runs/43361559288
启动镜像 SHA256：ecbd5ae2af2fa94c2cb6fa3bb37d2616667f6ceab5b8f0111f2beeeec8e0a8be
