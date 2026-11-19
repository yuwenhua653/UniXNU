# Preserve the missing first-frame wait evidence

The phone log supplied after run 44490462557 records a complete reserved-log
round, 338 writes, 675 log-worker seconds and no write error. Its raw log SHA256
is `5a1eb0c20591a276a26aa07790a1f32a52c276180ae61fb9241692bc935b736c`.

Measured facts:

- AppleKeyStore registered, 183 opens, 4544 calls, 96 unsupported results.
  State selectors 7/17/35 and software wrap/unwrap 10/11 have successful calls.
  Unsupported selectors remain unsupported; do not invent outputs to suppress errors.
- GOP registered with five clients, but zero accepted/rejected submissions,
  copies, kicks or retirements. This is still before a first observed submission.
- No retained first SpringBoard/backboardd exit or reboot request is present.
  The captured rolling console is late boot; it cannot establish what happened
  to liveactivitiesd early in this run. The earlier repeated SIGTRAP is not
  present in this retained window, which is not proof of its complete absence.
- APFS reports non-content-protected class requests and failed purge attempts.
  These do not establish that capacity or an unsupported key selector caused
  the missing first frame. Do not reformat retained Data on this evidence.

## Upstream method

[Official log capture](https://github.com/UniXNU/UniXNU/blob/main/docs/porting/log-capture.md)
requires a separate process-capture worker for the native iOS 27 stall path.
The read-only implementation is pinned to
[UniXNU-sheng c8f92b2](https://github.com/UniXNU/UniXNU-sheng/tree/c8f92b208068eeaa4cd2b0f592671f04ee70076e).
This is diagnostic source evidence, not another device's desktop proof.

The previous Myron image had exit records and a rolling console but no live
process sampler. It could record a crash; it could not identify a process
that stayed alive waiting on synchronous IPC, a VM fault or a lock.

## Change and boundaries

Build BootProcessWorker/BootProcessProbe and the host-tested portion of
BootUiTraceProbe with the actual Mach-private XNU C recipe. Keep the upstream
bounded task/thread traversal, arm64e return-address PAC stripping, reference
handling, and complete-snapshot publication. Do not include Sheng PMU/MMIO,
interrupt profiling, reset policy or optional VM-object diagnostics.

Start the sampler separately from the UFS writer. The writer copies only
completed rows; even a blocked user-page read cannot stop persistence. Remove
proc_name from the formatter as it would traverse processes in the writer.
Peer PIDs remain available. Preserve up to 40 rows each for backboardd,
SpringBoard, chronod and liveactivitiesd, before ordinary rolling logs, within
24 KiB of the existing 64 KiB slot. The storage geometry is unchanged.
Capture attempt/pass/busy/phase counters distinguish stale snapshots from
process absence. Stack sampling is asynchronous, not a stopped-task snapshot.

Require sampler definitions in native artifact verification and include the
upstream licenses in every assembled test package. The old image has none of
these sampler definitions; changing its boot arguments alone cannot enable it.

## Validation

Preflight exercises the actual upstream capture bodies with kernel/VM doubles:
task/thread contention, interrupt restoration, bounded traversal, malformed
frame chains, failed copies, IPC and VM reference balance, and a deliberately
blocked reader while previously published snapshots remain readable. The
Myron formatter is checked at every capacity from zero through 24577 bytes.
The actual persistent writer is exercised with its storage guards intact.

This change repairs the missing diagnostic path. It does not yet fix or claim
to identify the remaining desktop startup dependency. On the next device
capture, use the exact cache slide, executable base and wait-peer/stack rows
to identify that dependency before changing service behavior.
