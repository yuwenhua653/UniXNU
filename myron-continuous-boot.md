# myron iOS27 continuous boot

Phone evidence on 2026-11-13: the entry observer reached 2716. That proves the
actual XNU prefix, initial tables, PAC-key setup and MMU enable reached the first
C entry. It does not prove C initialization or desktop startup. The observer
intentionally stopped before the C prologue.

This change builds an uninstrumented-entry source kernel with the existing
myron continuous recorder. It does not patch the terminal observer to resume
after turning off the MMU/cache. The board recorder enables existing C/VM,
bootstrap, BSD, mount and exec hooks via MYRON_EARLY_PROGRESS. The generic sheng
progress policy and optional UFS observer remain disabled. Boot-progress mode 2
records continuously, including after diagnostic deadlines. Normal user page
faults update counters without repainting the display. Process exits retain
status and namespace/code information. Rendering uses only a mapping supplied
by the XNU console and yields ownership when scanout takes over.

The recorder is compiled with the native XNU arm64e recipe, force-loaded into
both the baseline and each root relink, and checked again in the final fileset.
The root authentication and existing explicit root/Data/dyld gates remain in
place. This is not evidence that those stages work on the phone yet.

The workflow builds the source kernel and qualified native payload on macOS,
then automatically rebuilds the final FD on Linux/Clang 18. The second job binds
its input to the same commit/run/source snapshot and verifies the unchanged
installed root and policy hashes. Only the FD changes in that second job; the
new native FAT is preserved exactly. It reruns the loader handoff, PAC capsule
and complete FD checks. The intermediate macOS image is not a phone test package.

Local validation: actual recorder host execution across timeouts; mapping
rejection and pixel bounds; console-to-scanout ownership; process-exit details;
14 storage boot control/relocation tests. CI additionally compiles the recorder
for arm64e and then against the actual native SDK recipe. Phone execution beyond
C entry, real storage initialization and desktop remain pending.
