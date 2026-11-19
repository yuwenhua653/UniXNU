# Firmware GOP presentation readiness

The 44481576289 phone test retained console output successfully but still recorded
zero accepted/rejected frame validations and zero copies. This does not establish
that the compositor submitted a frame. The client counter counts open attempts,
not the number of currently live rendering clients.

Source review found an independent, deterministic presentation defect:

* `MyronDisplayProbe.cpp` rejects `offline-legacy-pm != 0` for this board.
* `startDisplay` leaves `logicalPM == false` when that option is absent.
* Both `validateSwap` and `kickOnce` nevertheless required `logicalPM`.

Consequently a valid submitted frame could never be accepted/copied with the
shipping board configuration. The compiled validator in kernel SHA256
`704a67f9b631ca246becf20ec1341b8188b33677a06e9dcfea29a6dcf7a157fc`
contains the corresponding boolean check at `0xfffffff00aa4702c`.

The fix uses successful original powered-state publication plus the mapped
primary GOP as the presentation prerequisite. Optional PM-tree lifecycle remains
separate and disabled. Stop, free, and startup failures revoke presentation
readiness. The original request geometry, pixel format, descriptor bounds,
completion and surface ownership checks remain in force.

The exact 24A446 original `applyStateRequest` implementation at
`0xfffffff009a3e4ac` was reviewed against the existing state-request layout:
requested skip/value at 0/4, powered skip/value at 8/12, changed byte at 16.
No donor addresses, vtable slots or authentication discriminators were changed.

`test_myron_display_lifecycle.py` executes the actual startup and validation
methods and the actual entry gates of `kickOnce` against IOKit/IOSurface test
doubles. It checks PM-disabled acceptance, invalid-surface rejection, failed
state publication, absent mapping, and both legacy-gate negative controls.
The macOS sanitizer test runs before the expensive native package job.

## Remaining uncertainty

This repairs a reachable presentation-path defect; it does not explain why the
captured phone test has **zero validation calls**. Do not call it a confirmed
desktop-start fix before phone evidence shows actual frames.

The exact arm64e iOS 27 QuartzCore cache has a software fallback:
`AccelServer::render_update` branches to `Server::render_update` when its Metal
renderer is null; the latter requests `sw_renderer`. Absence of the GPU stack
alone is therefore insufficient to identify this particular stall. Execution of
that fallback on this phone has not been established.

The updated persistent display summary reports powered-state publication and
kick/no-head/not-ready counts to distinguish an upstream no-frame condition
from driver-side rejection. It still does not report user-space renderer thread
stacks or prove desktop availability.
