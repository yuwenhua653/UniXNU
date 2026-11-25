# Dynamic-state allocation fixes

The pinned Mesa source contains a duplicate ordinary viewport/scissor emission
in `DRAW_STATE_FDM`: it allocates and emits a state under the nonzero-size
branch, then allocates and emits it again unconditionally. The second state
replaces the first handle. This wastes command storage and bypasses the
zero-size branch. Remove the second emission.

The dynamic-state macros, FDM viewport/scissor helpers and shader-constant
emitter also ignored sub-stream allocation failures. Propagate the actual
`VkResult` into the command buffer; stop before emission/end when reservation
fails. Graphics/compute callers stop when constant creation fails. Preserve
FDM writeability cleanup on error. This does not invent a successful GPU fence
or retry a failed command as completed work.

The fixes are in `patches/mesa/turnip-dynamic-state-allocation.patch`, recorded
after the existing patches in the compiler input manifest. They target Mesa
`85fda3b36405bcaea8bffc64aa4f2651dc90770d`.

Validation: the patch applies after the selected existing Mesa patches and
reverses exactly. A host fixture executes the actual resolved dynamic-state
macros in 14 success, zero-size, OOM, skipped-state and FDM cases. The pre-fix
source fails the duplicate-allocation assertion. The build recipe runs the
same fixture before compiling the userspace component. This is not an arm64e
compile or a hardware validation.

The next Turnip build also retains line tables and its UUID-matched dSYM.
The installed older library lacks private function symbols; a nearest-export
name is not reliable symbolication. Its crash instructions and allocation
failures motivate this audit, but do not establish that every observed crash
belongs to these particular call sites. Other unchecked command-stream paths
still require review. The ColorAttachment descriptor rejection and PosterBoard
trap remain separate unresolved problems.

These changes require a new GPU userspace component and an updated, verified
addon/trust contract before appearing in a phone package. The existing kernel
build reuses the previous immutable userspace component and cannot include
these changes automatically. No new CI build is requested by this checkpoint.
