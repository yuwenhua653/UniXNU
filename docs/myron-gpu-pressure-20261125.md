# myron GPU resource pressure

The device run after the write-combined scanout change completed 2,737 GPU
submissions, with 2,737 retired and no poisoned ring. The 256 MiB early BO pool
reached its limit; client slot zero recorded 2,537 allocation refusals. This is
allocation pressure, not proof of a hung GPU. CPU presentation used the half
conversion path: 880 copies averaged 16.70 ms, with a 26.86 ms maximum. These
are copy-only times, not application FPS or total frame latency.

Keep the early pool and enable at most 128 MiB of additional wired BO backing,
allocated only on demand through the backend's existing descriptor path.
The overflow charge is released only after the descriptor is actually released.
Prepare failures roll it back; device holds, cache restoration failures and
quarantined memory retain it. The 256 MiB per-object limit, cache maintenance,
SMMU checks, completion fences and OPP ceiling remain enforced. Imported pages
and internal page tables are not included in this BO limit.

This removes the unconditional refusal after pool exhaustion; it does not prove
that 384 MiB is sufficient for every workload. The snapshot now includes current
and peak overflow bytes, the cap, grants/refusals, connection process names and
the backend's existing short Metal failure messages. Black wallpaper is not yet
qualified as fixed. No full shader tracing is enabled.

Host validation executes the actual allocator/release code with IOKit peers,
including budget exhaustion, reuse, allocation/prepare/metadata/cache failures,
DMA holds and quarantine. The ARM cache barrier is replaced only in that host
test; native compilation and hardware validation remain separate.

Data is still a 1 GiB APFS container. This change does not resize it or reset its
seed. A separate copy-and-grow migration is required; changing the seed size
alone would select a different persistent overlay and lose access to current
data. Public build inputs contain source and synthetic tests, not user Data.
