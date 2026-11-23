# myron runtime update after build 45074791666

The phone boots to SpringBoard, with delayed side-key response, an unexpected
passcode prompt during shutdown and only Settings visible. GPU acceleration has
not been observed. This update preserves the exact initial Data seed and the
existing authenticated OS/SystemOS/UFS and real display submission gates.

- Report SLS 3 (no keybag/passcode) from the owned state-only AppleKeyStore.
  Unsupported selectors continue to fail; no user passcode is cleared.
- Reuse packed seed 528d1c330b73d799ef1b6fa49c4b46d4d4ad69b8537e6acec617468c45568611
  from run 45074791666. CI checks the previous boot, FAT, packed and logical
  hashes, then mounts the unpacked seed read-only. A foreign seed is refused.
- Declare the actual seed-bound UFS Data persistent in ADT. Previously the
  ephemeral-storage property survived after UFS persistence was added.
- Restore the upstream original-system-app copy hook. Choose complete original
  app trees up to 384 MiB by measured allocation and retain 384 MiB free. The
  runtime rechecks available space, stops on copy error and uses separate user
  scratch so it cannot corrupt SystemOS's launchd environment. Only the exact
  synthetic migration-complete plist this port generated may be removed; userland
  changes and SetupDone remain intact. A durable marker follows a successful copy.
  The app list and omissions are emitted in system-apps-plan.json. This is bounded
  provisioning, not a claim that all Apple apps fit or run on this port.
- Preallocate the button HID input descriptor. Add real volume-up held/released
  state at GPIO101, with independent debounce and combined side/volume reporting.
  GPIO input ownership must match; only the pull is changed and restored on stop.
  Key timestamps distinguish sampling delay from downstream UI delay; seconds of
  latency are not established as fixed. Volume-down remains unimplemented.
- Enable the existing native A840 hardware worker only when the bound native build
  report has compiled GPU objects and verified embedded firmware. Enablement is
  derived from the report, not an environment variable lost across sudo. Keep the
  bounded BO pool and two real client/fence/readback qualification rounds. Persist
  the result summary in boot logs. No Metal accelerator/plugin or GPU scanout is
  advertised by this change; frontend and userspace integration remain unfinished.

References: UniXNU/UniXNU 04573c510c5fd4892ca6948739389141cc9e05f5
(system-app hook and persistent ADT), current AppleKeyStoreState documentation,
Typeun/myron-device d9b6be4d75f5a8169aee65b02bb23cd88968c1eb
(package/HidInputProbe.cpp and board.toml), and the already pinned NativeAdreno
5bbeb3b8d049a637a595090319835a49e58a8b56 backend.

Host validation: exact seed unpack/hash and bit-flip rejection, app budgeting and
source-transformation failures, production Data mount authorization failures and
app-hook ordering using the patched pinned XNU exec source, software keystore
selector/registration tests, durable overlay reopen/mismatch and button-combination
tests, portable GPU power/GMU/HFI/command-DB and backend ring/CP/IRQ/timer/pool tests.
Native arm64e compilation and final payload checks run in CI. These checks do not
prove handset shutdown, application migration, latency or GPU hardware success.
