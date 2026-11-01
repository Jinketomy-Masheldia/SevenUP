/* HC3 keeps command snapshots as diagnostic OSData properties on the interface. */
#include <stdint.h>
#include <stddef.h>
typedef uintptr_t U;
extern const char *hc2_name(const void *, const void *);
extern int hc2_printf(const char *, ...);
extern unsigned char hc2_property(void *,const char *,void *,unsigned);
extern U hc2_original_short(U,U,U,U,U,U,U,U);
extern U hc2_original_long(U,U,U,U,U,U,U,U);
struct Record {
    uint32_t schema,api,command,captured;
    uint64_t length,result;
    unsigned char before[16],after[16];
};
_Static_assert(sizeof(struct Record)==64,"fixed diagnostic record size");
static int equal(const char *a,const char *b) {
    if(!a)return 0;
    while(*a&&*a==*b){a++;b++;}
    return *a==*b;
}
U observe(unsigned api,U a,U b,U c,U d,U e,U f,U g,U h) {
    const char *name=hc2_name((void*)a,0);
    int selected=equal(name,"aop-button")||equal(name,"turtle");
    struct Record rec={0};
    if(selected) {
        rec.schema=1;rec.api=api;rec.command=(uint32_t)b;rec.length=d;
        rec.captured=c?(d>16?16:(uint32_t)d):0;
        for(unsigned i=0;i<rec.captured;i++)rec.before[i]=((unsigned char*)c)[i];
    }
    U result=api?hc2_original_long(a,b,c,d,e,f,g,h):hc2_original_short(a,b,c,d,e,f,g,h);
    if(selected) {
        rec.result=result;
        for(unsigned i=0;i<rec.captured;i++)rec.after[i]=((unsigned char*)c)[i];
        char key[]="HC3Log_0_00000000";
        const char hex[]="0123456789abcdef";
        key[7]=(char)('0'+api);
        for(unsigned i=0;i<8;i++)key[9+i]=hex[(rec.command>>(28-i*4))&15];
        unsigned ok=hc2_property((void*)a,key,&rec,sizeof(rec));
        hc2_printf("\x1b[33mHC3 %s api=%u cmd=%x len=%llu result=%llx saved=%u\x1b[0m\n",
                   name,api,(unsigned)b,(unsigned long long)d,(unsigned long long)result,ok);
    }
    return result;
}
U hc2_short(U a,U b,U c,U d,U e,U f,U g,U h){return observe(0,a,b,c,d,e,f,g,h);}
U hc2_long(U a,U b,U c,U d,U e,U f,U g,U h){return observe(1,a,b,c,d,e,f,g,h);}
