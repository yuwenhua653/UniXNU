/* Real PAC instructions, real EL0, and real hardware translation in QEMU TCG.
 * Keys are public synthetic test constants. This does not boot the phone kernel.
 */
.arch armv8.3-a
#ifndef FINAL_T0SZ
#define FINAL_T0SZ 21
#endif
#ifndef ENABLE_PAC
#define ENABLE_PAC 1
#endif
.equ KBASE, 0xffffffc000000000
.equ TARGET, 0x1e9d71f70
.equ SLOT, 0x6ae10001e9d71f98
/* 4K, inner-shareable WB, 40-bit PA, TBI0, T1SZ26, TG1=4K. */
.equ TCR_BASE, (2 << 32) | (1 << 37) | (2 << 30) | (26 << 16) | (3 << 28) | (1 << 26) | (1 << 24) | (3 << 12) | (1 << 10) | (1 << 8)
.text
.global _start
_start:
  mrs x9, CurrentEL
  cmp x9, #4
  b.ne fail
  msr DAIFSet, #15
  ldr x9, =stack_top
  mov sp, x9
  /* QEMU's ELF loader zeros .bss; fill only the reviewed valid entries. */
  ldr x9, =user_l1
  ldr x10, =0x40000701
  str x10, [x9, #8]
  ldr x10, =user_l2
  orr x10, x10, #3
  str x10, [x9, #56]
  ldr x9, =user_l2
  ldr x10, =0x41000741
  mov x11, #((TARGET >> 21) & 511)
  str x10, [x9, x11, lsl #3]
  ldr x9, =user_l0
  ldr x10, =user_l1
  orr x10, x10, #3
  str x10, [x9]
  ldr x9, =kernel_l1
  ldr x10, =0x40000701
  str x10, [x9, #8]
  ldr x9, =0x41171f70
  ldr x10, =0x2710435041430001
  str x10, [x9]
  ldr x9, =0x1122334455667788
  msr APDAKeyLo_EL1, x9
  ldr x9, =0x8877665544332211
  msr APDAKeyHi_EL1, x9
  mov x9, #0xff
  msr MAIR_EL1, x9
  ldr x9, =TCR_BASE | 26
  msr TCR_EL1, x9
  ldr x9, =user_l1
  msr TTBR0_EL1, x9
  ldr x9, =kernel_l1
  msr TTBR1_EL1, x9
  dsb sy
  isb
  mrs x9, SCTLR_EL1
#if ENABLE_PAC
  orr x9, x9, #(1 << 27)
#else
  bic x9, x9, #(1 << 27)
#endif
  orr x9, x9, #1
  msr SCTLR_EL1, x9
  isb
  ldr x9, =kernel_entry + KBASE
  br x9
kernel_entry:
  /* Startup executes privileged-only identity memory; expose it to EL0 only
   * after instruction fetch has moved to the separate kernel alias. */
  ldr x9, =user_l1 + KBASE
  ldr x10, =0x40000741
  str x10, [x9, #8]
  dsb ishst
  tlbi vmalle1
  dsb ish
  isb
  ldr x9, =stack_top + KBASE
  mov sp, x9
  ldr x9, =vectors + KBASE
  msr VBAR_EL1, x9
  isb
  mov x20, #38
  ldr x22, =TARGET
  ldr x23, =SLOT
  mov x25, #0 /* negative authentication checks */
  mov x26, #0 /* old malformed load faults */
  mov x28, #0 /* FPAC traps (otherwise AUTDA returns poison) */
  ldr x9, =user_old
  msr ELR_EL1, x9
  mov x9, #0x3c0
  msr SPSR_EL1, x9
  eret

user_old:
  /* Find a nonzero residual under the 43-bit ObjC mask. Usually first attempt.
   * Only synthetic address diversity changes; the target and key stay fixed.
   */
  mov x8, #256
1:mov x21, x22
  pacda x21, x23
  and x24, x21, #0x7fffffffff8
  cmp x24, x22
  b.ne auth_checks
  add x23, x23, #8
  subs x8, x8, #1
  b.ne 1b
  svc #0xff
user_new:
  mov x21, x22
  pacda x21, x23
  and x24, x21, #0x7fffffffff8
  cmp x24, x22
  b.ne user_fail
  /* New geometry must perform an actual successful load through the ISA. */
  ldr x0, [x24]
  ldr x1, =0x2710435041430001
  cmp x0, x1
  b.ne user_fail
  mov x25, #0

auth_checks:
  mov x0, x21
  autda x0, x23
  cmp x0, x22
  b.ne user_fail
  /* Accept either architected failed-auth poison or a FEAT_FPAC exception. */
  mov x27, #1
  mov x0, x21
  eor x1, x23, #1
bad_modifier_insn:
  autda x0, x1
bad_modifier_return:
  cmp x0, x22
  b.eq user_fail
  add x25, x25, #1
  mov x27, #2
  eor x0, x21, #(1 << 48)
bad_signature_insn:
  autda x0, x23
bad_signature_return:
  cmp x0, x22
  b.eq user_fail
  add x25, x25, #1
  mov x27, #0
  cmp x20, #38
  b.ne user_new_done
  mov x27, #3
bad_load_insn:
  ldr x0, [x24]
  b user_fail
bad_load_return:
  mov x27, #0
  cmp x26, #1
  b.ne user_fail
  svc #0x38
user_new_done:
  svc #0x43
user_fail:
  svc #0xff
  b .

.balign 2048
vectors:
.rept 8
  b unexpected
  .space 124
.endr
  b sync_el0
  .space 124
.rept 7
  b unexpected
  .space 124
.endr
sync_el0:
  mrs x9, ESR_EL1
  lsr x10, x9, #26
  cmp x10, #0x15 /* SVC64 */
  b.eq svc_handler
  cmp x10, #0x1c /* PAC authentication failure */
  b.eq auth_trap
  cmp x10, #0x24 /* EL0 data abort */
  b.ne unexpected
  cmp x27, #3
  b.ne unexpected
  mrs x10, ELR_EL1
  ldr x11, =bad_load_insn
  cmp x10, x11
  b.ne unexpected
  mrs x10, FAR_EL1
  cmp x10, x24
  b.ne unexpected
  tbnz x9, #6, unexpected /* must be a read */
  and x11, x9, #0x3f
  cmp x11, #7 /* address-size or translation fault, level 0..3 */
  b.hi unexpected
  ldr x11, =fault_record + KBASE
  stp x10, x9, [x11]
  add x26, x26, #1
  ldr x10, =bad_load_return
  msr ELR_EL1, x10
  eret
auth_trap:
  mrs x10, ELR_EL1
  cmp x27, #1
  b.eq 1f
  cmp x27, #2
  b.ne unexpected
  ldr x11, =bad_signature_insn
  cmp x10, x11
  b.ne unexpected
  ldr x10, =bad_signature_return
  b 2f
1:ldr x11, =bad_modifier_insn
  cmp x10, x11
  b.ne unexpected
  ldr x10, =bad_modifier_return
2:msr ELR_EL1, x10
  mov x0, #0
  add x28, x28, #1
  eret
svc_handler:
  and x9, x9, #0xffff
  cmp x9, #0x38
  b.eq old_done
  cmp x9, #0x43
  b.eq new_done
  b fail
old_done:
  cmp x20, #38
  b.ne fail
  cmp x25, #2
  b.ne fail
  adr x1, old_signed
  mov x2, x21
  bl print_hex
  adr x1, old_masked
  mov x2, x24
  bl print_hex
  adr x1, chosen_modifier
  mov x2, x23
  bl print_hex
  adr x1, old_far
  ldr x9, =fault_record + KBASE
  ldr x2, [x9]
  bl print_hex
  adr x1, old_esr
  ldr x9, =fault_record + KBASE
  ldr x2, [x9, #8]
  bl print_hex
  adr x1, old_tcr
  mrs x2, TCR_EL1
  bl print_hex
  /* Execute from TTBR1 while TTBR0 is blank, exactly as the XNU transition. */
  ldr x9, =blank_root
  msr TTBR0_EL1, x9
  dsb ish
  isb
  tlbi vmalle1
  dsb ish
  isb
  ldr x9, =TCR_BASE | FINAL_T0SZ
  msr TCR_EL1, x9
  isb
  tlbi vmalle1
  dsb ish
  isb
  /* Both instruction fetch and data load must work on unchanged kernel L1. */
  ldr x9, =0x41171f70 + KBASE
  ldr x10, [x9]
  ldr x11, =0x2710435041430001
  cmp x10, x11
  b.ne fail
  mrs x9, TTBR1_EL1
  ldr x10, =kernel_l1
  cmp x9, x10
  b.ne fail
  ldr x9, =user_l0
  msr TTBR0_EL1, x9
  dsb ish
  isb
  tlbi vmalle1
  dsb ish
  isb
  mov x20, #43
  ldr x9, =user_new
  msr ELR_EL1, x9
  mov x9, #0x3c0
  msr SPSR_EL1, x9
  eret
new_done:
  cmp x20, #43
  b.ne fail
  cmp x25, #2
  b.ne fail
  cmp x26, #1
  b.ne fail
  adr x1, new_signed
  mov x2, x21
  bl print_hex
  adr x1, new_masked
  mov x2, x24
  bl print_hex
  adr x1, new_tcr
  mrs x2, TCR_EL1
  bl print_hex
  adr x1, auth_traps
  mov x2, x28
  bl print_hex
  adr x1, pass_message
  mov x0, #4
  hlt #0xf000
  adr x1, exit_ok
  mov x0, #0x20
  hlt #0xf000
  b .

/* SYS_WRITE0 prefix and hexadecimal value; clobbers x0..x8, x9 is untouched. */
print_hex:
  mov x0, #4
  hlt #0xf000
  adr x1, hex_buffer
  mov x3, #16
  mov x4, x2
1:lsr x5, x4, #60
  cmp x5, #10
  add x6, x5, #'0'
  add x7, x5, #('a' - 10)
  csel x6, x6, x7, lo
  strb w6, [x1], #1
  lsl x4, x4, #4
  subs x3, x3, #1
  b.ne 1b
  mov w6, #10
  strb w6, [x1], #1
  strb wzr, [x1]
  adr x1, hex_buffer
  mov x0, #4
  hlt #0xf000
  ret
unexpected:
  mrs x2, ESR_EL1
  adr x1, unexpected_esr
  bl print_hex
  mrs x2, ELR_EL1
  adr x1, unexpected_pc
  bl print_hex
fail:
  adr x1, fail_message
  mov x0, #4
  hlt #0xf000
  adr x1, exit_fail
  mov x0, #0x20
  hlt #0xf000
  b .
.balign 8
exit_ok: .quad 0x20026, 0
exit_fail: .quad 0x20026, 1
old_signed: .asciz "OLD_SIGNED="
old_masked: .asciz "OLD_MASKED="
chosen_modifier: .asciz "MODIFIER="
old_far: .asciz "OLD_FAR="
old_esr: .asciz "OLD_ESR="
old_tcr: .asciz "OLD_TCR="
new_signed: .asciz "NEW_SIGNED="
new_masked: .asciz "NEW_MASKED="
new_tcr: .asciz "NEW_TCR="
auth_traps: .asciz "AUTH_TRAPS="
unexpected_esr: .asciz "UNEXPECTED_ESR="
unexpected_pc: .asciz "UNEXPECTED_PC="
pass_message: .asciz "PASS: real EL0 PAC, 38-bit failure, 43-bit load, unchanged kernel L1, auth rejection\n"
fail_message: .asciz "FAIL: VA/PAC reproducer invariant\n"
.ltorg
.data
hex_buffer: .space 18
.balign 16
fault_record: .space 16
.bss
.balign 4096
user_l1: .space 4096
user_l2: .space 4096
user_l0: .space 4096
kernel_l1: .space 4096
blank_root: .space 4096
.balign 16
.space 4096
stack_top:
