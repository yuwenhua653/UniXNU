# myron: PID 1 DYLD exit after run 43575774754

## Phone evidence and limits

The user's PXL_20261114_111842063.jpg shows process signature accepted, then
launchd PID 1 status 0xb, reason namespace 6 and code 1. Apple XNU defines
namespace 6 as DYLD; dyld defines code 1 as DYLIB_MISSING. This is a dependency
load failure class, not proof that a specific file is absent from disk.
No desktop or successful launchd initialization is established.

Tested kernel SHA256:
`d118a67db687def0cffbe1ca792c5d76040dc7596e06821521b4d0ca9e6e8247`.
PC `0xfffffff00aaa0f14` is the return address after the panic call at
`0xfffffff00aaa0f10` in `_proc_prepareexit.cold.1`. The adjacent symbol at the
recorded PC is not the failing instruction. The ordinary panic observer's
zero ESR/FAR values are not a captured user exception.

## Concrete integration gap

The current root variant mounts authenticated SystemOS at `/private/preboot`
and checks all 78 shared-cache members before launchd. However, native
`shared_region_map_and_slide_setup()` normally accepts root or the mount
located through `/private/preboot/Cryptexes`. The existing upstream optional
owner-cache carrier is compiled out: no carrier symbols exist in the tested
kernel. Its default UUIDs belong to a different input set and cannot simply
be enabled unchanged. Fuxi documents the same class of missing-cache failure.
This gap is consistent with the photo, but the missing dyld description
prevents identifying it as the sole observed cause.

## Changes

- Recompile `vm_unix.c` only for the signed-root candidate, using its original
  native compiler recipe; replace its object under the existing hash/restore
  mechanism. The nine-unit preflight now includes this source before linking.
- Enable the existing carrier with OS/SystemOS UUIDs from validated build
  inputs; require distinct devices, read-only APFS mounts, the exact cache
  directory parent, and authentication of both devices. File/signature/map
  checks after the carrier remain unchanged. Compiled export/import checks
  and retained symbols reject an absent carrier.
- Before critical-process panic, show the existing kernel-owned exit
  description, bounded to 800 bytes and wrapped into persistent screen rows.
  Keep original panic policy, sync, arguments and diagnostic caller behavior.
- Run focused carrier and exit-renderer tests before the expensive native
  build. No root partition reinstall or new backup requirement is introduced.

## Validation completed

- Exact pinned XNU patch application for affected source paths.
- Real carrier and native mount-decision host execution; valid SystemOS,
  24 provenance failures, invalid UUIDs, missing legacy Cryptex path.
- Entire following file/signature/map source is byte-identical. The test's
  downstream signature rejection is simulated, not real signature execution.
- ASan/UBSan: 800-byte non-NUL input, narrow/wide wrapping, control/null/empty
  strings, IRQ/mount redraw, first panic, framebuffer ownership, disabled hook.
- Existing recorder regression test passes.
- Fresh reconstruction from the modified delta passes both focused suites;
  Python syntax and git whitespace checks pass.

No Apple SDK/native compilation or phone test of this change has run. The
modified nine-unit failure fixture awaits its full CI root-fixture environment.
Local clang was unavailable; do not label these host checks an arm64e build.

## Reviewable publication scope

Four top-level source/review files are proposed for the existing public
`yuwenhua653/UniXNU`, branch `codex/myron-iphone27`, based on remote commit
`5ffaa2b8a4ea02ec66cbd186b1919bff4a66e62d`:

- `myron27-storage-delta.json` (six changed/added embedded source files)
- `myron27-build.py`
- `tests/test_myron_exit_reason.py`
- this review

The prior fresh-PC packaging-script commit is not part of this source update.
No uploaded photo, phone backup, credentials or device input archive is included.
No remote update or new build has been performed for this patch.

## Primary references

- https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/bsd/sys/reason.h
- https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/bsd/kern/kern_exit.c
- https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/bsd/vm/vm_unix.c
- https://github.com/apple-oss-distributions/dyld/blob/main/include/mach-o/dyld_priv.h
- https://github.com/UniXNU/UniXNU/blob/04573c510c5fd4892ca6948739389141cc9e05f5/patches/xnu-12377/offline-owner-cache-carrier.patch
- https://github.com/bangprovn/ios-fuxi/blob/main/docs-lanes/ios27.md
- https://github.com/bangprovn/ios-fuxi/blob/main/xnu27/patches/fuxi/0009-cryptex-graft.patch
