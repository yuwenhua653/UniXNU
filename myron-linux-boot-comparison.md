# Linux/Clang 18 boot comparison — 2026-11-13

The phone still showed the Xiaomi logo and four coloured lines with the macOS
boot probe from run 43349357896. The already completed firmware-only run
43361559288 builds the firmware with Ubuntu/Clang 18 and reuses that probe's
entire FAT, iOS27 kernel, shim and Android header byte for byte. No kernel or
root rebuild is needed. The CI job took 132 seconds; its build/check script
reported 82.3 seconds.

## Binary evidence

The R90 iOS17 package contains 35 firmware modules. Extracting those modules
and comparing their bytes to the two iOS27 images gives:

| Comparison against R90 | Whole modules identical | PE .text identical |
| --- | ---: | ---: |
| Previous macOS probe, run 43349357896 | 0/35 | 0/34 |
| Linux/Clang 18, run 43361559288 | 31/35 | 31/34 |

The identical Linux modules include DxeCore, GraphicsConsoleDxe, ConPlatformDxe,
ConSplitterDxe, MyronFdtGopDxe, MyronKeysDxe and the filesystem/runtime drivers.
The remaining differences are SEC, BDS, UniXNU and DarwinBoot. SEC is not a PE
image in this comparison. See `tests/r90-firmware-binary-comparison.json` for
per-module hashes and section comparison. Every extracted Linux module hash
also matches the successful build's firmware verification report.

R90's packaging record is **not** a phone-success record. Binary similarity
alone does not establish a compiler regression or prove that this candidate
boots. BDS source instrumentation also changed from the macOS probe, so this
is not a compiler-only controlled experiment.

## Companion

`myron-device-test/package_boot_update.py` now emits `START-IOS27-LINUX.cmd`, a
Chinese guide and the isolated `boot-update-43361559288` directory. This avoids
replacing the previous delivered menu or helper folder. It pins both the new
manifest and image SHA256, retains all original Android-backup/session/root
receipt checks, flashes only the saved boot slot, and keeps restore independent
of the update files. Existing `package` and `state` are required and preserved.

The companion workflow tests Windows and Linux, then downloads only the small
candidate artifact from run 43361559288. It does not rebuild firmware, the
kernel, or the root filesystem. The original run 43165530177 root installation
is reused only if its saved receipt and all retained image/layout identities
match. No fresh backup of a currently flashed iOS boot is permitted.

Phone observation should record the last B001–B017/B0FF or 2700–2704 value,
menu/text, or all coloured lines. B006 means BeforeConsole is returning; B010
marks AfterConsole entry. 2704 is before the XNU branch, not proof of XNU entry.
If stuck, enter bootloader fastboot and use the existing Android restore.
