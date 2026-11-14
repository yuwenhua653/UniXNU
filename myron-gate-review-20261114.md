# Gate interface repair after root mount

The phone photo `1000149322.jpg` from run 43567678297 shows
`vfs_mountroot mounted; authentication pending`, then the VFS_ROOT and root
authentication-decision markers, followed by `bsd_init: calling devfs_kernel_mount`.
The previous buffer-ownership panic is absent in this observation. These markers
do not establish launchd execution or a working desktop.

The new panic is `Gate used is invalid`. PC `0xfffffff00aa4387c` is the return
address of the panic call at `0xfffffff00aa43878` in `_gate_verify_tag_panic`.
It is not proof that `_gate_verify_destroy_panic` (which starts at the same
return address) ran. The display preserves the format string, not its variadic
values; gate pointers, refs and flags cannot be read from `%p/%lx/%d/%x`.

## Verified ABI error

Candidate SHA256:
`547c79f1c48f02aa60968c4fa7cf07cab728e507bae20538724700f2e8ba2a2d`.
Pinned 24A446 donor SHA256:
`813be26ab6bd1d8de211904eca413a1a2ebf79989f90c33a48ff0f2fcff99036`.
The donor was re-extracted from the profile's Apple IPSW URL after workspace
maintenance removed the earlier copy. Both compressed and decompressed pins match.

- APFS slot `0xfffffff0080e8318`, used by stub `0xfffffff00a09e2d4`, originally
  refers to donor function `0xfffffff00a1cd4f0` (296 bytes).
- The donor checks the gate tag at `[x1+0x10]` and acquires the gate through
  `[x1]`. APFS call sites `0xfffffff00a0110d8`, `0xfffffff00a011354` and
  `0xfffffff00a0118e8` pass the lock and gate as distinct arguments.
- The candidate instead binds this import to `_gate_close` at
  `0xfffffff00a1b0628`, which interprets **x0** as the gate. The lock is therefore
  incorrectly subjected to the gate tag check.
- Correct destination: `_lck_rw_gate_close` at `0xfffffff00a1b05cc` in this
  candidate, which validates the RW lock and forwards **x1** to `_gate_close`.
  Future builds resolve by symbol, not by this build's address.

The exact [Apple locks.c source](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/kern/locks.c)
defines the two-argument public wrapper and one-argument internal function.
The correction preserves gate type/ownership checks and all synchronization behavior.

## Scope and validation

All 11 retained chained imports into the donor's gate-interface region were
inventoried: five from APFS, six from AppleImage4. Ten already resolve to their
expected public interfaces; the RW close import is the demonstrated mismatch.
All 11 now have explicit donor-body identities and a final-fileset import gate,
alongside the existing 189 descriptor and STRATEGY-function checks. No raw
one-argument gate function is accepted in place of a two-argument wrapper.

- Current phone artifact is rejected for exactly one gate import.
- Earlier run 43544518065 artifact is rejected for the STRATEGY and gate imports.
- Actual matcher reviewed anchors resolve 13 named dispatch/gate interfaces.
- Temporary corrected checker specimens pass; restoring one bad pointer fails.
  These specimens are never packaged for the phone.
- Source reconstruction, per-file hashes, Python syntax and whitespace checks pass.

This establishes a concrete binding defect consistent with the observed panic.
The screenshot does not supply a complete stack trace. A corrected CI artifact
and subsequent phone test are still required to establish further boot progress.
