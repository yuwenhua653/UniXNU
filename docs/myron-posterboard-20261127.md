# Black wallpaper: original iOS27 PosterBoard initialization evidence

The original-library index completed at 9d0130bc in run 45931203811. Its
artifact SHA256 is 7a2eccbc5add42b01c9109b5e263b19f3e41d6797190d5d04a4e4758f7a5ef34.
The bounded analyzer now includes the datastore factory, full 3968-byte
initializer, SQLite wrapper and implementation, plus their error paths.
No original executable or user Data is included in this source note.

In the original PosterBoard framework:

- XPC glue `_lock_dataStoreWithError:` is at image offset 0x118ac0.
  It calls the datastore builder and only constructs the generic unknown-reason
  error when both the returned store and NSError are nil.
- `buildDataStoreForURL:...` at 0x119118 directly allocates the datastore and
  calls its initializer. It does not contain a GPU-capability rejection branch.
- Datastore `initWithURL:...` at 0x15118 first performs migration and integrity
  validation, then initializes its SQLite database at +0xafc. A null database
  enters the "failed to setup database" path. Gallery/extension setup comes
  later and is not evidence of successful database creation.
- The SQLite implementation invokes `initWithFileURL:options:dataProtectionClass:error:`.
  This makes both file creation/storage and file-protection compatibility
  relevant checks. Static analysis does not establish which failed on phone.

The retained older read-only Data export had version-61 PosterBoard directories
but no completed database. Runtime logs reported the generic creation error
and a nil-store assertion. These observations explain why replacing a wallpaper
PNG or removing that assertion would not establish a working wallpaper service.
They do not prove that expanding Data fixes PosterBoard.

No assertion bypass, fabricated database or destructive cache reset was added.
The next runtime comparison must inspect the new Data free capacity and the
first datastore/SQLite failure on that same boot, then distinguish migration,
protected-file creation and SQLite open errors. Black wallpaper remains unverified.
