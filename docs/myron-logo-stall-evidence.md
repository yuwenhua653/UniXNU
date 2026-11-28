# First-frame stall after the early-task launch fix

The 2026-11-28 device observation for package run 46121247454 differs from
the preceding launch-constraint reboot: SpringBoard and backboardd are alive,
no first reboot is recorded, and the GPU has retired all 545 submitted tasks.
This establishes progress past the previous failure, not a working desktop.

The display accepted three swaps but copied and retired none. Its transfer
status is NotReady; there are seven distinct return sites with this status.
The existing record cannot distinguish them. New `display_not_ready` counters
use the following stable, source-generation-checked order:

1. Blank-swap GOP geometry or current-console mismatch.
2. Blank-swap console handoff refused.
3. Surface bounds/format or GOP geometry/current-console mismatch.
4. Surface console handoff refused before producer wait.
5. Scaled surface map/allocation/conversion table or handoff refused.
6. Half-float surface console handoff refused.
7. Normal CPU copy console handoff refused.

`handoff`: 0 not attempted; 1 interrupt context; 2 interrupts disabled;
3 32 bounded attempts exhausted; 4 acknowledged. The boot recorder separately
reports enabled/state, prepare/cancel counts and release status. These records
do not bypass any check, retire failed frames, or fabricate GPU completion.

The Data block provider advertises 16 GiB. The app staging check found about
75 MiB free and required 760 MiB, but it ran before the early resize helper.
It is not a post-resize capacity measurement. No helper report was recovered.
The general console had wrapped beyond 1 MiB, losing the helper's early
messages. Neither successful resize nor the helper's precise failure is proven.

The recorder now keeps the first twelve and last four complete tagged helper
lines separately from the rolling console tail, even after display handoff.
It marks truncation and capture gaps, discards partial lines after contention,
and never interprets console text as authorization or success. All storage is
bounded and shares the existing nonblocking capture lock. Host regression
tests cover wrap, tail ordering, contention, truncation and every snapshot
buffer capacity below 4096 bytes under ASan/UBSan.

The wrapper's unchanged refusal checks now identify argument, parent, UID,
executable-path and boot-argument failures separately. The APFS helper also
emits a bounded reason and observation/capacity summary before saving JSON.
No resize validation, attempt journal, retry rule, GPT, seed or Data contents
is changed. These helper source changes require a new component build and
reviewed artifact/hash pins before a full device package can be produced.

This change repairs missing diagnostic evidence. It does not claim to fix the
remaining display stall or prove Data expansion on the phone.
