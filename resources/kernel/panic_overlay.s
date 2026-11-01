.text
.p2align 12
.globl _pd_hook
.private_extern _pd_hook
_pd_hook:
    stp x29, x30, [sp, #-0x40]!
    mov x29, sp
    stp x0, x1, [sp, #0x10]
    stp x2, x3, [sp, #0x20]
    ldr x4, [sp]
    add x5, sp, #0x40
    bl _pd_capture
    ldp x0, x1, [sp, #0x10]
    ldp x2, x3, [sp, #0x20]
    ldp x29, x30, [sp], #0x40
    // Stolen instruction from check_and_handle_nested_panic.
    sub sp, sp, #0x50
    b _pd_nested_resume

.globl _pd_save_hook
.private_extern _pd_save_hook
_pd_save_hook:
    stp x29, x30, [sp, #-0x20]!
    mov x29, sp
    stp x0, x1, [sp, #0x10]
    bl _pd_render
    ldp x0, x1, [sp, #0x10]
    ldp x29, x30, [sp], #0x20
    // Stolen instruction from PESavePanicInfo.
    stp x29, x30, [sp, #-0x10]!
    b _pd_save_resume

.globl _pd_context
.private_extern _pd_context
_pd_context:
Lcontext_pc:
    adr x0, Lcontext_pc
    ldr x1, Lcontext_anchor
    sub x0, x0, x1
    ldr x1, Lcontext_address
    add x0, x0, x1
    ret
.p2align 3
Lcontext_anchor:
    .quad 0x1111222233334444
Lcontext_address:
    .quad 0xfffffff0078ebc00

.globl _pd_doprnt
.private_extern _pd_doprnt
_pd_doprnt:
Ldoprnt_pc:
    adr x16, Ldoprnt_pc
    ldr x17, Ldoprnt_anchor
    sub x16, x16, x17
    ldr x17, Ldoprnt_target
    add x16, x16, x17
    br x16
.p2align 3
Ldoprnt_anchor:
    .quad 0x2222333344445555
Ldoprnt_target:
    .quad 0xfffffff0072152b8

_pd_nested_resume:
Lnested_pc:
    adr x16, Lnested_pc
    ldr x17, Lnested_anchor
    sub x16, x16, x17
    ldr x17, Lnested_target
    add x16, x16, x17
    br x16
.p2align 3
Lnested_anchor:
    .quad 0x3333444455556666
Lnested_target:
    .quad 0xfffffff0071f5258

_pd_save_resume:
Lsave_pc:
    adr x16, Lsave_pc
    ldr x17, Lsave_anchor
    sub x16, x16, x17
    ldr x17, Lsave_target
    add x16, x16, x17
    br x16
.p2align 3
Lsave_anchor:
    .quad 0x4444555566667777
Lsave_target:
    .quad 0xfffffff00781ddf8
