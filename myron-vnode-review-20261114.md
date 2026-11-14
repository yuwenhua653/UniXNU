# APFS vnode binding review, 2026-11-14

The tested kernel from build 43395897855 contains five APFS chained pointers
whose original `vnop_strategy` descriptor identity resolves to native
`_vnop_bwrite_desc`. This is a concrete binding defect. It is not yet proven
to be the cause, or the only cause, of the observed `buf_brelse: bad buffer`
panic during root mount.

Inputs independently read for this review:

- iPhone12,1 / 24A446 decompressed donor SHA256:
  `813be26ab6bd1d8de211904eca413a1a2ebf79989f90c33a48ff0f2fcff99036`.
- Previously tested emitted fileset SHA256:
  `cc18aed64e75919aa68b5f8ddbe6ec93332f3dc2048e1d8872f9445174c578e3`.
- Original descriptor: `0xfffffff00ac95568`, independently named by its
  chained `vdesc_name` field at +8 as `vnop_strategy`.
- Expected native descriptor: `0xfffffff00ac36fa0` (`_vnop_strategy_desc`).
- Actual target: `0xfffffff00ac36fe8` (`_vnop_bwrite_desc`).
- Affected APFS sites: `0xfffffff0080d9450`, `0xfffffff0080de3d8`,
  `0xfffffff0080de6f8`, `0xfffffff0080dea18`, `0xfffffff0080df640`.

The audit identifies 189 APFS chained descriptor references spanning 56 names.
The remaining 184 sites match. It does not validate instruction-encoded data
references, all APFS function imports, or runtime buffer ownership.

## Reference ports

- [ishtar porting record](https://github.com/markakash/UniXNU-ishtar/blob/main/porting.toml)
  reports iOS 27 Setup Assistant on 2026-10-30, following donor-specific import,
  vnode descriptor, launchd, Data and display work. Its older README/status
  fields lag those findings. This is a project report, not independent phone
  reproduction or proof of a usable desktop.
- [sheng startup repair report](https://github.com/UniXNU/UniXNU-sheng/blob/main/reports/ipados27-startup-repair-2026-11-02.md)
  reports iPadOS 27 root/SystemCryptex mounts and SpringBoard/backboardd processes
  after fixing original adapter branches, absolute GOT slots, vnode identities,
  and restoring Data inputs. It explicitly describes historical working-tree
  observations without publishing all raw artifacts; it does not prove UI.
- [fuxi iOS 27 lane](https://github.com/bangprovn/ios-fuxi/blob/main/docs-lanes/ios27.md)
  records `_kernel_task` misbinding blocking APFS root mount, followed by UPL
  incompatibility reading launchd. Its alternate read-only APFS route reaches
  later launchd/dyld issues; it is not an iOS 27 desktop success claim.
- [dada](https://github.com/superboyyy/hakios-arm64e-dada) describes iOS 26
  desktop work on Oryon. Do not count it as an iOS 27 success.

The branch already backports original adapter relocation/absolute GOT handling.
The tested image also has native `_kernel_task` imports for APFS and the four
other checked Apple modules, `_get_aiotask` in IOStorageFamily, and
`_IOCircularDataQueueCopyLatest` in IOHIDFamily. These are not missing merely
because the pinned XnuPrelink revision predates later upstream commits.

## Source correction and validation

Add 51 exact-name descriptor identities to the five already reviewed, keeping
all 56 pinned to the donor hash. Resolve rebuilt native addresses by symbol,
never by copying the numeric addresses above. Verify donor descriptor names
before prelink. Gate every desktop prelink variant and standalone replay on
the emitted 189-site audit before allowing packaging to proceed.

The real pinned XnuPrelink `Matcher.reviewed_data` resolves all 56 identities
correctly. The new gate rejects the old image at exactly the five listed sites.
A temporary checker-only specimen with those five pointers corrected passes;
restoring one bad site is rejected. The specimen is deleted and is never a
boot artifact. Source reconstruction, Python syntax and existing six final
buffer-trace contract tests pass.

No new full build is requested by this source commit. Build 43541303792 was
already running at review time and does not contain these new bindings.
The local artifacts lack the native unprelinked kernel and LTO `.noctf`
reference needed for a genuine prelink replay. A fresh emitted and packaged
image, then a phone observation, remain required before claiming boot progress.
