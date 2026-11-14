# myron: launchd PAC failure after run 43590593422

The phone reports PID 1 status 9, namespace 0x1c and code 0x105: SIGKILL,
OS_REASON_PAC_EXCEPTION and EXC_ARM_PAC_FAIL in the pinned XNU source.
This path supplies no string description. The displayed kernel panic return
address is not the user fault PC. No successful desktop boot is established.

## Identified defect and upstream fix

The previously reviewed final kernel (SHA256
`5b02b6915a2979edbd49fd429bdcd5d122c715949fed782a8bc025626ba9f45d`)
returns zero from `_ml_default_jop_pid`. The shared-region pager treats zero
as the non-arm64e selector and skips signing authenticated cache pointers.
The actual 4 KiB v5 slide code was present. This is a specific missing selector
fix, consistent with the PAC exception; the photo cannot identify the exact
failing pointer without the user PC and instruction.

Backport both related changes from upstream commit
[`a11553a7a29a49777f2665008f4216fcd4ad1b40`](https://github.com/UniXNU/UniXNU/commit/a11553a7a29a49777f2665008f4216fcd4ad1b40):

- Native arm64e uses selector 1, allowing pointer signing; arm64 keeps 0.
- Only DISABLE_USER_JOP threads return to EL0 with PAC enable bits off.
  EL0 exception entry restores them before kernel authentication. Arm64e
  processes and the kernel retain PAC. The upstream locore patch is preserved.

The source changes are isolated in the device patch series, leaving the pinned
upstream revision and the existing shared-cache provenance/signature checks intact.

## Diagnostics and build checks

Capture only the first PID 1 user PAC exception from kernel-owned saved state:
PC/LR/SP/FP/CPSR/ESR, raw FAR, the instruction already copied by the original
handler and x0-x28. FAR validity is not assumed. No extra user-memory read,
PAC key disclosure, exception bypass or termination-policy change is added.
Dedicated display rows retain the snapshot through exit, IRQ, mount updates
and panic while preserving the critical-exit reason and final panic rows.
The hook is enabled by the board's actual MYRON_EARLY_PROGRESS macro as well
as XNU_BOOT_PROGRESS; the regression test uses the board macro alone so an
otherwise linked recorder cannot silently lack the user-exception call.

Host tests apply the exact patch stack and cover native/paravirtualized selector
branches, the real v5 slide signing path and the bounded exception renderer.
The native artifact verifier checks actual selector return instructions and
requires the new PAC recorder symbol before prelinking; symbol presence alone
is insufficient for the selector fix. Native compilation and real-device
execution remain separate qualifications.

## Recovery of interrupted publication

Workspace maintenance removed the unpublished local commit c748b7c. The update
is reconstructed on remote head ab73e224aa3948a39bbc6294ef3ee551f2e3aabb from
the pinned upstream patch and the recorded design, then revalidated. It is an
equivalent source recovery, not a claim to reproduce that lost commit hash.
Fresh reconstruction passes the native-selector/slider test and ASan/UBSan
user-PAC and existing exit-reason tests. Existing progress and panic/IRQ
regressions also pass. Apple native compilation still awaits this CI run.

Publication includes source, tests and this review only. No phone images,
backups, device inputs, credentials or unrelated packaging changes are included.
Existing root contents and partition geometry are unchanged.
