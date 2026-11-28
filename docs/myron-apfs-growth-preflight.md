# APFS growth qualification before another phone package

The owner rejected rebuilding a package containing only the cache-overlay
rollback. Run 46095775958 was cancelled. Do not trigger another full package
until an actual growth repair and its startup path have been reviewed and
qualified. Keeping the system cache untouched is containment, not that repair.

`myron-apfs-growth-analysis.yml` runs only for the exact message
`Analyze myron APFS growth before package`. It reads the hash-pinned original
24A446 OS/SystemOS, verifies the raw image identities, and produces bounded
static JSON for the real APFS resize/minimum-size API exports and launchd's
cache policy/embedded boot configuration. The original/merged cache also passes
through Apple's read-only plist parser. This workflow does not compile XNU,
create a flash package, access phone Data, run the helper or call a resize API.

Before implementation, resolve the exact supported resize target/ABI, helper
startup mechanism and service-cache compatibility. Then test the real helper
or its extracted transaction core with failure injection, including an existing
attempt journal, altered device identity, short reads, failed synchronization,
API failure and mismatched post-resize UUID/capacity. A valid file or plist is
not proof of execution; keep separate evidence for publication, process start,
resize call and filesystem verification. Preserve current Data and refuse stale
copy fallback. Only grow the authorized NativeRamBlock store; never the OS,
physical UFS/GPT or an arbitrary device name.

The phone remains the final APFS-runtime qualification. Static API inspection,
synthetic tests, a larger IOMedia and a successful kernel build cannot establish
filesystem growth or retained-data integrity on the phone.

## Completed donor analysis and source repairs, 2026-11-28

Analysis run `46096736637` completed both read-only jobs successfully. The
bounded provenance is in `records/myron-apfs-growth-46096736637.json`.
The exact donor APFS framework confirms the existing Resize/Minimum ABI and
physical-store fallback. Those were not demonstrated bugs. Its live-space
query has a different requirement: `APFSContainerGetSpaceInfo` passes zero for
the physical-store fallback flag. The revised helper discovers the synthesized
`AppleAPFSMedia` above the verified physical NativeRamBlock and uses its BSD
name consistently for all three calls. No caller-provided disk path is accepted.

The real verification defect was treating the bootstrap block-zero NX copy as
the live mounted container capacity. Apple's APFS reference (Container,
pages 8 and 26) distinguishes the bootstrap copy from checkpoint/live state:
https://developer.apple.com/support/downloads/Apple-File-System-Reference.pdf
The revised helper uses that checked raw block only for container UUID/geometry
sanity. Capacity comes from the APFS container API, cross-checked against the
mounted Data `statfs` capacity. It still requires exactly 1 GiB before a new
growth attempt and exactly 16 GiB afterwards. This is capacity verification,
not a full filesystem-integrity or user-file-content check.

`MyronAPFSTransaction.h` is called by the actual helper. It re-discovers and
compares the volume, synthesized media, physical store, provider registry IDs,
BSD names, mounted filesystem ID, raw device number and volume/container UUIDs
before the durable journal, again before the API, and after it. There is one
mutation call at most. Existing, partial or uncertain attempt journals are
never replaced or deleted. Fixed console stage markers distinguish process
entry, journal, resize entry, resize return and result even if Data log output
cannot be created. Read-only capture accepts the additional bounded fields.

The shared transaction core passed 60 host cases under ASan/UBSan (leak checks
disabled because this executor runs under ptrace). The actual journal adapter,
extracted without changing its control flow, passed 12 real temporary-file I/O
cases plus retained-attempt, symlink and directory refusal. These tests do not
execute iOS IOKit, its APFS user client or the Objective-C helper on a phone.
The revised iOS executable has not yet been compiled or run.

Packaging now compares the helper artifact's complete source-hash manifest
against the current reviewed sources. The real old artifact `15168827538` is
rejected. Its download ID and executable pins intentionally have NOT been
advanced to an unbuilt candidate. Update them, trust/addon hashes and resulting
kernel binding together only after the helper/startup repair is ready.

## Remaining blocker: real startup

The donor's embedded `Bootstrap.Paths` includes System and AppleInternal
directories, not `/Library/LaunchDaemons`. Its embedded `IgnoreCache=true`
controls a different flag from the restore/basesystem condition used by the
cache-protected disk-read branch. Therefore neither that plist key nor a
`launchd_no_cache` argument establishes that an added system job will be read.
macOS `plutil` accepted both cache files, but this does not qualify iOS's XPC
parser, its cache-loader path, or a third union mount.

The phone capture stopped during early boot work, before a helper start/result
was established. No final panic/reboot record identifies a unique cause.
The system-cache overlay stays disabled. A proven startup path remains
unresolved; do NOT call these source repairs a complete phone expansion fix,
and do NOT start a full package build from this checkpoint. No rollback-only
or speculative boot-argument build is requested.

## Implemented early task, pending signed-component qualification

The later read-only run `46100032778` resolves the startup source question.
Its exact-donor evidence and source references are recorded in
`records/myron-data-earlyboot-46100032778.json`. `restore-datapartition` is an
optional `/usr/libexec/HorizonSetup` task before `mount-phase-2`, MSU and the
service cache loader. The hash-verified donor has no file at that path. The
existing phone capture also records this task being attempted and absent.

The new read-only union publishes just the owner adapter at that absent path.
It refuses an existing file or symlink and any lookup error other than ENOENT,
requires a sealed read-only lower directory and the exact growth boot option,
and checks that an original lower entry remains visible. The eight-file addon
must finish its hash-bound installation before either union is attempted.
The early union no longer depends on the GPU mount succeeding. Neither the
LaunchDaemons directory nor the system service cache is overlaid. Old owner
files on Data are not deleted.

Original launchd spawns this task suspended, requires CS_PLATFORM_BINARY and
signing identifier `com.apple.HorizonSetup`, then resumes it. Its RequireSuccess
crash behavior is 3. The minimal C adapter is therefore a separate executable:
it checks PID 1 parent, root, fixed executable path and exact boot option,
spawns the APFS helper once with fresh default crash attributes, waits without
killing/retrying a resize, and returns zero even if the helper refuses or
crashes. Pinned XNU `kern_exec.c` explicitly assigns the fresh child crash
behavior; it does not inherit the task's panic policy. A crash of the adapter
itself is still boot-critical and is not claimed to have been phone-tested.

Code-page and entitlement hashes, exact signing identity and both executable
CDHashes are checked. The owner module remains first in the external trust
bundle, which pinned XNU loads as static/platform trust; the two Apple modules
remain byte-identical. No global AMFI or launch-constraint bypass is added.
The component build must compile and sign both real iOS executables before
updating addon/trust/kernel pins. `check_data_helper_contract.py` blocks a full
build until those pins and all reviewed helper source hashes agree.

Host checks passed 78 actual-wrapper cases and 198 actual-publication cases,
including child signals, bad boot options, existing/dangling-symlink paths,
independent mount failures and resource cleanup. The real union mount harness,
60 transaction cases, journal I/O tests and 280 reconstructed startup cases
also passed. These are source-path tests, not device execution or successful
filesystem expansion. The old artifact stays rejected while the new component
is being qualified; a successful component build alone is not a flash package.

The first component run `46101177780` compiled both real iOS executables and
passed macOS host checks. Independent download audit also rejected altered
code pages, wrong signing IDs and changed entitlements. Review then found that
removing the old launch service also removed its stdout file: console output
alone is not guaranteed to enter the kernel's persistent message capture.
The helper now additionally saves a bounded owner-only JSON result after its
transaction, using an anchored directory, no-follow/nonblocking open and
regular-file/owner/link-count/mode checks. Short or failed report writes do not
change the transaction outcome and never authorize retrying growth. The new
report writer has real-file fault tests; it requires a refreshed component.
The full-build gate remains closed until the refreshed artifact is bound.

The original mounted donor is checked again during packaging: exact audited
launchd hash, original executable directory, and absent HorizonSetup including
dangling-link refusal. The runtime makes its own absence check before mounting.
Application staging currently precedes this early userland task. After a first
successful expansion, a normal subsequent boot lets that existing staging step
use the new space. The adapter never forces a reboot. App/wallpaper recovery and
performance remain phone-test outcomes, not guaranteed by these host checks.

## Final signed component bound for a full test build

Run `46101684719` succeeded at commit
`dd3f5dd812780b7f748e10d3ebe025841087898c`. Artifact `15246315141` contains
both signed iOS executables, the bounded report writer, exact source manifest
and successful macOS host checks. Independent byte/code-page/identity and
entitlement checks passed after download. The source-pinned early adapter is
unchanged from the first successful component; the APFS helper now includes
the result-file writer. The full evidence is recorded in
`records/myron-data-earlyboot-46101684719.json`.

The final eight-file addon and four-entry first owner trust module were rebuilt
and read back; both original Apple modules remain exact. The actual installer
accepted those bytes, refused 96 corruptions and retained the final file through
10 atomic-writer failures. Reconstructed packaging accepts only the final
component and rejects both earlier artifacts. The full-build contract gate now
passes. This qualifies the source and compiled components for a **full test
build**, not successful phone execution or an already verified expansion.

Phone acceptance requires a verified/already-expanded report, real APFS Data
capacity of 16 GiB, increased free space and intact existing user data. Then a
normal subsequent boot lets pre-launchd application staging use that capacity.
Do not format Data or remove an uncertain attempt journal to force acceptance.
