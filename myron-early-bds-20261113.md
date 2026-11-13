# Early BDS investigation after unchanged four-stripe phone result

The user reports the run 43349357896 boot probe still shows only four coloured
stripes and no 2700–2704 digits. No photograph or colour ordering was supplied.
Absence of the digits does not prove execution never reached the capsule:
framebuffer presentation itself may be failing.

The reviewed firmware has four earlier stripes: cyan at y=96 and magenta at
y=120 in the SEC display handoff, yellow at y=144 at GOP installation, and
green at y=168 in PlatformBootManagerBeforeConsole. If these are the reported
stripes, the last visible milestone precedes EndOfDxe, console connection,
ConnectAll, the UniXNU menu and the later PAC capsule. Those marks cannot
establish that XNU has run. The R58 confirmed source has the same BDS call
sequence as the pre-change iOS27 snapshot; only its displayed revision text
had changed. No specific BDS call is yet established as the cause.

The BDS implementation now draws four large hexadecimal digits at x=32,y=208
using its existing GOP BLT path, independent of ConOut/font services. It adds
no device connection, allocation, hardware register writes or boot-policy
changes. Display failures return to the original flow. Markers indicate the
operation about to execute; they are not completion claims.

| Code | Boundary |
|---|---|
| B001 | EndOfDxe signal |
| B002 | Deferred-image dispatch |
| B003 / B004 / B005 | ConIn / ConOut / ErrOut variable update |
| B006 | BeforeConsole returned; core console connection follows |
| B010 | AfterConsole entered; boot-entry configuration publication |
| B011 | ConnectAll |
| B012 | Existing reviewed memory publisher |
| B013 | Existing handoff audit |
| B014 | Existing embedded FAT publication |
| B015 | Existing console banner |
| B016 | UniXNU FV application launch |
| B017 / B0FF | Application returned success / error |

The snapshot and source digests are updated. The memory contract accepts the
new reviewed BDS while retaining the exact BootMemory.c/MemoryWindow.h contracts.
Its old R54 BDS restoration path now restores the digest-checked snapshot
successor instead of only renaming a banner. Unknown sources remain rejected.

Validation: the actual snapshot C source ran under GCC ASan/UBSan against host
UEFI mocks. Twelve injected stalls retained their expected phase; the original
call order and one-shot application launch were preserved. The error-return
path and five missing/invalid/failing display conditions passed. All rendered
rectangles stayed within x=32..287 and y=208..287. Snapshot reconstruction and
memory-source qualification/rejection passed. Local LeakSanitizer was disabled
because this runtime uses ptrace; ASan/UBSan remained enabled. Local FAT suite
could not start because mformat is absent; CI installs mtools and runs that
suite plus the BDS harness before allowing the native package build.

No new phone boot or desktop success is claimed. Keep the installed unixnu and
original Android backup. The next build exports the small boot candidate;
its new hashes must be bound into an update companion before device use.
