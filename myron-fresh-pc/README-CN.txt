myron iOS 27 新电脑独立启动包 — 构建 43567678297

已核对最终 boot 中实际内核：APFS 的 VNOP_STRATEGY 函数入口已正确绑定，
不再错调会提前释放缓冲区的 VNOP_BWRITE；189 处操作描述符引用全部匹配。
失败释放路径现在保存真实调用者地址，不再记录编译器拆出的 cold 函数返回地址。
固件和交接测试通过，但这不代表已通过手机开机或进入桌面实测。

【正在使用上一轮新电脑包 43544518065】
1. 将本 ZIP 完整解压到一个新文件夹。
2. 从你在这台新电脑刚使用的 43544518065 包，复制整个 state 文件夹到新包根目录，
   与 START-IOS27.cmd 放在一起。保留原目录作为恢复备用，不要修改里面的文件。
3. 手机进入 bootloader fastboot，运行新包 START-IOS27.cmd，选 3、输入 START IOS。
   本包验证 boot 备份完整性、手机和槽位、完整现场根分区校验记录；通过后只刷本轮 boot。
   已确认两轮 GPT、根镜像和策略区内容完全相同，因此不必重新备份或重复全量读取。
4. 需要恢复 Android 时选 4。本包可直接恢复上述备份，不依赖旧包程序。
仅接受 43544518065 新电脑包或本轮包生成的完整备份，拒绝更早测试包的记录。
如果后续修改了手机分区/系统内容，应先用备份恢复 Android，再按下方流程重新采集。
若没有这份 state，请按下方独立流程操作，不要拿当前 iOS boot 当 Android 备份。

这是独立的“备份 + 校验 + 更新 boot”包。
不需要旧电脑上的测试目录、package、state、root-install.json 或 Android boot 备份。
包含 Windows x64 便携 Python、ADB、fastboot；不用安装 Python，也不用复制旧工具。
电脑仍需能识别手机的 ADB/fastboot USB 驱动。Android 无需 root；已有 Recovery
必须能提供 root ADB（如之前用于安装 unixnu 的 Recovery）。本包不安装 Recovery。

没有有效 state 时的独立使用步骤：
1. 将整个 ZIP 解压到新的独立文件夹，至少留 512 MiB 空间。不要在压缩软件里运行，
   不要混合不同备份。双击 START-IOS27.cmd。
2. 手机先进入能正常使用的 Android，开启 USB 调试，并允许这台新电脑的调试授权。
   选 1：记录当前手机/槽位和已启动 Android，然后重启到 Recovery。
   如果现在仍是 iOS 启动镜像、不能进入 Android，先恢复适配当前 Android 系统的 boot；
   不要把 iOS/UEFI 的 boot 当成 Android 备份。新电脑不能凭空恢复已丢失的原始 boot。
3. 手机停在 Recovery 主界面，不要进入 sideload。选 2：
   - 从当前槽位重新读取 boot，连续读两遍并核对 SHA256；
   - 在新包的 state 文件夹保存 boot_a.img 或 boot_b.img 和对应记录；
   - 现场验证 GPT 和手机现有 unixnu 的根镜像、策略区完整 SHA256。
   约 14.06 GiB 根镜像在手机端只读校验，不下载回电脑。等待时每 10 秒显示进度。
   校验过程不写手机分区，不重装、不重新分区、不改 Android 数据。
4. 等提示全部通过，手动将手机进入 bootloader fastboot（不要用 fastbootd）。
   选 3，输入 START IOS：只刷刚刚备份的同一槽位 boot，然后重启。
   UniXNU 菜单选第一项，按住音量＋约一秒后松开。若停住，拍摄最后一屏日志。
5. 回 Android：手机进入 bootloader fastboot，选 4 或双击 RESTORE-ANDROID.cmd，
   输入 RESTORE ANDROID，恢复本包刚刚从手机读取的 Android boot。
   恢复不需要 payload 文件夹、构建报告或根分区校验记录；需要保留 app、runtime、
   platform-tools 及整个 state 文件夹。

重要：
- 手机现有 unixnu 仍需是此前已安装的相同系统内容。新备份流程会现场校验；
  已有兼容备份则校验其完整记录与本轮范围、哈希的一致性。若不匹配会停止，不覆盖分区。
- state 是此电脑新采集的恢复资料，成功后请另存一份。不要手动修改里面的 JSON。
- 若中断备份，保留 .partial 和日志，重新解压一份到新目录再从步骤 1 开始；不覆盖旧文件。
- 不解锁引导程序、不切槽、不改 vbmeta，不自动重复刷写。
- 新电脑/新线缆若无法识别设备，先处理 USB 调试授权或驱动；不要绕过检查。
- 脚本的异常与恢复路径已通过主机模拟测试；本轮仍待手机实测。

本轮构建：https://github.com/yuwenhua653/UniXNU/actions/runs/43567678297
Python：https://www.python.org/downloads/release/python-31317/
Android platform-tools：https://developer.android.com/tools/releases/platform-tools
组件许可证随包保留。详细文件哈希见 FILES-SHA256.txt。
