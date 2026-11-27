# Publish Data only after its persistent overlay is ready

The previous NativeRamBlock integration published IOMedia from `start`, then
attached its persistent overlay when the Data UUID resolver ran. APFS can read
container metadata during media enumeration, before that resolver. Those reads
used the immutable seed, even when a newer container checkpoint or resized
container was present in the overlay.

`start` now opens and validates the selected persistent overlay before setting
the provider online and calling `registerService`. A failed open, allocation,
header/seed validation, initialization commit or GPT check refuses publication.
The later UUID resolver retains its idempotent attach call. The original seed
hash, 16 GiB selection, migration markers and no-reset policy are unchanged.

The host test compiles the actual generated start, attach and read methods. Its
registration callback immediately reads page zero, where the persisted fixture
differs from the seed. Both 1 GiB and 16 GiB paths return the persisted bytes.
Ten failure cases never publish. A negative control removes the early attach
and fails specifically on the first-read byte assertion.

The persistent log also records the existing passive UFS diagnostic formatter
and a Data publication stage. The first 19 intervals are 500 ms; subsequent
intervals remain 2 seconds. No additional MMIO sampling or panic-time UFS writes
are introduced.

Validation: runtime checks with ASan/UBSan, migration fault injection, Data
export/clone checks, log-worker checks, and plain/production boot-asset fixtures.
These establish the ordering defect and its correction on the host. They do
not establish that it was the sole cause of a device reboot; hardware boot and
APFS resize still require device validation.
