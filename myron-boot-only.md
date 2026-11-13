# Firmware-only iteration for the installed iOS27 root

Use `.github/workflows/myron-boot-only.yml` for the reviewed BDS-only changes.
It reuses the exact successful run 43349357896 startup image and only rebuilds
the 3MiB UEFI FD. It does not invoke the native XNU compiler, download an IPSW,
recreate root media or request owner signing inputs. It uses Ubuntu/Clang 18,
matching the compiler generation recorded in the R58 baseline.

`myron27-boot-only.py` verifies a pinned baseline commit, manifest and image,
then rejects any changed payload/loader source. The only admitted source delta
is the reviewed BDS firmware snapshot, its snapshot pin and reviewed memory
contract update. Other firmware modules must remain unchanged. Broader fixes
require an explicit review of this scope; do not bypass the source gate.

The original Android header, shim and entire 88MiB FAT remain byte-identical.
The original root image and owner policy carrier descriptors remain unchanged.
The real retained FAT is re-read through the staged loader's host tests, then
the fresh FD is unpacked and matched to its compiled PE modules. Its capsule
must match the bytes executed by QEMU. The final assembler only replaces the
FD range, and rechecks the baseline before output. Reports distinguish reused
payload qualification from the new firmware checks.

The GitHub artifact is `myron-ios27-firmware-only-candidate`. It is a candidate,
not a request to flash manually. A new device companion must bind its image
hash to the existing original Android backup and completed unixnu receipt.
The previous companion intentionally rejects a newly built image.

The source artifact has a retention limit. If it is unavailable, this workflow
fails; it never silently downloads an unrelated/latest image or falls back to
an expensive full build. Restore the exact archived baseline before retrying.
Full build remains available for actual kernel/root/loader changes.

## R58 comparison

The archived R58 source snapshot is commit
`a4e9f6e36fdba6d92efe43c2cd95163e2c520ac1`. Its five Mu repository pins match
current preparation. Of 64 board files directly matched by path, 58 are
byte-identical. Differences include the later 2GiB memory policy, generated
FAT header, BDS banner/progress and two INF staging transformations. Those two
INF removals are already performed by R58 `prepare_minimal.py`; they are not
new evidence of lost initialization. This comparison is partial source
comparison, not proof that all compiled firmware bytes match or that the
four-stripe root cause has been identified.

Do not interpret build acceleration, phase labels or host tests as phone boot
progress. Device success requires a new observed boot milestone.

## First completed firmware-only run

Run https://github.com/yuwenhua653/UniXNU/actions/runs/43361559288 at commit
`b26aca1c767e93b1702fabcf76f780d88d19031f` completed successfully. Runner time was
132 seconds (2026-11-13 03:50:11–03:52:23 UTC); the build/test script measured
82.3 seconds. All 13 reuse tests passed. The fresh FD contained 35 verified
modules and 493 checked compilation commands. Actual future duration depends
on queue/network/tool installation; this is a measured run, not a time guarantee.

Candidate boot SHA256:
`ecbd5ae2af2fa94c2cb6fa3bb37d2616667f6ceab5b8f0111f2beeeec8e0a8be`.
The first attempt stopped early on an existing empty gitlink directory; the
checkout fix preserves non-empty paths and is covered by two regression tests.

A subsequent Git tree comparison of upstream commits
`56aaad72df854febb77ee67a68ed486d0d882f1b` (R58 sources.json) and
`04573c510c5fd4892ca6948739389141cc9e05f5` (current build) found all 56 files
under package/ identical by blob SHA. Menu.c and Config.c were also fetched
and compared directly. The earlier suggestion that reverting the menu source
would by itself restore the old behavior was insufficiently grounded. This
is source identity, not compiled-image identity or proof of the fault location.

Board snapshot edits automatically select the firmware-only workflow unless
the commit explicitly requests the full device build. The strict reuse gate
still rejects kernel/loader changes. Documentation/trigger-only maintenance
may skip CI when executable build/test code and input snapshots are unchanged.
