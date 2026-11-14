# APFS STRATEGY dispatch repair

The phone photo `1000149317.jpg` after run 43544518065 shows a buffer obtained
from APFS, completed by IOStorageFamily, then released by native `buf_bwrite`.
The later release fails with queue 3 and BL_BUSY clear. Root mounting and
desktop startup have not been demonstrated.

## Exact artifact evidence

- Candidate kernel SHA256: `76c9bba9ef6fb3b574770f84d2f5e1923433551ec32e2b04728b95c9f9980ed1`.
- Donor: pinned iPhone12,1 24A446, SHA256
  `813be26ab6bd1d8de211904eca413a1a2ebf79989f90c33a48ff0f2fcff99036`.
- Event 1 caller `0xfffffff009f6f640`: APFS returns from `buf_getblk`.
- Event 2 caller `0xfffffff009b918b0`: IOStorageFamily completion calls `buf_biodone`.
- Event 3 caller `0xfffffff00a3f7fec`: native `buf_bwrite` releases the buffer.
- APFS read submission at `0xfffffff009f6f730` calls stub
  `0xfffffff00a09d2e4`, whose pointer slot is `0xfffffff0080e7b20`.
- In the donor this slot points to `0xfffffff00a3b6830`, the 72-byte wrapper
  referencing descriptor `0xfffffff00ac95568`, whose name is `vnop_strategy`.
- In the tested artifact it instead points to `_VNOP_BWRITE`
  (`0xfffffff00a4485a0`), rather than `_VNOP_STRATEGY`
  (`0xfffffff00a44853c`). This is a function-identity error, despite all
  189 descriptor references already passing their independent name checks.

Apple's [pinned kpi_vfs.c](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/bsd/vfs/kpi_vfs.c)
defines STRATEGY and BWRITE as distinct operations. Their donor wrappers have
identical masked instruction shapes; their descriptor references identify them.
The wrong BWRITE path clears B_READ and synchronously releases the buffer.
This accounts for the unexpected first release observed on the phone.

The failed-release PC is not reliable caller evidence in this build:
`buf_brelse.cold.8` captures its own return address, `0xfffffff00a3f68d8`.
The observer is now invoked on both paths before the panic-only block, preserving
the original ownership assertion and all buffer lifecycle operations.

## Changes and checks

- Pin both donor wrapper identities to native `_VNOP_STRATEGY` / `_VNOP_BWRITE`
  using exact donor body hashes and descriptor evidence.
- Extend the production final-fileset gate to check the APFS STRATEGY import,
  alongside all 189 descriptor sites. Existing prelink paths invoke this gate.
- Actual matcher reviewed anchors resolve both wrappers to distinct native symbols.
- Run 43544518065 artifact rejected for one function binding; previous artifact
  rejected for six bindings (five descriptors plus the function).
- Temporary corrected checker specimens pass; restoring one wrong pointer fails.
  These specimens are test data only, never packaged for flashing.
- Full selected buffer patch stack applies; removing diagnostic additions exactly
  restores original lifecycle code. Enabled/disabled observer macro tests pass.
- Source reconstruction, embedded SHA256 checks and whitespace checks pass.

No rebuilt kernel or new phone result existed when this source change was made.
The error is demonstrated; clearing this panic and reaching the desktop still
require the corrected build and subsequent device evidence. The current phone
root partition need not be reinstalled on the basis of this screenshot alone.
