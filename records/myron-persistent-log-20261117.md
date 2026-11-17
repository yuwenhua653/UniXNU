# Official persistent log route for myron

Implement the UniXNU log-capture workflow instead of relying on framebuffer photographs. References: upstream `docs/porting/log-capture.md`, and UniXNU-sheng 206171054cd9d5f18767dccc43524cd7ba568001 `package/BootLog.c` / `scripts/read-sheng-log.py`.

## Geometry contract

No handset-specific GPT GUIDs, absolute LBAs, image hashes or root-policy metadata are introduced by this change. New host fixtures use a synthetic 256 MiB partition and 64 MiB image. Runtime coordinates come from the already-qualified compiled deployment geometry. The writer requires a bounded 512 KiB tail window after the full signed-carrier capacity, with at least one block of separation; otherwise it refuses to open.

The default upstream 32 MiB log plus 256 MiB export geometry does NOT apply to this partition. `sheng-log` and persistent store remain rejected by the existing root entry. A board-owned hostLogOpen opens only the 128-block log window after authenticated root preparation, matching geometry and GPT checks. Legacy export state remains zero. Runtime per-write bounds, existing locked DMA ownership checks, and first-error stop remain in force.

## Data / recovery

SHLOG001 v5 mode-0 messages: 128 KiB. Five 64 KiB diagnostic slots, written only through their NUL terminator rounded to a block. Unchanged message blocks are skipped. Two cache syncs surround the last header write. The header extension checks message/slot/header CRCs. This detects interrupted/in-place mixed rounds; it does not make the ring power-loss atomic.

A separate kernel thread starts only with log=1, after root preparation. It snapshots the real msgbuf under bsd_log_lock_safe/unlock to exclude resize/free races, and releases the lock before disk I/O. Recorder snapshot acquisition is nonblocking; no writer locks span disk I/O. The 32 KiB pre-reboot console ring freezes at the first recorded reboot/panic. Includes existing first request, user trace, retained reason and shutdown diagnostics.

No panic-context writes or reboot-policy changes. A stop can lose the most recent two seconds; valid old disk data is not proof the latest attempt reached the writer. Boot ID/tag/rounds and integrity results are exposed honestly.

Windows READ-IOS27-LOG.cmd uses PATH adb/Python. Requires exactly one authorized myron in root recovery; ordinary Android need not be rooted. Reads and validates both GPT copies, exact deployment layout/GUID, and kernel block mapping before/after reading. Fixed dd input only, no output device, no reboot/flash/GPT mutations. Device-side stderr suppression and failure marker reject contaminated, short and full-length failed reads. Raw bytes are retained even when no supported log header exists.

## Executed validation

- Actual C++ bounds/commit code under ASan/UBSan: 36 I/O failure points, overlap/overflow rejection, ring rollover, changed-block write accounting, CRC/torn-data detection.
- Actual board worker with hardware stubs: root/geometry/mode/GPT/poison guards, bounded writes, first-error stop, locked source buffer copy.
- Actual recorder under ASan/UBSan: bounded/frozen console, contended snapshot, tiny output, wraparound plus existing reboot/panic/scanout checks.
- Official UNMODIFIED read-sheng-log.py decoded the C++ output; messages/latest slot matched the Windows decoder.
- Reader fake recovery: exact window, changed GPT refusal, raw preservation, failed-dd marker.
- Console route and reboot authorization/timeout regression checks passed.
- Final payload contract now requires persistent log symbols and log=1, and packages the reader/geometry report with firmware.
- Source-only reconstruction passed. Native arm64e compilation and real UFS persistence remain pending CI/device execution.

This is observability work for the PID1 reboot. The screenshot still does not establish the initiating root cause; Halt/Restart Timed Out is downstream. No desktop-boot claim.
