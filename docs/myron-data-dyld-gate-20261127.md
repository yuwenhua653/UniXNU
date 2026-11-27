# Accept committed Data capacity at the post-mount dyld gate

The Data mount gate already accepted a committed 16 GiB persistent store, but
`myron_dyld_startup_prepare` still required its reported capacity to equal the
immutable 1 GiB seed size. On an expanded block provider, the gate therefore
returned EAUTH before resolving launchd/dyld and their cache files. Its caller
treats a nonzero result as fatal (`myron dyld startup refused`).

The post-mount gate now uses the same capacity exception as the mount gate:
the original seed must be 1 GiB and `myron_data_capacity_valid(bytes)` must
confirm the active committed store. Seed hash, Data UUID/device, distinct
root/cache/Data devices, read-only original root/cache, live namespace and all
reviewed dyld cache file checks are retained. The seed and on-disk Data are not
rewritten by this change.

`test_data_dyld.py` compiles the actual generated startup gate with the existing
full startup fixture. A baseline control reinstates only the old size check
and reproduces EAUTH on 16 GiB without a commpage update. The corrected gate
runs the 140 existing scenarios at both 1 GiB and 16 GiB (280 total), plus
unauthorized expansion, unsupported sizes and disabled-entry cases.

The runtime preflight now runs this test before the full build. The original
small synthetic-seed fixture also retains a declaration for the capacity
callback so strict C11 compilation does not depend on dead-code elimination.

Host validation does not establish that every device reboot cause is removed.
The APFS container may still have its original 1 GiB logical size until the
phone-side helper completes and verifies expansion; a 16 GiB block provider
alone is not proof of that completion.
