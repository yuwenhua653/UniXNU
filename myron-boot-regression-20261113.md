# Myron boot regression investigation

The installed device package from run 43165530177 passed live GPT matching,
double-read Android boot backup, and unixnu installation/readback. The phone
then remained at the Xiaomi logo with four colored lines. Their positions and
colors have not been captured for this attempt. This does not identify a
specific XNU instruction or prove an iOS userspace boot.

## Recovered baseline evidence

- R58 source commit `a4e9f6e36fdba6d92efe43c2cd95163e2c520ac1` and its
  device-confirmation archive record stage 0x60, revision 0x58 and 26 timer
  interrupts. This was a stop before IOFindBSDRoot, not a mounted root.
- R90 source commit `bed77a18520aa8cc1e85c3b0369c95865316e127` includes the
  R89 video analysis: PreBoard processes ran and repeatedly exited with SIGTRAP;
  completed display frames were zero. This is later runtime evidence than R58,
  but does not prove a desktop or qualify R90 itself.
- R90 used an ARM64 21H461 image and `boot-progress=2`. The current ARM64e
  24A446 build has neither CONFIG_XNU_BOOT_PROGRESS enabled nor that argument.
  Adding the argument alone would not restore the compiled-out observer.
- The raw BootShim execution path is retained. Its payload-size header and
  register now describe 88 MiB instead of 64 MiB. The current loader additionally
  exercises PAC key access and real signing/authentication at EL1 and EL0.
  Previous ARM64 device success does not qualify those operations through EL2.

## Change and validation boundary

Render a persistent 16-digit phase before cache maintenance and each PAC
boundary, including before the first key register access that could trap to
EL2. An EL1 exception handler cannot report an exception handled outside EL1.
Keep the existing 8 KiB capsule, four-times glyph scale, key values, PAC tests,
MMU handoff and kernel/root bytes unchanged by this source change.

| Phase | Next operation |
| --- | --- |
| 2700 | Owned-memory and framebuffer cache maintenance |
| 2701 | PAC key register read/writeback |
| 2702 | EL1 PAC round trips |
| 2703 | EL0 round trips and checked SVC return |
| 2704 | Final band and branch to the kernel |

The last phase does not prove XNU entry. None of these markers claim a root
mount or desktop. Actual rendering is checked at the synthetic QEMU entry,
with a sentinel beyond the 384-pixel row; existing missing-PAC, broken signing,
EL0 failure and incorrect-SVC controls remain required. The complete native
build is gated on these tests. A separate small boot artifact is exported only
when its root-container identity still matches the installed package.

Current phone root and Android backup should be preserved. Any eventual boot
update must bind the old manifest/installation receipt and verify the new image
independently; replacing those records to bypass checks is not an update method.
