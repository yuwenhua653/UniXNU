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
