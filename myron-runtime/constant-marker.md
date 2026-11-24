# myron no-monitor constant marker layout

Run 45350101216 (source faae2bf64079bdab3a783d7be65a334018c35c34)
compiled the native GPU/root kernel, then failed in `ufs-root-prelink`:
`No unused prefix for native constants before retained kext constants`.
The retained corecrypto text ended 512 bytes beyond the requested prefix.
Removing whole zero pages still left one extra 4 KiB page required for an
8-byte `__LASTDATA_CONST,__mod_init_func` initializer.

The board overlay now has a final fallback after ordinary placement and
whole-page compaction. It removes eight verified zero bytes from the end of
native `__DATA_CONST` and moves the initializer into that space. Both native
segment byte ranges remain disjoint. Their combined end is page aligned;
retained constants start on a subsequent page. The original native input and
all retained kext addresses are unchanged. The fallback rejects a different
section shape, alignment, permissions, instruction relocation, nonzero
padding, live symbol or relocation into the removed padding. Ordinary fitting
layouts retain the existing placement.

This overlay targets myron's pinned BCM2837 no-monitor XNU configuration.
Pinned XNU: apple-oss-distributions/xnu
`ac9718fb1af618d5ce8678d0dc6e8a58f252216f`,
`osfmk/arm64/arm_vm_init.c`: `arm_vm_page_granular_helper`,
`arm_vm_prot_init`, `arm_vm_prot_finalize`, and the MH_FILESET range setup.
Native DATA_CONST maps the shared page RW/NX during initialization and RO/NX
at finalization. The derived PLK_DATA_CONST starts at the next full page;
no retained constant page is skipped. Do not generalize this fallback to a
monitor/KTRR configuration without reviewing its earlier LASTDATA_CONST
protection transition.

Validation used the failed run's actual source-built native kernel and LTO
reference, with the unchanged pinned iPhone12,1 24A446 donor and all 30 roots.
Strict emission produced an 82,984,960-byte candidate with no unresolved
references and no stubbed functions. The exact fresh checkout plus complete
board patch series reproduced the same candidate. Storage, APFS vnode,
boot chain, display, GPU accelerator, RAM Data, and reviewed identity audits
passed. DarwinBoot's production C parser accepted the actual candidate.
All 82 XnuPrelink host tests passed, including negative marker cases.

These are offline build/structural checks. They do not establish GPU command
processor startup, fence completion, Metal rendering, or phone boot success.

## 中文

本次修复针对原生内核已经编译成功、最终预链接常量区不足的问题。
仅将 8 字节初始化指针放入已核实的零填充空间，保留全部有效内容、
kext 地址、重定位和页权限边界。已用失败轮次的真实产物完成严格预链接
及启动链、显示和 GPU 接口检查；真机 GPU 运行状态仍需另行验证。
