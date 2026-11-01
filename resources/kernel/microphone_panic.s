.text
.p2align 4
.globl _np_hook
.private_extern _np_hook
_np_hook:
    sub sp, sp, #0x70
    stp x29, x30, [sp, #0x60]
    stp x19, x20, [sp, #0x40]
    stp x21, x22, [sp, #0x50]
    add x29, sp, #0x60
    adr x19, _np_hook
    ldr x8, Lhook_anchor
    sub x19, x19, x8
    adr x0, Lentry_message
    bl _np_printf
    ldr x8, Lpanic_format_global
    add x8, x8, x19
    ldr x20, [x8]
    ldr x8, Lpanic_args_global
    add x8, x8, x19
    ldr x21, [x8]
    ldr x8, Lpanic_caller_global
    add x8, x8, x19
    ldr x22, [x8]
    adr x8, Lno_reason
    cmp x20, #0
    csel x8, x20, x8, ne
    sub x9, x22, x19
    stp x8, x22, [sp]
    stp x9, x19, [sp, #0x10]
    adr x0, Lmetadata
    bl _np_printf
    cbz x20, Lcomplete
    cbz x21, Lcomplete
    ldr x8, [x21]
    str x8, [sp, #0x30]
    adr x0, Lreason_header
    bl _np_printf
    mov x0, x20
    add x1, sp, #0x30
    adr x2, _np_putchar
    mov w3, #0
    bl _np_doprnt
Lcomplete:
    adr x0, Lcomplete_message
    bl _np_printf
    // Framebuffer fallback after the full console report; preserve original
    // panic arguments and stop before any platform/display panic action.
    mov w0, #7
    mov x1, x22
    mov x2, x20
    mov x3, x21
    ldr x4, [x29]
    mov x5, sp
    bl _np_render
.globl _np_stop
.private_extern _np_stop
_np_stop:
    msr daifset, #0xf
    dsb sy
Lhold:
    wfe
    b Lhold

.p2align 2
.globl _np_putchar
.private_extern _np_putchar
_np_putchar:
    sub sp, sp, #0x20
    stp x29, x30, [sp, #0x10]
    add x29, sp, #0x10
    // Darwin variadic unsigned int argument, in the caller's stack area.
    str w0, [sp]
    adr x0, Lcharacter_format
    bl _np_printf
    ldp x29, x30, [sp, #0x10]
    add sp, sp, #0x20
    ret

.macro NP_STUB name, anchor, target
.p2align 2
.globl \name
.private_extern \name
\name:
    adr x16, \name
    ldr x17, 1f
    sub x16, x16, x17
    ldr x17, 2f
    add x16, x16, x17
    br x16
.p2align 3
1: .quad \anchor
2: .quad \target
.endmacro

NP_STUB _np_printf, 0x7777777777777777, 0xfffffff007215444
NP_STUB _np_doprnt, 0x8888888888888888, 0xfffffff0072152b8

NP_STUB _np_render, 0xaaaaaaaaaaaaaaaa, 0xbbbbbbbbbbbbbbbb

.p2align 3
Lhook_anchor: .quad 0x9999999999999999
Lpanic_format_global: .quad 0xfffffff00793dd90
Lpanic_args_global: .quad 0xfffffff0078ec198
Lpanic_caller_global: .quad 0xfffffff0078ec1b8

Lentry_message: .asciz "\n\033[31mMD PANIC / DEBUGGER ENTRY\033[0m\n"
Lmetadata: .asciz "FORMAT: %s\nCALLER: 0x%016llx\nUNSLID: 0x%016llx\nSLIDE:  0x%016llx\n"
Lreason_header: .asciz "\033[31mREASON: "
Lcomplete_message: .asciz "\033[0m\nMD CAPTURE COMPLETE - HALTED FOR PHOTO\n"
Lno_reason: .asciz "<panic-format unavailable>"
Lcharacter_format: .asciz "%c"
.p2align 2
