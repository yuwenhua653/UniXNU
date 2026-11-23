# Myron iPhone 27 GPU integration checkpoint

## iPhone27 userspace integration

`prepare_userspace.py` now resolves the official arm64e AdrenoMetal/metal2vulkan
build recipes at recorded revisions, with the same 128-IB A840 ABI as the kernel
and the board's recorded Mesa patches. The selected Mesa revision contains the
three-slice A840 device table (six CCUs, 96x32 tile alignment). All nine patches
have been applied and reversed against that exact source revision locally.

The board overlay excludes the iPad 24A446 QuartzCore fixed-address writes and
delayed reader, and the older iPad diagnostic stack-offset reader. It does not
substitute guessed iPhone offsets. The A740 command replay is disabled. The
official arm64e Rust callback wrappers and indirect-branch rewrite precede signing.

The Metal mailbox and native poller now use a distinct `MAI2` layout, carrying
the full 3104-byte submit instead of the old 1792-byte maximum. Old peers are
refused, requests are serialized, a timeout prevents reuse of its live request,
and a close/reopen cannot inherit a stale acknowledgement. The ordinary Turnip
direct/tunnel path now rejects short successful replies. Tests compile the
actual staged poller/client methods and the actual Turnip transport block.
They cover 128 buffers, overlarge messages, backend errors, timeout/late replies,
sequence wrap, old-peer rejection and replacing the connection during dispatch.
These are host tests, not hardware completion evidence.

The `Myron iOS27 A840 userspace` workflow builds actual Turnip, the Rust bridge
and the 4 KiB-signed plugin, then checks arm64e Mach-O types and signature hashes.
Its candidate addon has no publish marker and does not replace the Data seed.
It is a component artifact, **not a flashable package**. The accelerator's
retained iPhone bindings, target trust-module merge, boot capacity and real
display handoff still have to be connected before a phone test package.

The iOS bridge carries the translator's existing Mach page-read and mapping
permission implementation over to iOS; it does not treat an unreadable or
unwritable range as valid. The complete arm64e bridge build qualifies this
source change; a host compile alone does not verify phone rendering.

In particular, the current `MyronDisplayProbe` fence-query exports still report
no GPU provider. The CPU scaled-copy path has not acquired a GPU producer fence;
the existing fence timer is created by the direct-DPU path. Publishing Metal
before wiring that ownership boundary could read an unfinished GPU surface.
Do not enable the plugin merely because the userspace build passes. Likewise,
the upstream `make-owner-trust-bundle.py` fixture belongs to a different target;
merge only this build's signed CDHashes with this iPhone's unchanged trust input.

```sh
python3 myron-gpu/prepare_userspace.py --fetch --references /tmp/metal-refs \
  --native-references /tmp/native-refs --out /tmp/myron-gpu-userspace
# macOS with Xcode, Bison >=3.7, glslang, shaderc, SPIRV-Tools, LLVM,
# Ninja and Rust 1.98.0 + rust-src:
python3 myron-gpu/build_userspace.py --tree /tmp/myron-gpu-userspace
```

The first native A840 board driver is now connected to source reconstruction,
optional XNU compilation and the late boot boundary; see [native/README.md](native/README.md).
Production still uses the working CPU display. The native A840 backend and its
four firmware blobs compiled and linked in run 45105158334 / commit b5f2ec2;
that package enables the bounded hardware worker. Phone GPU execution and Metal
userspace/addon integration remain unverified.

## Combined update after failed run 45115625273

The runtime app guard's test used a Darwin-owned typedef and failed before native
compilation. Its fixture types are now private. This update also extends GPU work:

* Turnip's Darwin device-identification block now recognizes A840 while retaining
  its active-slice chip ID. The old arithmetic produced 6860 for `0x44050a31`.
  The actual patched block is compiled and exercised, including A740, A630,
  all seven nonzero slice masks and unrelated-ID negative cases.
* `scripts/build-turnip-darwin.py --target ios27 --native-adreno DIR` selects
  arm64e/iOS 27 and rejects a header different from this native A840 kernel's
  pinned ABI. The build identity includes that header. Compile-time checks cover
  the 128-IB / 3104-byte submit record and 64-byte device identity.
* `MyronAcceleratorCandidate.cpp` implements the plugin-type client entry and
  preserves real hardware readiness. The native build compiles it with its actual
  XNU recipe, checking extent, 168 authenticated slots and original-base imports.
  It deliberately remains outside the linked object/initializer set: iPhone
  retained-base binding, complete Metal plugin/addon and trust integration are
  still required before it can be published. No extra desktop service or fake
  hardware completion is introduced.

These changes do not claim a working Metal device. Full Turnip/Metal compilation,
addon packaging, target binding and device rendering remain follow-up work.

## Same-SoC references checked on 2026-11-22

| Project | What its evidence supports | Use for this port |
| --- | --- | --- |
| [YMGPwcca/OneiOS, SM8850 branch](https://github.com/YMGPwcca/OneiOS/blob/fc3bfd26fdce45df1ba3243260501693cbf5b21c/docs/SM8850_LIVE_STATUS_2026-11-20.md) | Galaxy S26 Ultra, iOS 27 hosted execution, first frame and active KGSL/drm2kgsl context/import/fence path; not sustained 60 FPS | Study iOS 27 frontend and fence contracts. Its Android-hosted KGSL path does not supply a bare-metal XNU GMU/SMMU driver. No OneiOS source is copied here. |
| [Typeun/myron-device](https://github.com/Typeun/myron-device/tree/d9b6be4d75f5a8169aee65b02bb23cd88968c1eb) | Same board, native Adreno 840 work, iPadOS 17.7.11 reference | Board clocks, command DB, GMU startup, firmware parsing and HFI. These portable sources retain their license. |
| [zg7681/NativeAdreno-myron, a8xx](https://github.com/zg7681/NativeAdreno-myron/tree/5bbeb3b8d049a637a595090319835a49e58a8b56) | A8xx register selection, ring, CP init, interrupt and timer implementation | Correct A840 backend candidate. Do not silently combine its older five-buffer backend with the current eleven-buffer upstream VM implementation. |
| [u0er/unixnu-xiaomi17u](https://github.com/u0er/unixnu-xiaomi17u/tree/4c373f26d55f5db0af5e603437d080a5b833fa49) | Native SM8850 GPU stack; maintainer reports desktop rendering on iOS 16.7 | Hardware identity, submission lifetime and logical-display mapping. See [the detailed review](xiaomi17u-review.md); do not import its synthetic hang-fence completion. |
| [UniXNU GPU porting](https://github.com/UniXNU/UniXNU/blob/8542980d02b4d2cc5c32ee3542de1760b2562aac/docs/porting/gpu.md) | Native driver and iOS 27 Metal/Turnip packaging contract | Native client, target-specific bindings, GPU addon and matching owner trust. |

The checked public sources did not establish a complete, directly reusable
**bare-metal SM8850 + iPhone iOS 27** GPU stack. This is a statement about the
sources checked, not proof that no other implementation exists.

## Changes and evidence

* `MyronHfi.c/.h` now records the actual packed performance payload length.
  `power-hfi-length.patch` changes the reference caller to send that length.
  With a command DB limited to seven GX levels, the wire payload is 33 words,
  not the maximum 69. A wire-walking test checks the following CX table too.
* The same power-path patch also derives the A840 user-space chip ID from the
  hardware slice mask, propagates read failures, and checks that it matches
  the three-slice GMEM setup before publishing. Portable identity tests pass.
* GMU tests now check the owner's **OS3.0.306.0.WPMCNXM** image: version
  `0x50030023`, instruction-cache payload `0x1b260`. Its GMU and ZAP files differ
  from the reference board bundle; SQE and AQE match. Extracted file hashes are
  in `firmware-3.0.306.json`. Firmware bytes are not included. The entire OTA
  archive was not downloaded or authenticated by these checks.
* `audit_iphone27_accelerator.py` checks the actual desktop kernel's 136-byte,
  168-slot IOAcceleratorES base, its constructors, real IOService imports and
  pointer authentication metadata. Only destructor/metaclass slots differ
  from IOService. Three deliberate binary corruptions are rejected. This
  prevents using the upstream **iPad** 24A446 address fixture for this iPhone.
* `ui-3x-candidate.patch` records a proposed 3x artwork/layout configuration
  from the same-board reference. It is **not applied**. Its effect on text and
  the battery icon still needs verification; it is not a confirmed UI fix.

Run portable checks with an ASan/UBSan-capable C compiler:

```sh
python3 myron-gpu/check_host.py --cc cc --firmware /path/to/306-firmware --output host-checks.json
python3 myron-gpu/audit_iphone27_accelerator.py \
  --kernel /path/to/final/kernel.macho --kernel-sha256 SHA_FROM_MATCHING_MANIFEST \
  --xnuprelink /path/to/XnuPrelink --output iphone27-abi.json --negative-controls
```

`host-checks.json` and `iphone12-1-24A446-abi.json` record this checkpoint's
successful host checks. They do not prove hardware startup, Metal rendering or
phone UI correctness.

## Integration still required

1. Qualify the newly adapted native service against actual XNU and the phone.
   Its first stage bounds the BO pool and OPP, and polls real fences.
   A real interrupt attachment and thermal policy remain pending. The reference's 1 GiB GPU pool and maximum
   speed-bin vote must not be enabled unchanged. The stock DT chip ID is
   `0x44050a01`; `0x44050a31` is its three-active-slice user-space encoding.
   The staged path now derives it from checked hardware readback.
2. Build the A840 backend and iPhone-specific arm64e accelerator against the
   actual XNU headers. Preserve firmware/SMMU ownership, fenced submissions
   and the existing real display retirement gates. Retain working FT3683 HID.
3. Build matching iOS 27 Metal/Turnip userspace and verify the iPhone shared
   cache bindings. Use native client type `0x4147`; the hosted `0x4149` transport
   is a different interface. Account for the separate SQE allocation in every
   GPU address space.
4. Package the runtime addon with its matching trust bundle and validate boot
   capacity: the current 88 MiB FAT cannot be assumed to fit extra userland.
   Apply UI configuration consistently to source reconstruction and final
   embedded-ADT verification before a combined test build.

The source-check workflow compiles portable/backend host tests; it does not start a full kernel build. The current
working desktop is not replaced by a partially connected GPU driver.

The runtime integration now pairs chosen/artwork scale at 3 and adds physical power input and seed-bound Data persistence. The combined device workflow fetches pinned OTA operation ranges and compiles A840 native code with real XNU recipes. Its boot hook remains opt-in; Metal userspace and accelerator publication are still pending.
