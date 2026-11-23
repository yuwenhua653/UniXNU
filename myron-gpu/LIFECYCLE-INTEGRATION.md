# iPhone27 GPU client lifecycle checkpoint (2026-11-23)

Base: `724be5a576e7a5805dc83fe74c72df626a8f1ca2`, branch
`codex/myron-iphone27`. This checkpoint changes source and host qualification;
no Actions run, native kernel build or phone test was performed. The last phone
capture still reports CP=0 and ready=0. The preceding UBWC6 fix is preserved.

## Fixed in this checkpoint

* `MyronMetalPublish.cpp` now includes `IOPlatformExpert.h`. The pinned XNU
  `ac9718fb1af618d5ce8678d0dc6e8a58f252216f` declares `getPlatform()` as returning
  `IOPlatformExpert *`, with only a forward declaration in `IOService.h`.
  Converting that pointer to `IOService *` requires the complete class. The
  old host peer incorrectly returned `IOService *` and missed this native
  compile blocker. The corrected peer reproduces a compile error without
  the include and passes with it.
* The mailbox worker calls the same connection dispatcher as direct/tunnel
  commands. It previously called `runCore` directly: BO import always returned
  Unsupported and CPU lease release bypassed the cached-view teardown. A task
  reference held for the connection lifetime supplies the mailbox owner's
  address space; direct calls still use their actual calling task. A retained
  connection and the existing request/owner checks protect late replies.
* CPU unmap validates the real handle, token, reserved fields and lease first.
  Failed requests no longer remove a still-live mapping. Only a successful
  last lease drains cached views; earlier leases keep them. While IOKit removes
  mappings outside the shared GPU lock, other core operations and view lookup
  sleep on a per-connection gate. They resume after removal, rather than freeing
  the BO/reusing its token while an old CPU mapping is still present. Close uses
  the same gate, so waiting requests observe a closed client after teardown.
* The old view-draining loop discarded `removeMappingForDescriptor()`'s
  retained map pointer. Pinned XNU returns a +1 reference; discarding it leaked
  the mapping instead of revoking it. The driver now explicitly unmaps and
  releases every returned map, including one held by another reference. Failed
  unmap latches a connection error; dispatch, new views, import and close refuse
  to free/recycle the still-quarantined backing objects.
* Failed provider/attach/start refuses the connection before mounting a GPU
  core. Type/capacity/mount failures after successful attachment stop and detach
  before release. Task references are released in the client's final free path.

All changes to the pinned backend are staged by exact-match replacements in
`native/publish_lifecycle.py`; its dependency SHA and original blob checks remain
unchanged. The 128-IB wire ABI and the verified existing Metal component do not
change. No Apple binary, phone log, firmware or owner data is added to the repo.

## Qualification completed

* Production dispatch and close code, plus the actual backend `cpuUnmap`
  validation, run over host peers with UBSan. Invalid handles/tokens/reserved
  fields/sizes, duplicate releases, multiple leases, final-view/free races,
  close/import races, direct/mailbox task selection and failed-close retry pass.
* Production connection creation runs with injected init/provider/attach/start,
  type/capacity/mount failures; attachment and task references balance.
* Production view removal checks token isolation, all-map draining, retained
  reference balance, revocation with an independent map holder and error
  retention. The dispatch tests also verify failed-unmap quarantine.
* Existing kernel poller and Metal mailbox tests still pass: full 128-IB
  submission, bounds, error replies, timeout quarantine and owner replacement.
* `check_native_host.py` now includes all three lifecycle suites. UBWC6 programming
  and 128 single-bit fault cases, CP initialization, ring programming/wrap/error
  cases, IRQ decoding, timer handling, policy and 20480-extent pool recovery pass.
* Portable board/GMU/HFI suites, kernel/userspace wire ABI, producer-fence display
  gate, diagnostic collector and source reconstruction pass.
* The retained kernel from run 45117385166 defines the new task-reference
  and wait/wakeup dependencies, including the private task-reference group
  variants. This checks symbol availability only, not a new native link.

This Linux workspace has GCC but no `clang++`, Apple SDK or iPhone compiler.
A requested secondary Clang check could not start. Full native compile/link,
final image qualification and CP/fence/known-image rendering on the phone remain
required. Host peers do not establish MMIO behavior, IOKit mapping behavior or
hardware rendering. Preserve the no-full-build constraint until source review
and targeted native qualification are ready; do not relabel an old boot image.
