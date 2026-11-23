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

The current build does not link `NativeAdrenoAccelerator.cpp`, install a Metal
plugin, relax sandbox/AMFI policy, enable GPU scanout, or advertise hardware rendering. UI scale is handled separately by myron-runtime.
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
linked or published. Next are the iOS27 Metal/Turnip artifact, real producer
fences for both CPU display-copy paths, retained accelerator binding, target
trust merge, signed addon capacity, and a known rendered image on the phone. Follow the [official GPU porting sequence](https://github.com/UniXNU/UniXNU/blob/8542980d02b4d2cc5c32ee3542de1760b2562aac/docs/porting/gpu.md).
