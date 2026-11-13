# myron masked-WFE compatibility experiment

The two device photographs show identical root-mount events and identical
37-second/IRQ counters. Root discovery returned disk5s1; APFS mount entered;
the last recorded UFS completion returned status 0 and 4096 bytes. This does
not establish that APFS is corrupt or that interrupts stopped independently
of the display recorder.

The qualified native kernel from run 43379932443 contains `wfe_allowed = 1`.
Its compiled `wfe_to_deadline_or_interrupt` loads that scalar at
0xfffffff00ac2a348 and branches over WFE when it is zero. Apple's pinned
`osfmk/arm64/cpu.c` (ac9718fb1af618d5ce8678d0dc6e8a58f252216f) explicitly
describes the masked-interrupt WFE limitation; some callers keep interrupts
masked, including the proximate-timer wait. The source already implements
the alternative policy when `wfe_allowed` is zero.

This experiment changes only the initial scalar from 1 to 0. WFI idle,
timer programming, interrupt masking/dispatch, and all kernel instructions
remain identical. Short/proximate WFE waits instead poll the existing
interrupt/deadline conditions, so idle power consumption may differ. Device
execution and resolution of the APFS stall are unverified.

The derivative rejects any other original kernel SHA, validates the native
symbol and non-executable writable data mapping, and verifies the exact
result SHA. Tests inspect the compiled consumer, reject corrupted and
already-adjusted input, and compare every file after the FAT update. The
firmware build rebinds the payload hashes and reruns handoff and Windows
update/restore qualification. It reuses the installed root and policy
identities without changing the Android backup rules.

Native provenance remains commit e7cd64972d3a5725f1a13d130806729a21101361,
run 43379932443. Assembly provenance and the scalar adjustment are separate
fields in the report and manifest. This is a binary data derivative, not a
new native compile. Future source integration, if device results justify
it, should apply `int wfe_allowed = 0` only for this board and rebuild XNU;
this workflow deliberately does not silently change the full-build source
or claim the experiment is a proven fix.
