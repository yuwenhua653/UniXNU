# Data early task launch failure in run 46109218091

The phone reached launchd and the original `restore-datapartition` boot task.
The eight-file addon installed successfully (`files=8`, two updated, six
unchanged) and the early executable union reported `early_stage=5`, status 0.
AMFI then killed `/usr/libexec/HorizonSetup` before its first user-space
checkpoint: validation category 1, launch type 1, constraint mismatch.
Because the original boot task requires success, launchd announced a panic
three seconds later. The wrapper's handling of child failures cannot protect
against the wrapper itself being killed before main.

The saved Data mount still reported 262144 blocks of 4096 bytes (1 GiB).
The read-only scan selected the 16 GiB provider but found no helper report.
Provider size is not evidence of APFS container growth. The original app
staging failed with ENOSPC before the rejected early task.

## Exact retained policy

The failed package's logical kernel has SHA256
`efc153153c8262b96cba71a8a13d0d97f2c6d1a2ad8627d70cf746bf5f23cf48`.
Its retained 24A446 AMFI contains a system-service category predicate at
`0xfffffff008f1139c`: category below 20 and bit set in mask `0x890ba`.
Category 0 is absent; category 5 is present. Its successful category mark
sets the object flag consumed by the subsequent system-service check.
The unrecognized-category path applies fallback category 6. That fallback
requires protected/system/authenticated-volume placement for a binary whose
trust cache already supplies a constraint category; our Data-backed union
does not meet it. The diagnostic `c[8]` identifies the policy source; it is
not trust-cache category 8.

The actual category 5 self DER requires `validation-category == 1`.
Its parent DER permits PID 1 or the existing trusted, system-volume
`com.apple.mbfloagent` parent. This matches the original early-task parent.
We retain that policy unchanged and assign category 5 only to the exact
HorizonSetup CDHash. The GPU plugin, Turnip and child resize helper remain
category 0. The child uses fresh, default spawn attributes, not launchd's
system-service or panic attributes.

The owner trust UUID now includes the complete entries, including categories,
so a policy change cannot retain the previous owner UUID. The original two
Apple trust modules, eight addon files, signed helper binaries, Data seed,
original root and AMFI executable bytes remain unchanged. No global AMFI
or launch-constraint bypass is enabled.

## Build gates and verification

`earlyboot_launch_policy.py` checks nine exact code/table/DER ranges in the
actual final kernel, verifies category 5's dispatch and decodes the mask.
It runs during sidecar staging and final firmware readback. The sidecar and
firmware guards independently check every owner entry's type, flags, category
and reserved byte and preserve the original Apple trust modules.

Host verification includes rejection of the actual old trust bundle, mutations
in all nine policy ranges, and wrong categories/flags on all four owner entries.
The reconstructed build source accepts the repaired trust bundle and the
actual retained kernel policy. These are static and host checks, not proof
that the next phone boot or APFS resize succeeds.

The next phone evidence must include `[myron-data-earlyboot] stage=entered`,
the child result, and a verified APFS capacity increase before reporting growth.
Keep the no-retry transaction journal and collect logs before another iOS boot
if startup fails. Do not format Data or remove its attempt journal.

Background references (the version-specific decision above uses the actual
24A446 binary, not older category tables):

- https://developer.apple.com/documentation/security/defining-launch-environment-and-library-constraints
- https://gist.github.com/LinusHenze/4cd5d7ef057a144cda7234e2c247c056
