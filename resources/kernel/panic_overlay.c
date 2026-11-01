/* Diagnostic renderer for the supplied T8010 kernel. No allocation or locks.
 * Uppercase 5x7 glyphs are hand specified below; ordinary kernel console
 * enable/disable and the graphics server are deliberately not called here.
 */
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef unsigned long uptr;

#define PD_STATE_VA 0xfffffff0078ebc00UL
#define PD_VINFO_VA 0xfffffff00791e9d8UL
#define PD_MAGIC 0x314b50414e494343ULL
#define MESSAGE_CAP 512

struct video {
    u32 height, width, depth, stride;
    uptr base;
    u32 type;
    char name[32];
    u64 physical;
    u32 rows, columns, rowscanbytes, scale, rotate, reserved[3];
};
struct pd_state {
    u64 magic;
    u32 busy, stage, length, render_count;
    uptr caller, slide, options;
    u32 frame_count, reserved;
    uptr frames[12];
    char message[MESSAGE_CAP];
};
_Static_assert(sizeof(struct pd_state) <= 1024, "Reserved state overflow");
_Static_assert(__builtin_offsetof(struct video, base) == 16, "vinfo base layout");
_Static_assert(__builtin_offsetof(struct video, physical) == 64, "vinfo physical layout");
extern struct pd_state *pd_context(void);
extern void pd_doprnt(const char *, const uptr *, void (*)(int), int);

/* Five columns per glyph, least significant bit at the top. */
static const char glyph_names[] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-_:./()[]<>+=!?%#,@\\'\"*|&";
static const u8 glyphs[][5] = {
 {62,81,73,69,62},{0,66,127,64,0},{66,97,81,73,70},{33,65,69,75,49},
 {24,20,18,127,16},{39,69,69,69,57},{60,74,73,73,48},{1,113,9,5,3},
 {54,73,73,73,54},{6,73,73,41,30},
 {126,17,17,17,126},{127,73,73,73,54},{62,65,65,65,34},{127,65,65,34,28},
 {127,73,73,73,65},{127,9,9,9,1},{62,65,73,73,122},{127,8,8,8,127},
 {0,65,127,65,0},{32,64,65,63,1},{127,8,20,34,65},{127,64,64,64,64},
 {127,2,12,2,127},{127,4,8,16,127},{62,65,65,65,62},{127,9,9,9,6},
 {62,65,81,33,94},{127,9,25,41,70},{70,73,73,73,49},{1,1,127,1,1},
 {63,64,64,64,63},{31,32,64,32,31},{63,64,56,64,63},{99,20,8,20,99},
 {7,8,112,8,7},{97,81,73,69,67},
 {8,8,8,8,8},{64,64,64,64,64},{0,54,54,0,0},{0,96,96,0,0},
 {32,16,8,4,2},{0,28,34,65,0},{0,65,34,28,0},{0,127,65,65,0},
 {0,65,65,127,0},{8,20,34,65,0},{0,65,34,20,8},{8,8,62,8,8},
 {20,20,20,20,20},{0,0,95,0,0},{2,1,81,9,6},{35,19,8,100,98},
 {20,127,20,127,20},{0,80,48,0,0},{62,65,93,85,30},{2,4,8,16,32},
 {0,5,3,0,0},{0,7,0,7,0},{20,8,62,8,20},{0,0,127,0,0},
 {54,73,85,34,80}
};
_Static_assert(sizeof(glyphs) / 5 == sizeof(glyph_names) - 1, "Glyph table mismatch");

struct canvas {
    volatile u32 *base;
    u32 width, height, pitch, x, y, scale, color;
};

static void put(struct canvas *c, int ch) {
    if (ch == '\r') return;
    if (ch == '\n') { c->x = 8; c->y += 9 * c->scale; return; }
    if (c->x + 6 * c->scale >= c->width) { c->x = 8; c->y += 9 * c->scale; }
    if (c->y + 7 * c->scale >= c->height) return;
    if (ch >= 'a' && ch <= 'z') ch -= 32;
    if (ch != ' ') {
        unsigned index = 0;
        while (glyph_names[index] && glyph_names[index] != ch) ++index;
        for (u32 x = 0; x < 5; ++x) {
            u8 bits = glyph_names[index] ? glyphs[index][x] : 127;
            for (u32 y = 0; y < 7; ++y) if (bits & (1U << y))
                for (u32 dy = 0; dy < c->scale; ++dy)
                    for (u32 dx = 0; dx < c->scale; ++dx)
                        c->base[(c->y + y*c->scale + dy)*c->pitch + c->x + x*c->scale + dx] = c->color;
        }
    }
    c->x += 6 * c->scale;
}
static void text(struct canvas *c, const char *s, u32 max) {
    for (u32 i = 0; i < max && s[i]; ++i) put(c, (u8)s[i]);
}
static void hex(struct canvas *c, uptr value) {
    text(c, "0X", 2);
    for (int bit = 60; bit >= 0; bit -= 4) {
        unsigned d = (unsigned)(value >> bit) & 15;
        put(c, d < 10 ? '0' + d : 'A' + d - 10);
    }
}

__attribute__((noinline)) void pd_render(void) {
    struct pd_state *s = pd_context();
    if (s->magic != PD_MAGIC) return;
    if (s->render_count >= 4) return;
    struct video *v = (struct video *)(PD_VINFO_VA + s->slide);
    uptr base = v->base;
    u32 w = v->width, h = v->height, stride = v->stride;
    if (v->depth != 32 || !base || (base & 3) || w < 80 || w > 4096 ||
        h < 80 || h > 4096 || stride < w*4 || stride > 65536 || (stride & 3)) return;
#ifndef PD_HOST_TEST
    if ((base >> 48) != 0xffff) return;
#endif
    struct canvas c = {(volatile u32 *)base, w, h, stride/4, 8, 8, w >= 480 ? 2 : 1, 0x00ffff60};
    /* Do not touch stride padding, mappings, display registers or console state. */
    for (u32 y = 0; y < h; ++y)
        for (u32 x = 0; x < w; ++x) c.base[y*c.pitch + x] = 0x00200000;
    text(&c, "K1 PANIC / DEBUGGER CAPTURE\n", 32);
    text(&c, s->stage < 3 ? "ENTRY CAPTURED\n" : "REASON:\n", 32);
    c.color = 0x00ffffff;
    text(&c, s->message, MESSAGE_CAP);
    text(&c, "\nCALLER ", 9); hex(&c, s->caller);
    text(&c, "\nUNSLID ", 9); hex(&c, s->caller - s->slide);
    text(&c, "\nSLIDE  ", 9); hex(&c, s->slide);
    text(&c, "\nOPTIONS ", 10); hex(&c, s->options);
    text(&c, "\nFRAME RETURNS (UNSLID):\n", 32);
    for (u32 i = 0; i < s->frame_count && i < 12; ++i) {
        hex(&c, s->frames[i] - s->slide); put(&c, '\n');
    }
    ++s->render_count;
    __asm__ volatile("dsb sy" ::: "memory");
}

static void capture_character(int ch) {
    struct pd_state *s = pd_context();
    u32 n = s->length;
    if (n + 1 < MESSAGE_CAP) {
        s->message[n] = (char)ch;
        s->length = n + 1;
        s->message[n + 1] = 0;
    }
}

__attribute__((noinline)) void pd_capture(uptr options, uptr caller, const char *fmt,
                                         const uptr *args, uptr fp, uptr stack_low) {
    struct pd_state *s = pd_context();
    /* No waiting: another/nested entry keeps the first record and returns. */
    if (__atomic_exchange_n(&s->busy, 1, __ATOMIC_RELAXED)) return;
    s->magic = PD_MAGIC;
    s->stage = 1;
    s->slide = (uptr)s - PD_STATE_VA;
    s->caller = caller;
    s->options = options;
    s->frame_count = 0;
    s->length = 0;
    if (fmt) for (u32 i = 0; i + 1 < MESSAGE_CAP && fmt[i]; ++i) capture_character((u8)fmt[i]);
    /* Render the literal before invoking the native formatter. If a bad %s
     * argument faults, the first entry marker can still have been drawn. */
    pd_render();
    s->stage = 2;
    if (fmt && args) {
        uptr copy = *args;
        s->length = 0;
        s->message[0] = 0;
        pd_doprnt(fmt, &copy, capture_character, 0);
    }
    /* Limit the walk to the current 16 KiB page: no speculative reads beyond
     * the current stack page/into a possible stack guard. */
    uptr stack_end = (stack_low & ~(uptr)0x3fff) + 0x4000;
    for (u32 i = 0; i < 12 && !(fp & 15) && fp >= stack_low && fp <= stack_end - 16; ++i) {
        const uptr *frame = (const uptr *)fp;
        uptr next = frame[0], lr = frame[1];
        s->frames[s->frame_count++] = lr;
        if (next <= fp) break;
        fp = next;
    }
    s->stage = 3;
    pd_render();
}
