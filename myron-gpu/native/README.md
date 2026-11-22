# Native A840 integration stage

This is the first board-driver integration into the myron iPhone27 build.
It is **not a GPU-enabled phone package**. The kernel C++ compile recipe is
connected but has not yet been run against a prepared arm64e XNU tree.
Metal publication, userspace, GPU scanout and hardware rendering remain pending.

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
Neither build selection nor that boot argument is added to production defaults.

The current build does not link `NativeAdrenoAccelerator.cpp`, install a Metal
plugin, relax sandbox/AMFI policy, enable GPU scanout, or change the UI scale.
The iPhone-specific accelerator audit in the parent directory is retained for
the next integration stage. Passing these tests does not establish Metal ABI
compatibility or hardware startup.

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
allocator functions. The CI job runs these source checks only; it does not
start the hour-long kernel/package build.

Next required checks are real XNU compile/link and retained ABI validation,
then matched iOS27 Metal/Turnip code, signed addon capacity, a known rendered
image, and phone verification. Follow the [official GPU porting sequence](https://github.com/UniXNU/UniXNU/blob/8542980d02b4d2cc5c32ee3542de1760b2562aac/docs/porting/gpu.md).
