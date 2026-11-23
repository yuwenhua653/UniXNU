# Native A840 integration stage

The native board driver compiled and linked into the iPhone27 package in run
45117385166 (commit 8fc39d1e8afe0c1e0d61bd08597b461331682d98). Its final
embedded kernel SHA-256 is
`1af397687b3f7eca2a7f546885eca72389e5bedbe52e3eeaeba6335813e6ac7d`.
The package enables native bring-up with `myron-gpu=1`; actual phone readback
has not been established by these host audits. This remains **not a
GPU-accelerated desktop package**. Metal publication and display integration
are pending; userspace is built separately by `myron-gpu-userspace.yml`.

## Implemented

`MyronGpuService.cpp` adapts Typeun/myron-device's native A840 implementation
at `d9b6be4d75f5a8169aee65b02bb23cd88968c1eb`, retaining its BSD license:

* CX/GMU clocks, SCM register access, command DB, GMU SMMU and firmware startup.
* Actual-length HFI performance/bandwidth tables and acknowledged GX votes.
* A8xx register programming/readback, checked active-slice chip identity.
* Separate SQE allocation, AQE, ring, CP init, real CP timestamp waits and
  CPU readback, signed ZAP authentication and fenced secure-mode exit.
* Two complete client rounds, including close/unmap/reopen, before admitting
  userspace. Any failed request or unclosed client keeps admission disabled.

Board differences are explicit:

* A maximum 256 MiB BO pool within this port's 2 GiB RAM. Pool allocations
  cannot silently spill into unbounded fallback allocations. This is a pool
  bound, not a global limit on imported userspace pages.
* At most stock index 7 / 422 MHz, common to both reviewed speed bins. There
  is no copied maximum-frequency governor or unqualified thermal integration.
* The GPU interrupt mask stays zero. Fence waiters sleep and read the actual
  CP timestamp until a reviewed GIC attachment is available.
* Explicit cache maintenance stays on. No unproven coherent-import shortcut.
* No panic-report loop, fabricated fence or replacement display retirement.
  The unimplemented GPU scanout tunnel returns `kIOReturnUnsupported`.
* The backend pool free list accommodates four 4096-object userspace clients
  plus the kernel test client. The old 512-slot limit could lose free extents.

`prepare_sources.py` validates dependency commits **and file blob hashes**,
copies only tracked source files, and applies narrowly matched backend changes.
The A8xx backend remains at `5bbeb3b8d049a637a595090319835a49e58a8b56`; it is not
silently mixed with upstream's newer per-process, eleven-buffer implementation.

## Actual build wiring

`myron27-build.py --source-only` reconstructs the board with `gpu/` and applies
`board.patch`. `MYRON_GPU_NATIVE=1` selects the real C/C++ compilation, archive
linkage and late boot hook. `MYRON_GPU_FIRMWARE` must point to local, exact
OS3.0.306 GMU/SQE/AQE/ZAP files; all four sizes and SHA-256 values are checked
before compilation. Firmware bytes are not committed here.

`gpu_build.py` uses the prepared XNU `IOPlatformExpert.cpo.json` and
`startup.o.json` recipes, checks arm64e objects, removes automatic class
initializers, and emits explicit late registration. The kernel's existing
undefined-symbol and unchanged-initializer checks still apply. At boot,
`myron-gpu=1` starts this stage after the existing storage/display/touch boundary.
The combined device build selects native compilation, and the qualified package
above enables the boot argument. User admission still requires both real client
readback rounds to pass on the phone.

The source now links the iPhone-specific `MyronAcceleratorCandidate.cpp` through
retained-family adapters and verifies them in the final collection (see the
integration section below). It does not install a Metal plugin or enable the
`myron-gpu-metal=1` activation argument yet. GPU scanout remains disabled; UI
scale is handled separately by myron-runtime. Host tests do not establish
hardware startup or a rendered desktop.

## Verification

```sh
python3 myron-gpu/native/prepare_sources.py --references /tmp/gpu-refs --fetch
python3 myron-gpu/native/check_native_host.py \
  --references /tmp/gpu-refs --output /tmp/native-host.json
```

The host suite compiles the real ring, CP-init, IRQ decoder and timer against
upstream software peers; it checks A8xx register selection, failed writes,
poisoned rings, and bounded timeouts. It also tests pool/OPP/admission policy
and fragments/reassembles all 20480 possible BO extents using the staged
allocator functions. The source-check CI job runs these host tests. The separate device-package workflow now fetches exact OTA firmware and compiles the native stage with the kernel.

Run 45029819275 (602714d7) compiled all 35 native GPU objects and linked the
native kernel, then failed fileset placement: `__DATA_CONST` plus
`__LASTDATA_CONST` still needed 0x166000 bytes after safe padding removal;
the retained-text/retained-constant gap was 0x1222c8 bytes (page-aligned
usable capacity 0x121000). Native kernel SHA-256:
`b382a9b298c5703e43812e5bf57d42364b7c130f762d93f1c3e4db3dbed9b4f9`.

The four immutable firmware inputs now use `__TEXT,__myron_gpu`, keeping
4 KiB blob alignment and the existing copy-to-GMU/GPU-memory paths. They
are not kernel authenticated pointers and need no space in the constrained
native constant prefix. The linked-kernel audit checks all four byte hashes,
size words, nonoverlap, alignment, section ownership and read-only mapping.
No retained-kext address, overlap check, PAC check or runtime gate is relaxed.
A layout projection using the failed kernel and pinned donor fits with a
0x1f0000 TEXT upper bound, 0x120000 DATA_CONST and 0x1000 LASTDATA_CONST;
this projection is not a new native build or successful full prelink.

The later run above passed fileset layout and compiled-kernel firmware checks.
The retained iPhone IOAcceleratorES base was also checked in its actual final
kernel: 136-byte instances and 168 authenticated virtual entries, with three
binary negative controls. Its candidate is compiled separately and is not yet
linked or published. Run 45134750180 (78dc7d57) now built the real arm64e iOS27
Turnip, Rust bridge and signed plugin. The downloaded artifact digest is
`982b039c9796fc0bd6fb9701780d127f21c39db507dd850b86422de9ff384740`;
`audit_userspace_artifact.py` independently verifies each 4 KiB code page,
CodeDirectory special slots, CDHashes, build target and decompressed addon.
The addon is 15,295,600 bytes; it has no publication marker or probe daemon.

The board now registers a lifetime-stable producer-fence query only after the
existing two hardware submission/readback rounds pass. The query uses the
submission lock nonblockingly and reads the real CP timestamp. Pending work,
busy locks and poisoned rings never become completion. The common validated
surface path waits before CPU scaling, normal copies and direct scanout;
no scanout MMIO, original family retirement gate or Data seed is changed.
Host tests exercise the actual query and display decisions with software peers.
Native compilation and phone qualification remain separate requirements.

Remaining work includes the phone's pre-CP startup failure, retained accelerator
binding/publication, target trust merge, signed addon capacity, and a known
rendered image on the phone. Follow the [official GPU porting sequence](https://github.com/UniXNU/UniXNU/blob/8542980d02b4d2cc5c32ee3542de1760b2562aac/docs/porting/gpu.md).

## UBWC6 startup correction (2026-11-23)

Do not start another full image build for an isolated diagnostic or host-test
change. The user requires the GPU integration gaps to be reviewed together
before the next full compile. The 45147290072 run stopped in a log-worker host
fixture, before its kernel job; that fixture now links the actual staged-app
formatter and exercises both GPU-enabled and GPU-disabled worker configurations.

The mode7 write to BR `RB_CMP_NC_MODE_CNTL` used `0x28046`. SM8850 KGSL
`gen8_start` initializes `amsbc` and `rgb565_predicator` to zero and leaves them
zero for UBWC6; it selects `mode2=5`, `yuvnotcomptofc=1`, MAL=32, yielding
`0x28040`. The old value incorrectly enables the two UBWC5 compression flags.
The same-SoC [successful test record](https://github.com/u0er/unixnu-xiaomi17u/blob/7c2ca6ba83dda2b9f30111bdc335281279c143a0/xnu/patches/0182-pandora-gpu-chipid-files-chunks.patch)
reports those two bits not reading back as written. Our pre-CP gate required
all 118 readbacks to match, so that documented behavior rejects the old write.

`MyronA840RenderConfig.h` supplies the corrected UBWC6 write and KGSL's twenty
bicubic weights; the earlier generated register/CP-protection table is kept
unchanged. Full-word readback equality remains mandatory, including both bits
1 and 2. No register masks, CP-ready flags, slice identities or fences are
faked. Exact source hashes and fields are in `hwinit-ubwc6-source.json`.
`test_hwinit.py` executes the production mode7 body over a register peer:
the old value passes only 117/118 checks and fails the CP gate; the new value
passes 118/118. All 128
single-bit corruptions across four critical registers and the IO, power and
SMMU negative cases still fail. This demonstrates the software/configuration
defect, not a successful boot on the user's phone; its old snapshot omitted
the actual mismatching register value.

Metal discovery, retained accelerator binding/publication, owner trust merge
and addon installation remain incomplete. The component artifact's successful
build cannot substitute for those steps or for real CP/fence/rendered-image
results. Keep the existing original Data seed and display/HID checks.

## Retained Metal frontend and sidecars (source checkpoint, 2026-11-23)

`MyronMetalPublish.cpp` now supplies the missing discovery service. The exact
136-byte iPhone `IOAcceleratorES` parent must load and match the retained
metaclass address before the AGX subclass initializer runs. A pre-existing AGX
class refuses publication. Init/property/attach/start failures release the
instance; registration is one-time. Publication additionally requires the real
CP/readback/fence-ready result and explicit `myron-gpu-metal=1`.

`accelerator_abi.py` checks the donor hash, retained family code, every inherited
method's native identity and all 168 authenticated slots. The build supplies
BTI branch adapters for the actual C2/D2 and an original metaclass GOT binding,
then uses the display driver's existing final-link and final-prelink verifier.
The original family is retained; no substitute base class is implemented.
`myron-runtime/accelerator.py` connects those checks to the normal build and
includes both new adapters in the storage audit's exact adapter set. The
collector keeps `accelerator-abi.json` for final-package review.

The service publishes `MetalPluginName=NativeAdrenoMetal` and
`MetalPluginClassName=NativeAdrenoMetalDevice`. Its service-scoped
`NativeSandboxGrantProcess` uses the facility already present in the actual
native kernel for backboardd, iconservicesagent, WidgetRenderer_Default and
PosterBoard. There is no new global sandbox or AMFI patch. The actual data
client remains type 0x4147; progress markers are recorded without a connection,
and Apple's type-1 protocol is refused.

`../prepare_metal_sidecars.py` reuses verified component run 45134750180, checking
all signed code pages and special slots before packaging. It adds the publish
marker outside the sealed bundle and trusts only the plugin/Turnip CDHashes.
The two original iPhone 24A446 modules are kept byte-for-byte; no probe daemon is
installed and the original Data seed is not regenerated. Generated sidecars
are explicitly marked **not installed, not boot-capacity-qualified, not
flashable**. `../test_metal_sidecars.py` independently reads them back and rejects
changed original trust, missing/duplicate hashes, malformed offsets/order and
invalid addon paths/modes.

### Remaining integration blockers — no full build yet

* The current 88 MiB FAT cannot hold these sidecars. With the last verified
  82,984,960-byte kernel, original 1,319,024-byte seed, 15,295,680-byte addon,
  92,344-byte owner trust, max ADT and loader allowance, the conservative file
  budget is exceeded by **8,732,136 bytes**. Do not silently resize the 96 MiB
  boot partition, overwrite UFS data or drop the working Data seed. Transport
  space and loader handoff need a reviewed solution and byte-exact host tests.
* This board's root runtime still removes the upstream GPU addon installer and
  mount block. The trusted addon needs a complete transport → memory-map →
  persistent installation → original Metal path chain before activation.
* The original target's Metal discovery path, scoped access and presentation
  need final binary/runtime qualification. Native compiler checks are pending
  for this new frontend; software peers do not substitute for that check.
* The phone's actual CP and known-image/readback result is still pending. The
  previous capture reported CP=0 and ready=0. A published service is not proof
  of a rendered frame.

Local checks: actual publication function over failing IOKit peers (15 failure
paths, disabled/not-ready gates, cleanup, repeated invocation, client types),
retained family binary/PAC inspection with corrupt-code/table negatives,
portable backend/ring/CP/memory tests, display fence tests, source reconstruction
and root preflight provider ordering. These changes are saved with `[skip ci]`;
no Actions build has been requested.
