# iOS 27 Objective-C pointer authentication compatibility

The device test of run 43674287810 reached launchd, then stopped at an EL0
read translation fault. The photograph records PC `0x183257140`, raw FAR
`0x741e9d71f70`, ESR `0x92000004`, and shared-cache slide `0x02e3c000`.
Analysis run [43682754429](https://github.com/yuwenhua653/UniXNU/actions/runs/43682754429)
checked the original iPhone12,1 / 27.0.1 / 24A446 SystemOS identity and decoded
the matching cache without modifying it.

The unslid instruction is `libobjc.A.dylib` at `0x18041b140`, `ldr x8, [x19]`.
The preceding recursive call extracts an isa pointer with
`and x0, x8, #0x7fffffffff8`. The parent class's authenticated v5 relocation
targets `0x1e9d71f70`, but the recursive call receives `0x741e9d71f70`.
The extra bits are 38, 40, 41 and 42. They survive this 43-bit mask when
pointer signing uses the tested kernel's 38-bit user address geometry.
The redacted function's control flow matches public Objective-C class
realization code; this source-level name is an inference, not a recovered symbol.

## Change

The board patch gives user translation and PAC a 43-bit address range, while
preserving the kernel's 38-bit range. It does not disable pointer authentication
or modify the original shared cache.

| State | T0SZ | T1SZ | User root | Kernel root |
| --- | ---: | ---: | --- | --- |
| Early boot identity map | 26 | 26 | L1 | L1 |
| Runtime | 21 | 26 | L0 | L1 |

Separate page-table attributes select the L0 user geometry for newly created
task, shared-cache and commpage pmaps, and retain L1 attributes for the kernel.
Cold boot, secondary CPU startup and nonretention idle resume switch TCR only
after TTBR0 points to an empty table, with translation invalidation and barriers.
Unsupported page sizes, SPTM, kernel protection and mixed-page configurations
are rejected at compilation. Private pmap layout changes require all XNU
objects and generated headers to be rebuilt together.

## Verification boundaries

The preflight checks compile the selected patched headers and page-table
initializers. A separate QEMU test executes real PAC instructions with synthetic
keys and translation enabled. The native artifact verifier checks the resulting
kernel rather than relying solely on source text. These checks run before a
candidate is accepted; they do not prove that launchd or the desktop boots on
the phone. A new device test remains necessary after the exact final boot image
and its provenance have been verified.

Fresh-computer test packages must collect and verify a new boot backup on that
computer. CI's retained root identity is not evidence of a local boot backup.

## Local preflight results

Clang 19.1.7 and QEMU 10.0.13 passed the real-instruction test. With a public
synthetic key and modifier `0x6ae10001e9d71f98`, the old configuration produced
masked address `0x501e9d71f70` and actual read fault `ESR=0x92000004`.
The new configuration produced masked address `0x1e9d71f70` and successfully
loaded the mapped value. The different malformed high bits are expected with
synthetic keys; no device key was copied. Wrong-width and PAC-disabled control
builds were rejected. Authentication with a wrong modifier or altered signature
was also rejected in both geometries.

The source geometry test passed its host execution and arm64e layout compile,
including 12 rejected configurations. The native-verifier fixture passed its
positive case and 28 negative controls. The previous phone-tested kernel fails
the new geometry gate as expected. CI repeats the executable preflight before
starting the full native build.
