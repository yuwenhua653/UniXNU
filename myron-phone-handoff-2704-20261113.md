# Myron phone observation: UniXNU menu and handoff 2704

Observed on 2026-11-13 (Asia/Shanghai), following installation of the Linux/Clang 18 boot-only candidate from run 43361559288. The exact flashed bytes were not independently read back in this observation; package identity follows the user's test sequence.

## Evidence

- First supplied photo: UniXNU 0.1.0 menu, configuration path \\EFI\\UniXNU\\unixnu.toml, selected MYRON iOS 27 dyld startup entry.
- Second supplied photo: after selecting that entry, green first band, cyan second band, visible 0000000000002704.
- DarwinBoot prints kernel streaming, ARM64 loading, framebuffer information, command line, and "inputs validated; exiting boot services".
- User reports the second screen remains stuck.
- Original photos are retained privately; no photographs uploaded to this repository.
- Menu photo SHA256: b3bd21a9e19fe517e58d047e3cfc97631551c2741cea85418290e877feeae81e
- Handoff photo SHA256: 3a81003ce772605fd5edd81632837260f4aa0612214b91060b5dc7f38653d1cf

## Source-grounded interpretation

In the shipped loader/Handoff.S, 2704 is emitted after successful ExitBootServices,
the owned-memory cache sweep, MMU/cache disabling, key-register read/writeback,
EL1 PAC round trips, EL0 PAC round trips, and the checked SVC return. These
checks apply to this boot CPU, not all CPUs or every XNU pointer-authentication
path. The cyan second band is then painted immediately before br x1.

The last console line is therefore stale relative to the later direct
framebuffer milestone: this observation is not evidence of ExitBootServices
hanging. The menu regression was crossed in this attempt.

2704 does not prove execution of the kernel entry, MMU initialization, C startup,
root mount, launchd, or desktop. The photo cannot distinguish a stop immediately
before/at the branch from later silent kernel execution. No root-cause claim is
made about the compiler: BDS instrumentation also changed between candidates.

## Next diagnostic boundary

Keep the Linux/Clang 18 firmware and existing Android backup/root installation.
Further BDS/menu markers cannot distinguish the remaining boundary. The next
instrumentation must observe actual XNU entry and early MMU/C-startup progress.

Current build_ufs_dormant.py explicitly disables XNU_BOOT_PROGRESS; adding the
boot-progress argument alone cannot enable compiled-out observer code. The
upstream patch-xnu-entry-probe.py uses fixed addresses for a different kernel
and must not be applied unchanged to this iOS27 fileset. Any reused-image
instrumentation requires exact image/symbol/instruction checks and qualification;
otherwise qualify a source build with appropriate early observers.

No new image or device-write action is produced by this evidence-only update.
