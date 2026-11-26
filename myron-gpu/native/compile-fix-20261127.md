# Native allocator build fix

Full package run 45758310825 stopped in Root compile preflight. The two fatal
diagnostics came from the staged NativeAdrenoMemory.cpp grant/refusal counters:
incrementing a volatile-qualified integer is deprecated in C++20 and the native
compiler treats that warning as an error. LTO and kernel prelink had not run.

Use explicit reads and assignments for overflow counter and byte-accounting updates,
matching the upstream pool counters. Keep the existing resource-gate locking,
volatile diagnostic visibility, 128 MiB cap, quarantine accounting, and unsigned
counter rollover. No compiler warning is disabled for the production source.

The actual staged allocator test now builds as C++20 with -Werror and ASan/UBSan.
It checks grant/refusal/peak counters and rollover in addition to cap, reuse,
failure rollback, device holds, and quarantine. The refusal rollover case sets
the caller's budget high enough to reach the overflow cap, rather than returning
at the unrelated per-request budget guard.

Local verification: the pre-fix staged allocator reproduced both diagnostics;
the fixed test passes with GCC 14. All 14 native host suites pass, as do the 13
continuous-contract tests and two diagnostic-collection tests. These are host
checks, not a device rendering result or a completed arm64e kernel build.

The macOS prerequisite job now fetches the pinned dependencies and runs the same
strict test with Xcode clang++ before the full package job can start. The native
compile, LTO, prelink, and package checks remain mandatory.
