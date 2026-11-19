# Myron first-frame startup dependency

The tested run 44481576289 reached the registered GOP service but recorded no
accepted or rejected swaps and no copied frame. Its retained launchd output
records liveactivitiesd exiting through SIGTRAP and crashing 16 consecutive
times. The earlier GOP readiness repair remains necessary, but those counters
do not establish that it explains the missing first submitted frame.

## References and version boundaries

- [Official display integration](https://github.com/UniXNU/UniXNU/blob/8542980d02b4d2cc5c32ee3542de1760b2562aac/docs/porting/display.md).
- [Official log capture](https://github.com/UniXNU/UniXNU/blob/8542980d02b4d2cc5c32ee3542de1760b2562aac/docs/porting/log-capture.md).
- [Official component catalog](https://github.com/UniXNU/UniXNU/blob/8542980d02b4d2cc5c32ee3542de1760b2562aac/components.toml)
  lists AppleKeyStoreState for iPadOS 27.0.1 24A446. It does not claim myron hardware verification.
- [Sheng board integration](https://github.com/UniXNU/UniXNU-sheng/blob/c8f92b208068eeaa4cd2b0f592671f04ee70076e/package/KeyStoreProbe.cpp)
  registers the shared service after IOKit initialization and supplies board identity.
- [QEMU welcome-screen record](https://github.com/xVanTuring/UniXNU-qemu/blob/97b75b1f63c6b7e895cd7646029db741d5fe5488/README.md)
  describes SpringBoard waiting on chronod, chronod waiting on liveactivitiesd,
  and the latter trapping when MKBEventsRegister cannot find AppleKeyStore.
  **That observation is iPadOS 17, not evidence that myron has booted iOS 27.**
- [Pinned shared component](https://github.com/UniXNU/AppleKeyStoreState/tree/6ff4f11d8fdf853351f8d98e1bbe1373fb8da2e6).
  Source, license and upstream test are vendored without content changes.

## Exact iPhone 24A446 static check

The original iPhone12,1 shared cache and its matching symbol/subcache UUIDs
were checked locally. No donor instructions were modified. Unslid addresses:

| Site | Original behavior |
| --- | --- |
| MobileKeyBag MKBEventsRegister `0x1aeb9ec04` | Matches the class string `AppleKeyStore`; zero matching service branches at `0x1aeb9ec5c` to a NULL return. |
| SessionSyncEngine Keybag.shared `0x2a2eaed64` | Its once initializer calls the IOSKeybag initializer at `0x2a2ec9340`. |
| IOSKeybag `0x2a2ec963c` | Calls cache stub `0x2a80bae00`; the stub branches directly to MKBEventsRegister `0x1aeb9ec04`. |
| IOSKeybag `0x2a2ec964c` | A NULL result branches to `BRK #1` at `0x2a2ec9678`. |

This verifies that the version-specific failure mechanism still exists. The
phone log's SIGTRAP does not include the liveactivitiesd fault PC, so it is a
strong matching explanation, not a measured PC attribution or a promise of UI.
The current source has no AppleKeyStore service registration. Original
AppleSEPKeyStore is not a provider on this non-SEP platform.

## Change

Compile AppleKeyStoreState with the prepared kernel's C++ recipe. Remove its
automatic initializer, explicitly register its classes after IOKitBSDInit,
and publish it before BSD initialization returns and launchd starts. Preserve
the existing root, Data and display initialization. Refuse registration when
the original service class already exists or the device identity is absent,
zero, short or oversized. Keep an explicit `myron27-keystore=1` package policy.

The service answers the reviewed state/bookkeeping selectors and implements
the upstream software key wrapping. It is **not hardware-backed SEP data
protection**; passcode, device locking and reference-key operations are not
implemented. The board identity is never printed. No constant identity or
invented hardware-success response is supplied by the board.

Preserve service registration, open counts, selector results and first error
in each existing reserved-log snapshot, before the rolling console. No new
partition or unbounded logging is introduced. The native final-symbol checks
require both classes, late initializer, startup and snapshot entries.

## Validation and next device observation

The preflight-only commit runs the unchanged upstream selector/DER/key-wrap
test and the actual board probe against host lifecycle doubles with ASan and
UBSan. It checks 15 startup/failure cases, one-time initialization, identity
boundaries and snapshot capacities. It does not start the full native build.
The existing full build remains gated on preflight checks and strict native
link/prelink validation. Host tests do not establish real IOKit publication.

On the next useful device run, require `registered=1`, successful state-query
calls and absence of the repeated liveactivitiesd SIGTRAP loop, then inspect
whether display validations/copies start. If a blocker remains, retain its
selector failure or process fault rather than interpreting log scrolling as
progress. Welcome-screen/desktop success still requires a device observation.
