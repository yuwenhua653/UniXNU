# myron 24A446 desktop seed

The fresh donor Data previously launched Setup on every boot. Phone tests
reported prolonged waits after display size, Quick Start and keyboard pages;
one recorded Setup main thread waited for the mandatory-update completion.
The underlying service delay is not diagnosed by this change.

The newly created Data now follows UniXNU's documented Skip Setup path:

- https://unixnu.com/guide/skip-setup
- UniXNU/UniXNU at `8542980d02b4d2cc5c32ee3542de1760b2562aac`,
  `scripts/make-data-seed.py` and `scripts/seed-data-skip-setup.py`.
- UniXNU/UniXNU-sheng at `c8f92b208068eeaa4cd2b0f592671f04ee70076e`,
  `board.toml` selects `payload.runtime.skip_setup = true`.

`myron-skip-setup.patch` merges Setup completion, mini-buddy, initial cloud UI,
and migration preferences into the mobile account of a new local APFS volume.
The migration build is exactly `24A446`, version `27.0.1`; upstream's older
`21H461` default is not used. The seed also selects upstream's no-auto-dim
preferences while native power-button/sleep handling remains unqualified.
Unlike upstream's general helper, this port does not add `BKNoWatchdogs` or
`FBLaunchWatchdogExceptions`. Native watchdog behavior stays unchanged.

Original donor volumes remain read-only. Device identity, real display gates,
FT3683 input, original executable trust membership and the retained unixnu
root image checks are unchanged. The 1 GiB logical sparse Data seed remains
volatile; this is not a persistent-data implementation or a promise of a
stable desktop. It is not evidence that Setup's service waits were repaired.

Checks run the production preference writer and reject wrong typed values,
wrong build versions, unexpected symlinks and ownership/mode changes. The
existing macOS APFS preflight reopens its detached raw image and checks the
same preference content. Original-userland preparation also reopens the real
new Data, verifies all five domains and emits `setup-seed-check.json` with
their hashes, packed/logical seed hashes, capacity, free bytes and source hash.
The native artifact collector retains that receipt.

The kernel embeds the expected Data hash and volume UUID, so replacing only
scratch-data.img in an old boot image would fail the real Data checks. This
change goes through the existing native build and verified firmware packaging.
The final package must match the receipt's seed hash and the same run's kernel
hash. Only a subsequent phone test can establish whether SpringBoard opens
and remains responsive.
