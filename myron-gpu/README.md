# Myron iPhone 27 GPU integration checkpoint

This directory is **not enabled by the production build**. It contains reviewed
portable components, a real HFI wire-length fix, and a target-specific accelerator
ABI audit. No new phone package or GPU-success claim follows from these tests.
The desktop baseline remains run 45008031354 / commit 682c5c4.

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

1. Adapt the native board service to this port's 2 GiB owned RAM, real interrupt
   API and power/thermal policy. The reference's 1 GiB GPU pool and maximum
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

No kernel compilation is requested by this checkpoint commit. The current
working desktop is not replaced by a partially connected GPU driver.
