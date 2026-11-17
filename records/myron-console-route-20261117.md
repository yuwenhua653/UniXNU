# Buffered console routing after the second reboot photograph

The photo 1000149655.jpg again shows an authorized PID 1 launchd reboot
request (about 0x61 seconds) and a later platform halt/restart timeout.
The earlier reason-log heading is absent. This does not establish the initial
shutdown requester; the process exits shown later can be shutdown cleanup.

Source inspection establishes a diagnostic gap: bsd/dev/arm/km.c sends tty
chunks through console_write(), which can return on disableConsoleOutput
before the existing _cnputc boot-progress interception is reached. The native
video console can set that flag when relinquishing the display. Whether that
flag caused this particular photograph's missing output is not yet observed.

The new board patch routes buffered and unbuffered console entry calls into
the active diagnostic recorder before the native mute gate. It leaves the
entire original native path intact when the board recorder is disabled.
The recorder retains its existing nonblocking writer and framebuffer-ownership
rules. Calls, bytes, natively muted bytes and contention drops are counted
before the first reboot request and displayed in rows 2-4. This lets the next
result distinguish a silent producer from text discarded along the route.
No reboot, shutdown timeout, security checks or service policy is changed.

Validation: the real patched entry gates pass active/inactive and muted/unmuted
cases with no duplicate native output; ASan/UBSan recorder tests cover bounded
reason capture and contention; shutdown authorization/return checks pass;
source overlay reconstruction and final-payload contract regressions pass.
The final payload now requires the console-route function, counters and marker.
Native compilation and real-device log routing remain to be verified.

Supplementary original-launchd analysis run 44050116302 inspects the boot-flag
parser and serial logger wrappers. It does not rebuild or modify the OS binary.
