# Owned GPU memory capacity

The myron native backend provides a 256 MiB BO pool and at most 128 MiB of
reclaimable overflow. The Darwin Vulkan backend must advertise at most their
combined capacity, clamped further if the system estimate is smaller. This is
a shared capacity, not currently available bytes or a per-process reservation.
Imported host pages retain their existing independent lifetime and accounting.

The generic Darwin backend estimates its heap from system RAM. That estimate
can exceed myron's enforced owned-memory ceiling. The runtime uses the reported
heap to size pooled blocks and retained empty blocks; reporting system RAM can
therefore choose unnecessarily large allocations for this board.

The resolved myron userspace build applies an additional Mesa patch and copies
the native policy header. The wire ABI, native memory limits, arithmetic,
shader policy, Data contents, and generic non-myron build remain unchanged.
The resolved-source manifest covers both the patch and policy header.

`test_heap_contract.py` compiles the actual resolved heap assignment with the
policy header, exercises values below/at/above the limit and integer extremes,
and runs before the native Turnip component build. This verifies configuration
consistency, not device memory reclamation or a runtime performance improvement.
Remaining allocation failures and the display-service crash still require
device evidence; reducing the advertised capacity is not a complete OOM fix.
