# Load the Data helper through the iOS 27 service cache

The inspected iPhone12,1/24A446 donor contains
`/System/Library/xpc/launchd.plist` and its `LaunchDaemons` dictionary.
The signed original launchd references that path and contains the cached-service
restriction. Publishing a new plist directory entry alone does not establish
that launchd accepts or starts that job.

`myron-gpu/data_launch_cache.py` accepts only the previously inspected original
cache (2,474,924 bytes, SHA256
`5e0c65cf8ee4e6551325afdc4c283c350281d98e14f67b45bc55acfa536ae6e1`).
It adds `/System/Library/LaunchDaemons/org.unixnu.myron.data-grow.plist` with the
same root, one-shot helper job as the standalone plist. It refuses a preexisting
path or duplicate label. Removing the one new entry must reproduce the entire
original parsed cache, including every other top-level key and nested value.
Binary plist serialization is read back before publication.

The package reads the pinned cache artifact back independently, regenerates the
merge from its hash-verified original firmware plist, and requires byte identity
with the candidate. The ninth addon file is the resulting cache. Original Metal,
Turnip and helper executable bytes and the original Apple trust modules remain
unchanged. The existing whole-addon SHA256 binding also covers the new cache.

Cache preparation run `46085527736` at `f22c5a0d2166dea93576a7211062915621dbb2c6`
completed successfully. Independent artifact readback verified all 729 original
jobs and the one added job, including plist value types. The merged cache is
1,303,864 bytes, SHA256
`cc798dc8a2041266c97727d31d7b3c89301d6ac7231d82624b55d21e781f8273`.
The assembled addon is 15,691,928 bytes, SHA256
`00ec29159b04176d1588878eaa1d1e95f0dbcc0acee5d73076639de98a9e50ca`.
All eight previous addon files and the complete trust bundle retain their
previous byte identities. These checks do not execute the phone helper.

After all nine files install and verify, the boot path publishes the GPU view,
the helper's plist view, and finally a read-only union view over
`/System/Library/xpc`. The complete merged cache intentionally replaces the
original `launchd.plist` entry; other names retain lower-directory lookup.
Installation or publication failure records its stage and stops subsequent
publication without forcing a reboot. The persistent log includes both daemon
and cache publication stage/status. Stage 5 proves pathname visibility, not
helper execution or successful APFS resize.

The 16 GiB committed overlay selection, immutable seed identity, Data UUID
checks, growth authorization, durable attempt journal and refusal to retry an
uncertain resize are retained. There is no GPT change, Data reset, automatic
reboot, rollback to the old overlay or increase in GPU memory reservation.

Host checks cover exact cache delta preservation, malformed or colliding jobs,
changed artifact contents/report/source, all three actual mount calls and
failure paths, bounded persistent output, and the previously corrected 1/16 GiB
dyld startup gate. Native compilation and phone execution remain separate
qualification steps. Free space and application restoration must be verified
on the phone; cache preparation alone does not establish either result.
