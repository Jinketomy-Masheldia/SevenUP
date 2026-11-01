.text
.p2align 12
.globl _ch2_wait
.private_extern _ch2_wait
// Replaces one BL in AppleARMPlatform's function resolver.
// x0=matching dictionary, x1=timeout; x19=OSSymbol, x20=validated OSData.
// The original native wait is invoked once, with unchanged arguments/timeout.
_ch2_wait:
    sub sp, sp, #0x80
    stp x29, x30, [sp, #0x70]
    stp x21, x22, [sp, #0x60]
    stp x0, x1, [sp, #0x20]
    str xzr, [sp, #0x48]
    mov x0, x20
    bl _ch2_data_bytes
    cbz x0, Lwait_native
    ldr w21, [x0]
    ldr w22, [x0, #4]
    cmp w21, #82
    b.eq Lwait_log
    cmp w21, #86
    b.eq Lwait_log
    cmp w21, #87
    b.ne Lwait_native
Lwait_log:
    stp x21, x22, [sp, #0x50]
    mov x0, x19
    bl _ch2_string_bytes
    cbnz x0, Lwait_string_ok
    adr x0, Lunknown
Lwait_string_ok:
    str x0, [sp, #0x40]
    mov w9, #1
    str x9, [sp, #0x48]
    stp x0, x21, [sp]
    str x22, [sp, #0x10]
    adr x0, Lwait_message
    bl _ch2_printf
Lwait_native:
    ldp x0, x1, [sp, #0x20]
    bl _ch2_native_wait
    str x0, [sp, #0x30]
    ldr x9, [sp, #0x48]
    cbz x9, Lwait_done
    cmp x0, #0
    cset w10, ne
    ldr x9, [sp, #0x40]
    ldr x11, [sp, #0x50]
    stp x9, x11, [sp]
    str x10, [sp, #0x10]
    adr x0, Lfound_message
    bl _ch2_printf
Lwait_done:
    ldr x0, [sp, #0x30]
    ldp x21, x22, [sp, #0x60]
    ldp x29, x30, [sp, #0x70]
    add sp, sp, #0x80
    ret

.p2align 2
.globl _ch2_meta
.private_extern _ch2_meta
_ch2_meta:
    sub sp, sp, #0x40
    stp x29, x30, [sp, #0x30]
    stp x0, x1, [sp, #0x10]
    stp x2, x3, [sp, #0x20]
    adr x0, Lmeta_begin
    bl _ch2_printf
    ldp x0, x1, [sp, #0x10]
    ldp x2, x3, [sp, #0x20]
    bl _ch2_native_meta
    str x0, [sp, #0x10]
    adr x0, Lmeta_end
    bl _ch2_printf
    ldr x0, [sp, #0x10]
    ldp x29, x30, [sp, #0x30]
    add sp, sp, #0x40
    ret

// Entry hooks preserve argument registers and original return address,
// then replay the displaced SUB SP,SP,#0x30 before resuming the function.
.macro ENTRY_TRACE name, message, resume
.p2align 2
.globl \name
.private_extern \name
\name:
    sub sp, sp, #0x50
    stp x0, x1, [sp]
    stp x2, x3, [sp, #0x10]
    stp x4, x5, [sp, #0x20]
    stp x6, x7, [sp, #0x30]
    stp x29, x30, [sp, #0x40]
    adr x0, \message
    bl _ch2_printf
    ldp x0, x1, [sp]
    ldp x2, x3, [sp, #0x10]
    ldp x4, x5, [sp, #0x20]
    ldp x6, x7, [sp, #0x30]
    ldp x29, x30, [sp, #0x40]
    add sp, sp, #0x50
    sub sp, sp, #0x30
    b \resume
.endmacro

ENTRY_TRACE _ch2_start_entry, Lstart_begin, _ch2_start_resume
ENTRY_TRACE _ch2_handle_entry, Lhandle_begin, _ch2_handle_resume

// Return hooks run after each native epilogue, retaining native x0 and LR.
.macro RETURN_TRACE name, message
.p2align 2
.globl \name
.private_extern \name
\name:
    sub sp, sp, #0x20
    stp x29, x30, [sp, #0x10]
    str x0, [sp, #8]
    mov w9, w0
    str x9, [sp]
    adr x0, \message
    bl _ch2_printf
    ldr x0, [sp, #8]
    ldp x29, x30, [sp, #0x10]
    add sp, sp, #0x20
    ret
.endmacro

RETURN_TRACE _ch2_start_return, Lstart_return
RETURN_TRACE _ch2_handle_return, Lhandle_return

.p2align 2
.globl _ch2_publish
.private_extern _ch2_publish
// Replaces the original virtual registerService BLR x8.
_ch2_publish:
    sub sp, sp, #0x40
    stp x29, x30, [sp, #0x30]
    stp x0, x1, [sp, #0x10]
    str x8, [sp, #0x20]
    adr x0, Lpublish_begin
    bl _ch2_printf
    ldp x0, x1, [sp, #0x10]
    ldr x8, [sp, #0x20]
    blr x8
    str x0, [sp, #0x10]
    adr x0, Lpublish_end
    bl _ch2_printf
    ldr x0, [sp, #0x10]
    ldp x29, x30, [sp, #0x30]
    add sp, sp, #0x40
    ret

// Builder replaces these BRK instructions with checked direct B targets.
// All references are relative: no absolute pointer or added KASLR fixup.
.macro EXTERNAL name
.p2align 2
.globl \name
.private_extern \name
\name:
    brk #0x2c2
.endmacro
EXTERNAL _ch2_printf
EXTERNAL _ch2_data_bytes
EXTERNAL _ch2_string_bytes
EXTERNAL _ch2_native_wait
EXTERNAL _ch2_native_meta
EXTERNAL _ch2_start_resume
EXTERNAL _ch2_handle_resume

Lunknown: .asciz "?"
Lwait_message: .asciz "\033[32mCH2 WAIT %.64s ph=%u fn=%08x\033[0m\n"
Lfound_message: .asciz "\033[32mCH2 FOUND %.64s ph=%u found=%u\033[0m\n"
Lmeta_begin: .asciz "\033[32mCH2 Chestnut meta begin\033[0m\n"
Lmeta_end: .asciz "\033[32mCH2 Chestnut meta end\033[0m\n"
Lstart_begin: .asciz "\033[32mCH2 Chestnut start begin\033[0m\n"
Lstart_return: .asciz "\033[32mCH2 Chestnut start result=%u\033[0m\n"
Lhandle_begin: .asciz "\033[32mCH2 Chestnut handleStart begin\033[0m\n"
Lhandle_return: .asciz "\033[32mCH2 Chestnut handleStart result=%08x\033[0m\n"
Lpublish_begin: .asciz "\033[32mCH2 Chestnut publish begin\033[0m\n"
Lpublish_end: .asciz "\033[32mCH2 Chestnut publish returned\033[0m\n"
.p2align 2
