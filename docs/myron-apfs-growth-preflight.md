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
