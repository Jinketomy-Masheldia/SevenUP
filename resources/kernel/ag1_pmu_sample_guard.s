.section __TEXT,__text,regular,pure_instructions
.p2align 2
.globl _ag_entry
_ag_entry:
    // Replay exactly the displaced MOV. Non-null results take the native path.
    mov x24, x0
    cbz x0, Lempty
    b _ag_resume
Lempty:
    sub sp, sp, #0x30
    stp x29, x30, [sp, #0x20]
    add x29, sp, #0x20
    // Darwin arm64 printf variadic parameters are eight-byte stack slots.
    ldr w9, [x21, #0x140]
    mov w10, w20
    mov w11, w26
    stp x9, x10, [sp]
    str x11, [sp, #0x10]
    adr x0, Lmessage
    bl _ag_printf
    // getObject(0) is borrowed. Its containing array is still owned here.
    mov x0, x23
    ldr x8, [x0]
    ldr x8, [x8, #0x28]
    blr x8
    ldp x29, x30, [sp, #0x20]
    add sp, sp, #0x30
    // Native failure path releases the accumulated samples and returns NULL.
    b _ag_fail
.globl _ag_resume, _ag_fail, _ag_printf
_ag_resume:
    b .
_ag_fail:
    b .
_ag_printf:
    b .
Lmessage:
    .asciz "\033[33mAG1 PMU empty sample: channels=%u mode=%u sample=%u; returning failure\033[0m\n"
