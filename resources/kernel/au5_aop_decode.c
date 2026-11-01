/* AU5: complete only AOP firmware loading under the inherited -f policy.
 * No firmware replacement, no authentication-success claim for other clients.
 * ARM64/PIC: external calls are relative branches in the companion assembly.
 */
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long usize;
extern const void *au5_bytes(const void *);
extern u32 au5_length(const void *);
extern void *au5_copy(const void *,u32);
extern void au5_complete(void *,void *,u32);
extern int au5_printf(const char *,...);

/* Definite DER only. Check remaining length before every read/addition. */
static int item(const u8 **p,const u8 *end,u8 tag,const u8 **body,usize *len){
    if((usize)(end-*p)<2 || *(*p)++!=tag) return 0;
    usize n=*(*p)++;
    if(n&128){
        unsigned count=n&127;
        if(!count || count>4 || (usize)(end-*p)<count || !**p) return 0;
        n=0;
        for(unsigned i=0;i<count;i++) n=(n<<8)|*(*p)++;
        if(n<128) return 0;
    }
    if(n>(usize)(end-*p)) return 0;
    *body=*p;*len=n;*p+=n;
    return 1;
}
static int fourcc(const u8 **p,const u8 *end,u32 expected){
    const u8 *s;usize n;
    return item(p,end,22,&s,&n) && n==4 &&
        (((u32)s[0]<<24)|((u32)s[1]<<16)|((u32)s[2]<<8)|s[3])==expected;
}
__attribute__((visibility("default")))
const u8 *au5_payload(const u8 *p,usize size,u32 *length){
    if(!p || !length || size<16 || size>8*1024*1024) return 0;
    const u8 *end=p+size,*body,*first;usize n;
    if(!item(&p,end,48,&body,&n) || p!=end) return 0;
    p=body;end=body+n;first=p;
    if(fourcc(&p,end,0x494d4734)){ /* IMG4 wrapper, or a bare IM4P below */
        if(!item(&p,end,48,&body,&n)) return 0;
        p=body;end=body+n;
    }else p=first;
    if(!fourcc(&p,end,0x494d3450) || !fourcc(&p,end,0x616f7066)) return 0;
    if(!item(&p,end,22,&body,&n)) return 0; /* description */
    if(!item(&p,end,4,&body,&n) || n<4 || n>4*1024*1024) return 0;
    /* Only this device's uncompressed OSSerializeBinary AOP bundle is supported.
     * Reject compressed or different formats instead of passing a wrong object.
     */
    if(body[0]!=0xd3 || body[1] || body[2] || body[3]) return 0;
    *length=(u32)n;return body;
}
__attribute__((visibility("default")))
u32 au5_entry(u8 *self){
    if(*(u32 *)(self+0xf8)!=0x616f7066) return 0; /* preserve -f for other tags */
    const void *original=*(const void **)(self+0xe8);
    if(!original) return 0xe00002bc;
    u32 n=0;
    const u8 *payload=au5_payload(au5_bytes(original),au5_length(original),&n);
    if(!payload){au5_printf("\033[35mAU5 AOP: unsupported IMG4 payload\033[0m\n");return 0xe00002bc;}
    void *data=au5_copy(payload,n);
    if(!data){au5_printf("\033[35mAU5 AOP: allocation failed\033[0m\n");return 0xe00002bd;}
    /* This routine stores owned OSData at +f0, sets completed/valid flags and
     * the completion timestamp. Native loadFirmware later calls the client
     * with status=0 and releases both original/copy after the callback.
     */
    au5_complete(self,data,0);
    au5_printf("\033[35mAU5 AOP: decoded %u bytes; completion submitted\033[0m\n",n);
    return 0;
}
