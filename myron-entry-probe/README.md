# Retained iOS27 kernel entry observer

The phone reached the UniXNU menu and handoff phase 2704 with firmware run
43361559288. This experiment instruments the exact retained prelinked kernel
SHA256 `8c1dca686c9a99126402e59b1e5e553beb88abe4dbcf2d2a40b335bfc4e97718`.
It does not use R90 addresses, rebuild XNU, reinstall unixnu, or claim a fix.

`probe.py` checks the whole image hash, LC_UNIXTHREAD PC, all displaced
instructions, zero-filled executable cave and low-vector self-loops. It patches
only a copy, preserving the fileset layout and all root identities. The observer
uses no stack or firmware services. At each continuing marker it preserves
X0–X17, X19–X30 and NZCV; X18 is scratch at the reviewed sites and overwritten
before its next use in native startup. Original displaced instructions execute
once. The C-entry observer deliberately stops before PACIBSP/the C prologue.

| Display | Evidence |
| --- | --- |
| 2710 | Actual XNU entry executed |
| 2711 | Low vectors installed, about to read boot arguments |
| 2712 | Bootstrap page-table construction returned |
| 2713 | About to install the kernel PAC keys |
| 2714 | About to enable MMU |
| 2716 | Reached C entry after MMU enable; deliberate terminal stop |
| 27EE | Exception caught by the low vectors; deliberate terminal stop |

Low-fault ESR/ELR/FAR and previous phase are retained in the observer's context;
only 27EE is currently drawn. Normal vectors installed immediately before MMU
remain untouched. A trap through those vectors or EL2 can therefore still leave
the last earlier marker on screen. 2716 does not mean C initialization completed.

The workflow first executes the emitted markers with Unicorn to check registers,
flags and pixels. It then runs the actual patched XNU prefix in QEMU TCG, requiring
2716 and checking a negative UDF control at 2711. No PAC or system instructions
are replaced by test hooks. The QEMU boot arguments are synthetic; QEMU virt is
not the phone. Only after these pass does it rebuild Linux/Clang 18 firmware,
exercise the actual staged loader C path with the new FAT/root sidecars and
verify every final firmware module. The original 2700–2704 handoff is unchanged.

The output candidate must be packaged with its new manifest/image hashes and
existing Android-backup/root-install checks before delivery. It is not an
unrestricted flash image or a desktop build.
