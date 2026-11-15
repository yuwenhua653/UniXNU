# myron: PID 1 SIGSEGV after build 43664025900

The device photo reports launchd PID 1 status `0xb`, exit namespace `2`,
code `0xb`, and no exit-description string. In the pinned XNU source these
are `OS_REASON_SIGNAL` and `SIGSEGV`. This differs from the previous namespace
28 / code 0x105 PAC exit. It does not prove that PAC is fully resolved or
that userspace reached a later instruction. The IRQ and kernel-panic PCs
printed in the photo are not the original user fault PC.

The tested final kernel SHA256 is
`3ee7045a931ff08f44ef64ed9610de47fffc277db03737d033c68a3d10e5db17`;
the boot SHA256 is
`c28df19de88139c1e4be9ae446e8637227842fa86febe330467a954da81039c1`.
Its paired native PAC changes were verified in final integrated machine code.

## Identified diagnostic defect

`handle_user_abort()` already has a board hook after the successful/aborted
VM-fault return paths and after Mach exception-code and PAC-poison
classification. The old board implementation discarded the saved-state
pointer, stored only ESR/FAR/count, and displayed none of these fields.
The full-register recorder covered only `handle_pac_fail()`. Consequently,
a normal data/instruction abort could end in PID 1 SIGSEGV without showing
the original user context. The exit renderer also preserved register rows
only for namespace 28, which would erase an ordinary-abort snapshot.

This change records PID 1's first unresolved user abort from kernel-owned
saved state and retains it across signal exit and panic. It preserves the
original exception decisions, VM recovery, signal policy, PAC keys, root
contents and partition geometry. It does not add a userspace memory read.
The exception code is not labeled unconditionally as a VM return value:
alignment and non-VM paths can supply other codes.

The cached `task_shared_region_slide` is useful for locating shared-cache
instructions. Its value `0xffffffff` means unavailable; zero is valid. It is
not the launchd executable's slide. The snapshot cannot by itself prove that
a later userspace exception handler would not have recovered the exception.

If no full saved-state snapshot exists, a signal exit can display existing
uthread Mach exception/code/subcode as fallback evidence. It verifies that
the current thread belongs to the exiting task before copying those fields;
external termination paths can otherwise have a different current process.
Zero or absent metadata is not presented as a user fault PC. Non-signal
descriptions, including DYLD failures, retain their original display area.

This is a targeted correction to missing failure evidence, not a claim that
the SIGSEGV root cause or desktop startup has been fixed.

## Build qualification

The preflight applies the selected arch/OS/device patches to the pinned XNU
files and executes the extracted user-abort handler with modeled VM services.
It checks both successful recovery and failed data/instruction accesses,
unchanged exception dispatch, first-event ownership, cached-slide sentinels,
display bounds and retention through signal exit/panic. The existing PAC,
exit-description and ordinary progress tests remain separate regressions.
These host models qualify diagnostic behavior, not the complete native VM
or hardware behavior.

The native verifier requires both the recorder definition and an actual
AArch64 BL targeting the new user-abort recorder in executable segments.
Positive and negative branch-displacement tests reject non-calls, wrong
targets and invalid ranges. Final integrated-image inspection is still
required before producing the next device package.

Only source, host checks and this review are published. The device photo,
current Android boot backup and device/root inputs are not publication files.

Validation on the reconstructed upload capsule: all seven groups passed with
Clang 19.1.7, including the independent arm64e recorder compile. ASan/UBSan
host runs used UBSAN_OPTIONS=halt_on_error=1. The previous PAC-only source
is rejected by the new abort qualification. Full Apple native XNU build and
subsequent physical-device observation remain pending.
