# Preserving myron Data while growing APFS

Status: offline migration-image preparation is implemented and tested. It is
not an installer and does not make a flashable image. The phone's filesystem
has not been expanded. No user data is a public build input.

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

The remaining device integration must be completed before offering installation:

1. Capture and verify a fresh source while iOS is stopped. Keep a host backup.
2. Copy and read back the disjoint extent; revalidate source identity and GPT.
   Commit readiness last. Never overwrite the original extent or GPT.
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
