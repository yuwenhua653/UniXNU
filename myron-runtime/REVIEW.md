# myron runtime update after build 45074791666

## Combined follow-up to 45115625273

That run failed in macos-geometry, before native compilation, because the new
boot-argument test redefined Darwin's `user_addr_t`. Namespace all fixture types;
do not change kernel typedefs or weaken compiler warnings. The generated guard is
executed with the actual payload argument, disabled/old arguments and an absent
plan. Empty preflight plans now refuse provisioning instead of stamping success.
The generated migration helper is also executed against vnode peers: exact owned
plist, changed/short/long records, missing record, wrong vnode type and I/O/unlink
errors. User-modified preferences are preserved; errors propagate to the caller.

The prior commit's unprefixed app boot-argument fix and volume-down/PON retry work
have not yet reached a successful phone package. User observations of missing
apps and both volume keys refer to the previous delivered package 45105158334.
Shutdown without a password was confirmed by the user; app migration, volume
buttons, GPU hardware and the newly staged frontend still require device evidence.
No persistent seed or working display/HID gate is replaced by this update.

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

Build 45103031177 stopped before native compilation: the boot-assets ADT fixture
still declared `ephemeral-storage=1`, while the durable Data validator correctly
required the property to be absent. Update that fixture in the reconstruction
step; retain wrong-root, stale memory range and dense RAMDisk rejection, and add
negative checks for both `ephemeral-storage=0` and `=1`. No production validator
or display, HID, keystore, app migration or GPU path is relaxed by this correction.
From a freshly reconstructed tree, all 11 boot-assets, 8 Data-volume, 6 RamBlock
and 6 Data-seed tests passed locally. Native compilation and macOS APFS integration
still require the replacement CI run.

## After device test of 45105158334

The owner confirmed shutdown no longer asks for a passcode. Apps are still absent;
neither volume key has an observable effect. These are device observations, not
host-test conclusions.

The pinned staged-app helper still parsed `sheng-staged-apps`, while the actual
payload supplied `staged-apps=1`. Normalize this specific upstream boundary to
`staged-apps`; keep the app allowlist, capacity reserve, exact migration-record
comparison, signed root authorization, persistent seed and completion fsync.
The new regression compiles the generated production enable guard and feeds it
the argument extracted from the reconstructed payload builder, with off/missing
and obsolete-prefix negative controls.

Add Volume Decrement as report 5 bit 2, sampled from PMK8850 SID0 PON 0x13
RT_STS bit 6. Source: K90PM-Development/android_kernel_xiaomi_sm8850-devicetrees
e94223220b86a2b8fb3103682f36f29b2ba7f309, qcom/pmk8850.dtsi (RESIN,
KEY_VOLUMEDOWN), canoe-mtp.dtsi and canoe-pinctrl.dtsi (GPIO101 Volume Up).
UniXNU docs/porting/input.md and its linked Sheng ButtonProbe implement the same
PON/RESIN press/release semantics; the myron SPMI v8 layout remains unchanged.
Keep the original Power and Volume Increment report bits and preserve independent
debounce, boot-held suppression and release. Remove the permanent failed-read
latch: retries stay bounded at 500 microseconds per 20 ms poll. Successful reads
after a fault re-arm only after a stable release. No PMIC registers are written.

Volume Up remains on the reviewed GPIO101 input with pull-only ownership checks.
Its remaining device failure is not established as fixed. Preserve raw PON and
GPIO level/config/availability and per-volume-key press counts in the existing
snapshot to distinguish no physical input from accepted HID without UI response.
The tests execute the production MMIO reader with fake windows, including pin
ownership rejection, pull restoration, both volume keys, timeout recovery and
all eight key combinations; they do not qualify physical GPIO or iOS audio UI.
GPU enablement and the known lack of a Metal/display-acceleration frontend are
unchanged in this correction.
