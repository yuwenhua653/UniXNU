# Preserving myron Data while growing APFS

Status: offline migration-image preparation and the pre-mount device-copy core
are implemented and host-tested. Neither is wired to an installer or a boot
trigger yet. The phone's filesystem has not been expanded. No user data is a
public build input.

The retained seed is 1 GiB. Its SHA256 is also the identity of the persistent
overlay. Replacing it with a larger empty seed, or restoring an earlier export,
would not preserve the current installation. The existing generic Mac seed
growth script cannot be used as a device migration tool.

`myron-runtime/data_growth.py` accepts a validated read-only export and the
existing deployment geometry. It prepares a sparse 4 GiB overlay in a separate
extent immediately below the original 1 GiB extent. Both extents fit above the
signed root plus its 4 MiB guard and below the carrier/log reserve. It retains
the original seed identity, copies every present page, extends the bitmap with
zero bits and verifies all copied pages by SHA256 readback. The marker remains
pending. The original export and device are never modified. This is byte
preservation, not an APFS filesystem check or a resize operation.

Five synthetic tests cover the boundary calculation, sparse clone, pending
marker, corruption, foreign source identity and an undersized partition. An
existing private export was also prepared locally and all present-page hashes
matched; it is an older snapshot, not an acceptable source for phone restore.

`MyronDataMigration.h` now provides the separate on-device migration core. It
requires exclusive pre-mount ownership, reads the current source directly,
retains its original seed identity, writes only the disjoint destination and
verifies each copied run. It writes and verifies a pending marker first,
extends the bitmap, checks metadata readback and rechecks the source metadata
before committing ready. A ready destination is never overwritten by a retry.
The selector refuses corrupt committed metadata; it cannot silently return to
the stale original copy. The existing old-size path remains usable while a
copy is pending. Holding the source quiescent is mandatory: metadata comparisons
alone cannot detect an active writer changing an already-present data page.

Host tests inject failure at all 27 storage operations in a sparse fixture,
retry each interrupted copy, check readback corruption and changed source
metadata, and check selection of old/pending/ready/corrupt copies. All writes
are asserted to stay in the new extent. ASan/UBSan checks pass. These exercise
the actual migration core with substituted storage, not UFS power-loss or APFS
behavior. Scratch buffers require caller allocation, not the kernel stack.

The remaining device integration must be completed before offering installation:

1. Capture and verify a fresh source while iOS is stopped. Keep a host backup.
2. Wire the tested copy core to the UFS transport while Data is unpublished;
   revalidate GPT and guarantee exclusive ownership throughout. Commit
   readiness last. Never overwrite the original extent or GPT. If the final
   marker write/sync fails, treat its commit state as uncertain and re-read it
   before any selection; do not assume a failed call permits old-data fallback.
3. Teach the block provider to select that exact committed extent, present the
   larger capacity and treat pages beyond the original seed as zero. Preserve
   the seed identity and refuse corrupt committed metadata instead of silently
   returning to a stale copy. The current provider is still limited to 2 GiB.
4. Run a trusted, narrowly scoped helper on the phone. Resolve the physical
   store through the actual Data volume and confirm it belongs to NativeRamBlock
   before calling Apple's APFS resize function. No disk0/GPT resizing is needed.
5. Verify the resulting APFS container size, volume UUID and free space, and
   retain failure details. A larger virtual disk alone is not expanded Data.
   Once the new volume has accepted writes, returning to the old copy is a
   deliberate rollback with possible lost recent changes, not automatic recovery.

API research: OrchardLinux/resize-apfs, `Sources/NativeSystem/NativeSystem.c`,
resolves `APFSContainerResize(const char *, uint64_t)` from the phone's APFS
framework. Its device/GPT modification code does not apply to our virtual disk.
That private API's existence in other iOS versions does not qualify its behavior
on this iOS 27 port. Helper launch, signing/trust and runtime validation are
still required.

Reference: https://github.com/OrchardLinux/resize-apfs
