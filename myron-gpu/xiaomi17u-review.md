# Xiaomi 17 Ultra reference review

Reference: [u0er/unixnu-xiaomi17u](https://github.com/u0er/unixnu-xiaomi17u/tree/4c373f26d55f5db0af5e603437d080a5b833fa49),
reviewed at commit `4c373f26d55f5db0af5e603437d080a5b833fa49`.
No source, CI or device in that project was modified.

## What it establishes

This is a valuable **native SM8850 GPU** reference. Its workflow selects XNU
8796 / macOS 13.5-era sources, and `tools/metal/adapt_ios16.py` explicitly targets
iOS 16.7. It is not evidence of an iOS 27 build. The maintainer's
`COORDINATION.md` records desktop/icons/wallpaper verification and reduced
shadow-copy traffic. The referenced `turnip` run **43602780936**, commit
`8b1d5570df384c18ae52ff539468d2f1ce9702eb`, was independently checked through
the Actions API and completed successfully. That verifies CI status; the
physical observations remain the maintainer's reported evidence.

## Applicable findings

| Source | Finding | Myron action |
| --- | --- | --- |
| `0165`–`0175` GPU patches | Native GMU/SMMU/HFI, GX vote, CP, ZAP and fenced submission sequence | Cross-check against Typeun and the owner's 3.0.306 firmware. Same SoC does not imply the same OPP tables or reserved memory. |
| `0182-pandora-gpu-chipid-files-chunks.patch` | Advertised chip ID includes the active slice count | Confirmed independently in Qualcomm `adreno_gen8.c:gen8_get_gpu_slice_info`. Base DT ID `0x44050a01` becomes `0x44050a31` when three slices are enabled. Added checked derivation and failure handling to the staged myron board path. |
| `0194-pandora-gpu-128-ibs.patch` | Splitting command submissions at 16 IBs caused hangs in the recorded workload; both ends use 128 | Selected a8xx backend already declares 128. Match Turnip's wire struct to it; do not change one endpoint alone. |
| `0318`, `0327`, `0328` | Buffer lifetime, stale handles and state restoration across clients matter | Keep ownership and true completion checks in the native backend; compare the full submitting path, not just the ring start. |
| `0453-pandora-gpu-preserve-free-extents-and-initialization.patch` | Fixed-size free extent accounting could lose memory; zeroing failure must fail allocation | Review the chosen backend's allocator independently; this patch modifies a different allocator and is not applied blindly. |
| `0061`, `0125`, `0126`, `0333`, `0339` | UIKit sees an iPhone-sized logical canvas; presentation scales it to the physical panel and input uses the matching transform | The UI correction requires matching logical dimensions, scale, artwork and touch mapping. Changing only `display-scale` is not established as sufficient. |

The new `mg_a840_chip_id()` host tests cover all nonzero three-bit slice masks,
zero, failed MMIO and an all-ones fault result. The staged board call-site now
propagates CX_MISC read failures and refuses publication unless the existing
three-slice/18 MiB GMEM configuration actually matches. It does not pretend to
support a different slice topology. This remains an unlinked integration patch,
not a compiled phone GPU fix.

## Boundaries to preserve

* `_MTLDevice` 528/536-byte fixes in `adapt_ios16.py` belong to iOS 16/17.
  Our iPhone 27 shared-cache ABI must be derived separately. The 136-byte
  **IOAcceleratorES** kernel base audited here is a different class.
* The reference's GMU frequency table has four active entries in patch 0167;
  myron's extracted 3.0.306 DT has two. Do not overwrite myron's table with it.
* `0459-gpu-hang-recovery-advance-fence.patch` writes the pending fence number
  into the completion memory even though its comment says the GPU remains
  stuck. Do **not** import this behavior: waiters could treat unfinished work
  as complete. Preserve actual completion, fault reporting and display gates.
* `0454` fixes the reference's replacement SweetSurface selector. Our port
  uses the original iPhone IOSurface implementation; its offset constants and
  fake framebuffer ABI are not interchangeable with ours.
* Its Synaptics/TouchComm input changes are not for FT3683. Keep the working
  myron touch driver, and change coordinate mapping only alongside a tested
  logical-display transform.

Next integration should use this project as an additional hardware/display
reference, the a8xx native backend for submissions, and target-derived iOS 27
kernel/userspace bindings. It does not remove the remaining service, Metal
addon, trust bundle and boot-capacity work listed in README.md.
