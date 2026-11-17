# Original launchd shutdown attribution and console visibility

Source baseline: `a02a84e529b3da104027c4139dc6c41fb0e720fb`.
Phone evidence: `1000149643.jpg`, tested native run `43975218126`.

Offline analysis runs `44009931469` and `44011991353` both passed. The latter
artifact is `14297382263`, ZIP SHA256
`54740f7d5aa57267ebafc4b7a5853787a6de4c16fa32ebad096f1f6cfcbe972f`.
It contains 68 function descriptions and 14,136 audited instruction rows;
no original executable or OS image is exported.

The original OS full-image hash and APFS UUID were checked before read-only
mounting. launchd SHA256 is
`c640246d38aaeb2d2372aff1e5aa0de59dec267f53c0dfc155f7837e717af68b`,
UUID `ca54230d400531318dc3ccb7e7ef18e6`; original trust-cache membership and
every CodeDirectory code slot passed. No original OS binary was modified.

## What the evidence establishes

The stronger photographed-frame interpretation has slide `0x60e000` and six
consecutive direct caller matches. This is inferred ASLR, not a recorded
runtime load address. The chain crosses coalition cleanup and the shutdown
completion path at `0x1000160a8`, finally reaching the reboot
wrapper at `0x1000436a4`. It does not identify the initial shutdown requester.

The authenticated original executable reads `kern.bootargs`, pairs
`LogToConsole` with `launchd_log_serial=` at `0x10004a3b4..0x10004a3cc`, and
has a serial logger opening `/dev/console` at `0x10004deec..0x10004df00`.
The shutdown request handler at `0x100034908` formats both
`%s initiated by: %s` and `%s: flags = 0x%llx, caller = %s` before teardown.
Other distinct paths log critical-process crashes, a kernel SIGTERM, or boot
task reboot-on-success. Their presence alone does not prove any ran on-device.

## Change

Startup diagnostic packaging adds the original `launchd_log_serial=1` option.
The existing nonblocking console recorder retains the first three matching
logical lines, with two display rows each and elapsed timestamps, before the
first reboot request. Long lines, truncation, case differences, control bytes,
post-reboot churn, panic and framebuffer handoff are bounded. Explicit
`Feature disabled, device would have rebooted` messages do not consume slots.
If no matching text is observed, the previous history fallback remains.

Final firmware assembly requires the new retained-recorder definitions, reason
strings and the boot argument. It rejects the earlier recorder even when
generic progress symbols match. The optimized display heading is assembled
with immediate stores rather than a contiguous C string; the exact native
block was emulated and its output verified (see compiled-recorder record).
There is no reboot suppression, timer extension, service-disable rule,
signature change, or reset callback modification in this change.

## Validation and limits

The actual recorder passes GCC with ASan/UBSan and warnings as errors, plus
independent freestanding arm64e compilation. Tests exercise line wrapping,
oversized input, first-three retention, non-reboot negative control, cleanup
and timer-panic retention, contention and scanout ownership. Eight final-image
contract tests pass, including rejection of the old payload. The startup
boot-argument test and unchanged reboot authorization/return-path tests pass.

Native CI and final firmware verification passed. Actual phone console routing
must still be verified. Console text can
interleave or be dropped, and is not authenticated attribution. The first
shutdown trigger and desktop boot remain unresolved; this fixes an evidence
gap, not a proven operating-system boot root cause. No new phone test yet.

## Native build and firmware resumption

Native producer run `44014423552` succeeded at source `899b248`. The last
Linux job failed only at the contiguous heading check. Commit `289430f`
corrects that assumption, adds negative regressions, and pins resume run
`44036554616` to the same artifact, source checkout and image hashes. Ten
contract tests and checks against the downloaded CI kernel passed.

Firmware resume run `44036554616` completed successfully. The final packaged
helper passed 14 simulated-device tests. Offline extraction confirmed the
native FAT payload is unchanged, the final firmware hash matches its report,
and launchd serial logging and retained-reason definitions are present. The
phone test ZIP hash and exact identities are in `shutdown-reason-package-44036554616.json`.
No new phone result has been received.
