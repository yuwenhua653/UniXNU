# Myron iPhone 24A446 CPU GOP display candidate

The tested 44233840545 image reaches userspace but SpringBoard repeatedly exits.
The retained first-exit trace resolves to
`-[FBSDisplayMonitor _initWithDisplays:mainDisplay:bookendObserver:transformer:].cold.6`
at unslid `0x1a8a6c63c`. The failing assertion is `[displays count] > 0`.
The caller tests the display array count before reaching this trap. The later
halt/restart timeout and persona warnings do not explain that first failure.

This candidate adds a real firmware-backed `IOMobileFramebufferLegacy` subclass:

- Uses the maintained UniXNU/GopFramebuffer CPU backend at
  `b0d812d578efa2acb005b66f73168891719af09a`. Source/license are included; the
  board transport binding changes are documented below.
- Derives the ABI header from UniXNU-sheng's 27 adapter at
  `6c42e1055ffb3b335fda991190ad221edaa7af3c`, with independently relocated iPhone
  addresses. The iPhone donor SHA-256 is
  `813be26ab6bd1d8de211904eca413a1a2ebf79989f90c33a48ff0f2fcff99036`.
- Checks all 379 original vtable entries, compiled PAC metadata, native inherited
  identities, original constructors/metaclass, IOSurface accessors, final
  adapters, fixed GOT imports and final prelinked dispatch slots. The three
  abstract entries retain their reviewed caller diversities separately from
  the original pure-virtual target's raw signing.
- Reads geometry and memory extent from the actual GOP handoff; registers the
  provider under the real `arm-io` device-tree parent; waits for IOSurface and
  allocates its default surface using the original factory. The void slot 316
  is never treated as an object-returning API.
- Performs CPU copies and uses the existing console-release handshake before
  presenting a frame. GPU, DPU direct scanout and unmeasured refresh overrides
  are refused. No SM8550 register values or panel calibration are transplanted.
- Keeps SystemOS library mounting and the bounded persistent log path. Each
  committed log round now includes display registration, client status,
  accepted/rejected swaps, copied bytes and retirement counts.

The driver is compiled with the root candidate. It is only activated by the
explicit startup arguments. Other retained/dormant storage variants do not
register it. Full native compilation runs in the existing macOS CI; original
donor images and device logs are not added to this repository.

Validation: actual pinned donor checks and negative controls cover wrong donor,
slide, slot target, PAC key, code anchor, metaclass and generated method names.
CI also runs the upstream request-state/cancellation test and compiles all
display units against the real kernel recipe before reference/prelink work.
Final package assembly rejects kernels missing the backend or its activation
arguments. Compilation and these checks do not establish successful phone boot,
desktop rendering, touch, brightness control or GPU acceleration.

Build follow-up (run 44258848872): all three display C++ units compiled, but
root import preflight passed their MH_OBJECT files to the linked-image reader,
which requires a mapped header segment and raised StopIteration. Read external
N_ABS definitions directly from the bounded Mach-O symbol table instead; keep
absolute addresses separate from section symbols and exclude local/debug names
from import resolution. Regression cases cover sectionless objects, malformed
entries, unresolved imports, and the production address assembly compiled with
the real arm64e assembler in macOS CI. Full link and prelink checks remain required.

Transport follow-up (run 44265482666): object parsing now passes, including the
real arm64e address-object test. Import preflight then correctly rejected five
`l_native_*.ptrauth` symbols created by optional weak GPU/DPU declarations. The
board already supplies unsupported implementations, so share strong declarations
between caller and provider instead of optional weak imports. Never whitelist
the unresolved authentication thunks. A separate provider-presence query keeps
an absent GPU distinct from a failed or pending GPU fence query. The existing
CPU copy/retirement path remains unchanged; direct DPU scanout stays disabled.

Compile the actual board declarations and provider definitions for arm64e in the
early macOS job, check their imports together, and execute the extracted production
fence method for absent/unknown/pending/completed GPU states and a new request.
All three production display objects also reject authenticated weak imports
immediately after compilation. This is build/fence-policy validation, not phone
display qualification.

SDK follow-up (run 44273521900): the extracted production fence test passed,
but the new arm64e binding test inherited the macOS host SDK and stopped on
`-Werror,-Wincompatible-sysroot` before compiling the consumer. Select the
installed iPhoneOS SDK through xcrun and pass its explicit sysroot to both
target tests and production display adapter assembly. Keep warnings as errors;
missing device SDKs fail rather than falling back to the host SDK. Host-native
request/fence execution continues using the host compiler configuration.

Runtime-fixture follow-up (run 44275591028): device SDK selection and the real
fence method now pass. The standalone interface test compiled successfully but
mistook compiler-inserted stack-protector imports for missing board interfaces.
Compile test-only guard/failure support and test both explicitly disabled and
fully enabled stack protection. Verify that removing runtime support exposes
the two stack imports and removing the board provider still fails. No runtime
allowlist, kernel protection flag, or production import check is changed.


## Run 44297756043: missing prelink exception evidence

The full root compilation, display ABI checks and native link passed. The root fileset prelink exited before writing kernel.json. Its detailed log was incorrectly omitted from diagnostics, so the exception is not yet identified. This change repairs evidence collection; it does not claim to fix the underlying prelink failure.

All desktop stage logs and prelink reports are now preserved. A failing subprocess prints its actual log tail before propagating its exit status. Only the source-built root native kernel and RELEASE LTO reference are retained for offline replay, with SHA256 and size; donor kernels, root images and private inputs remain excluded. Collector inclusion/exclusion and a real subprocess failure before JSON creation are tested before the expensive build.
