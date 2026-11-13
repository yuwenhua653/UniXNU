// SPDX-License-Identifier: BSD-2-Clause-Patent
// Pinned iOS27 startup observer. No stack, firmware calls, reset or disk IO.
// X18 is scratch at all reviewed sites; start_first_cpu overwrites it before
// consuming it, and it is dead after the bootstrap address adjustment.
.text
.global ProbeEntry
.macro MARK name, phase, target
\name:
  adr x18, Context
  stp x9, x10, [x18, #16]
  stp x11, x12, [x18, #32]
  stp x13, x14, [x18, #48]
  stp x15, x16, [x18, #64]
  stp x17, x30, [x18, #80]
  mrs x9, nzcv
  str x9, [x18, #96]
  mov x9, #\phase
  str x9, [x18, #8]
  bl Render
  adr x18, Context
  ldr x9, [x18, #96]
  msr nzcv, x9
  ldp x9, x10, [x18, #16]
  ldp x11, x12, [x18, #32]
  ldp x13, x14, [x18, #48]
  ldp x15, x16, [x18, #64]
  ldp x17, x30, [x18, #80]
  b \target
.endm
ProbeEntry:
  adr x18, Context
  str x0, [x18]
  b EntryMark
MARK EntryMark, 0x2710, start_first_cpu
// Displaced instructions are executed exactly once, after each marker.
MARK LowMark, 0x2711, LowResume
LowResume:
  ldr x22, [x20, #8]
  b low_continue
MARK TablesMark, 0x2712, TablesResume
TablesResume:
  dsb ish
  b tables_continue
MARK KeysMark, 0x2713, KeysResume
KeysResume:
  ldp x2, x3, [x0]
  b keys_continue
MARK MmuMark, 0x2714, MmuResume
MmuResume:
  msr sctlr_el1, x0
  b mmu_continue
// Called instead of the first C prologue. The bootstrap path has performed
// no cached stores since enabling translation. Its x22/x23 still describe
// the VA/PA slide; switch to the existing identity mapping before disabling
// translation for the terminal readout. Never resume into C with caches off.
.global CStop
CStop:
  adr x18, CPhysical
  sub x18, x18, x22
  add x18, x18, x23
  br x18
CPhysical:
  msr daifset, #15
  dsb sy
  mrs x18, sctlr_el1
  bic x18, x18, #1
  bic x18, x18, #4
  bic x18, x18, #0x1000
  msr sctlr_el1, x18
  isb
  tlbi vmalle1
  dsb sy
  isb
  mov x9, #0x2716
  adr x18, Context
  str x9, [x18, #8]
  bl Render
.global ProbePark
ProbePark:
  dsb sy
  wfe
  b ProbePark
// Low exception vectors are only used before bootstrap installs normal
// vectors. Capture their first fault and stop; never suppress it and continue.
.global LowFault
LowFault:
  msr daifset, #15
  adr x18, Context
  mrs x9, esr_el1
  mrs x10, elr_el1
  mrs x11, far_el1
  stp x9, x10, [x18, #104]
  str x11, [x18, #120]
  ldr x9, [x18, #8]
  str x9, [x18, #128]
  mov x9, #0x27ee
  str x9, [x18, #8]
  bl Render
  b ProbePark
// Sixteen hex digits at quarter-screen height, separate from UEFI text.
// x9=value, x18=context; x9..x17 clobbered, caller saves/restores them.
Render:
  ldr x10, [x18]
  ldr x11, [x10, #0x28]
  ldr x12, [x10, #0x38]
  ldr x13, [x10, #0x48]
  lsr x13, x13, #2
  madd x11, x13, x12, x11
  mov x10, #60
Digit:
  lsrv x13, x9, x10
  and x13, x13, #15
  adr x14, Font
  mov x15, #7
  madd x14, x13, x15, x14
  mov x13, #0
Row:
  ldrb w15, [x14, x13]
  mov x16, #0
Column:
  mov x17, #4
  sub x17, x17, x16
  lsr w17, w15, w17
  and w17, w17, #1
  neg w17, w17
  // Each glyph pixel is 4x4, 24 pixels between digit origins.
  stp w17, w17, [x11]
  stp w17, w17, [x11, #8]
  add x11, x11, x12
  stp w17, w17, [x11]
  stp w17, w17, [x11, #8]
  add x11, x11, x12
  stp w17, w17, [x11]
  stp w17, w17, [x11, #8]
  add x11, x11, x12
  stp w17, w17, [x11]
  stp w17, w17, [x11, #8]
  sub x11, x11, x12, lsl #1
  sub x11, x11, x12
  add x11, x11, #16
  add x16, x16, #1
  cmp x16, #5
  b.lo Column
  sub x11, x11, #80
  add x11, x11, x12, lsl #2
  add x13, x13, #1
  cmp x13, #7
  b.lo Row
  mov x13, #28
  msub x11, x13, x12, x11
  add x11, x11, #96
  subs x10, x10, #4
  b.ge Digit
  dsb sy
  ret
Font:
.byte 14,17,19,21,25,17,14
.byte 4,12,4,4,4,4,14
.byte 14,17,1,2,4,8,31
.byte 30,1,1,14,1,1,30
.byte 2,6,10,18,31,2,2
.byte 31,16,16,30,1,1,30
.byte 14,16,16,30,17,17,14
.byte 31,1,2,4,8,8,8
.byte 14,17,17,14,17,17,14
.byte 14,17,17,15,1,1,14
.byte 14,17,17,31,17,17,17
.byte 30,17,17,30,17,17,30
.byte 14,17,16,16,16,17,14
.byte 30,17,17,17,17,17,30
.byte 31,16,16,30,16,16,31
.byte 31,16,16,30,16,16,16
.balign 8
.global Context
Context: .space 136
