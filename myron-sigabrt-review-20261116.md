# PID 1 SIGABRT after the VA43 build

Tested source: `fbe4f8a4993354217c1e499a7a725822432207d3`.
Tested CI run: https://github.com/yuwenhua653/UniXNU/actions/runs/43695528570
Tested boot SHA256: `979161f938e4e13b6cf247ae9405cd696ee71fe3792a393b611cc031d4582010`.

## Evidence and limits

The owner's November 16 photo shows `init_exclaveskit` PID 0x13 exiting
with status 0 and no exit reason, followed by `launchd` PID 1 exiting with
status 6, exit namespace 2, code 6. The current exiting thread's Mach
exception/code/subcode are all zero. No exit reason description is present.
The bottom panic prints a literal format string; its PC is a kernel panic
caller, not the user instruction that caused the termination.

In the pinned XNU source `ac9718fb1af618d5ce8678d0dc6e8a58f252216f`,
`bsd/sys/reason.h` defines namespace 2 as `OS_REASON_SIGNAL`, and
`bsd/sys/signal.h` defines signal 6 as `SIGABRT`. The preceding SIGSEGV
photo showed code 11. This proves a different observed exit mechanism;
it does not prove that every earlier address-width fault is resolved.
Neither the zero Mach fields nor the preceding successful service exit
identifies the source of SIGABRT. Self-abort, another signal sender, and
fallback from a failed reason-bearing abort remain distinguishable possibilities.

`proc_prepareexit()` calls `proc_handle_critical_exit()` before its normal
crash-report backtrace. For PID 1 that critical path panics, so the later
backtrace is unreachable. Existing unresolved-memory-fault hooks also do
not run for an ordinary signal exit. This is the concrete diagnostic gap.

## Change

Capture at most 20 user frames before the PID 1 critical-exit panic, only
for SIGABRT and only when the current process and current thread's task
match the exiting process. Reuse XNU's `backtrace_user()` and its bounded
copyin/error handling. Skip stack reads with interrupts disabled or in
interrupt context. Preserve the unwind error, flags, count and raw shared
cache slide; show partial/empty results explicitly. No custom raw user
pointer dereference, allocation, signal suppression or exit-policy change.

The framebuffer recorder copies a fixed kernel-owned snapshot. The
backtrace display is selected only for namespace 2/code 6 without a useful
description and without an already-captured memory/PAC fault. Full existing
exit descriptions retain their 800-byte budget. The display labels this as
the exiting thread's stack, not proof of the signal sender. BT00 is the
saved PC; subsequent entries are return addresses and must be symbolicated
accordingly against the matching 24A446 image/cache and its recorded slide.

The native verifier requires a real emitted call to the recorder. The final
fileset gate additionally requires its definition, the unwinder and the
new display marker inside the packaged kernel. Existing VA43 verification,
fresh-PC boot backup requirements and root-install guards remain enabled.

## Validation before CI

- Applied the actual arch/OS/device patch stack to the pinned XNU sources.
- GCC ASan/UBSan execution of the new hook/renderer: PID, task, signal and
  context guards; complete/partial/empty/error traces; 20-frame bounds;
  first snapshot; framebuffer padding; persistence through IRQ/mount/panic;
  existing fault and 800-byte reason priority; disabled-board behavior.
- Existing unresolved-abort and exit-reason execution tests passed.
- Seven final-fileset contract tests passed, including rejection of the
  previous diagnostics when the new SIGABRT implementation is absent.
- Existing native call-gate tests and all 28 negative user-VA verifier
  controls passed. Source capsule reconstruction and digest checks passed.

The macOS preflight runs the new test before the full native kernel build.
Native compilation and another phone boot are not established by these
host results. This change diagnoses the SIGABRT; it does not claim to fix
the as-yet-unknown abort condition or to reach the desktop.
