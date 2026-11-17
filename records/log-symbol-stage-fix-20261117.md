# UFS log symbol verification phase fix

Run 44066591261 failed in native-prelink-input. The native source kernel and recorder had compiled; the diagnostic explicitly reports no unresolved symbols and only four missing definitions: myron_log_state, myron_log_rounds, myron_log_errors, myron_log_first_lba.

Those four variables live in MyronBootLog.h, included by the root-enabled MyronUfsProbe object. That object is linked in the subsequent root_runtime stage, so requiring it in the earlier standalone kernel is incorrect. Retain myron_boot_log_snapshot in the early check because it belongs to the native recorder archive. Retain all four UFS symbols in myron_continuous_contract's final fileset check. No log writer, storage bounds, boot arguments, signing or reset policy changed.

Regression reads the actual early verifier symbol set from the source overlay and checks phase separation. It fails on ec2bc941 and passes after this fix. The final Mach-O fixture rejects each missing UFS log symbol. All eleven contract tests pass. The workflow now runs this suite before reference downloads and the full kernel build.

Actual macOS diagnostic artifacts from the failed run also confirm the persistent log fault-injection suite and worker guard tests passed. Native UFS integration, firmware packaging and physical logging remain to be verified by the next run/device test.
