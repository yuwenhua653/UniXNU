myron iOS27 启动阶段定位更新 — 43349357896

用途：定位“小米 Logo + 四色线条”停在哪个启动阶段。尚未真机验证；
编译和模拟器通过不能证明已经进入 XNU 或桌面。

只适用于已完成 43165530177 unixnu 安装并显示
“unixnu installed and read back”的同一台 myron。
新旧 root-container.raw 和 policy-carrier.bin 的 SHA256 一致。
本包只更新 boot，不需要重新下载、安装 15GB 根镜像。

使用：
1. 把 ZIP 内容解压到原测试目录，让 UPDATE-BOOT.cmd 与原来的
   MYRON-IOS27.cmd、package 文件夹、state 文件夹处于同一层。
   原文件不需要覆盖；boot-update-43349357896 是独立子目录。
   必须保留原 state 内 Android boot 备份和 root-install.json。
2. 双击 UPDATE-BOOT.cmd，先选 1 做离线校验。无需连接手机。
3. 手机手动进入 bootloader fastboot（不要进入 fastbootd），连接同一台设备。
   选 2，完整输入 START IOS。脚本检查序列号、槽位、boot 分区大小和解锁状态，
   刷入备份对应槽位的启动探针，然后重启。不需要 Android root。
4. 录像或拍下最后停住的数字、文字及色条。若仍只有小米 Logo 和色条也请拍下。
5. 若停住，手动回 bootloader fastboot，选 3，完整输入 RESTORE ANDROID。
   也可使用原 MYRON-IOS27.cmd 的选项 5 恢复。不要重新备份当前 iOS boot。

阶段含义：
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

原完整构建：https://github.com/yuwenhua653/UniXNU/actions/runs/43349357896
启动镜像 SHA256：a251b4eaf6f17feff09aed144259aafbc28dde01ec9508269184b6a1cb2b1735
