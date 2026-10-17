#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* One finite, continuous epoch. No network, programming or bridge changes.
 * Root must admit the matching FPGA/Linux before MMIO. An outer60s timeout
 * bounds a blocked bus, which the in-process deadline cannot interrupt. */
enum { MAGIC=0, ABI=4, STATUS=8, FAULT=12, COMMAND=16, THRLO=20,
 THRHI=24, SPARSE=28, PCM=32, ACCEPTED=36, EPOCH=40, WLEVEL=48,
 YLEVEL=52, ILEVEL=56, IFREE=60, WDATA=64, YDATA=68, YCOUNT=72,
 CYCLES=76, DROPS=80, EMITTED=84, INPUTS=88, NS=92, WBYTES=96,
 WREAD=100, YREAD=104, NY=108, FRAMES=112, ICAP=116, WCAP=120,
 YCAP=124, SOURCE=128, SAMPLES=384000, OUTPUTS=384512,
 FRAMECOUNT=3001, MAXWIRE=3241080 };
typedef struct { uint32_t (*read)(void *,unsigned); void (*write)(void *,unsigned,uint32_t);
 uint64_t (*now)(void *); void (*idle)(void *); void *context; } Bus;
typedef struct { uint8_t *wire; int32_t *y; uint32_t bytes,ycount,cycles,iterations; uint64_t epoch; } Result;
static const char *error_text="invalid arguments";
#define NEED(v,s) do { if(!(v)){error_text=(s);return false;} } while(0)
static uint64_t epoch(Bus *b) { for(unsigned n=0;n<8;n++){uint32_t h1=b->read(b->context,EPOCH+4),l=b->read(b->context,EPOCH),h2=b->read(b->context,EPOCH+4);if(h1==h2)return (uint64_t)h1<<32|l;}return UINT64_MAX; }
static unsigned minimum(unsigned a,unsigned b){return a<b?a:b;}
static bool run(Bus *b,const int32_t *input,uint64_t threshold,uint32_t sparse,const uint32_t source[8],Result *r) {
 NEED(threshold<(1ULL<<56)&&sparse<=1,"configuration range");
 for(unsigned i=0;i<SAMPLES;i++)NEED(input[i]>=-2048&&input[i]<=2047,"input range");
 NEED(b->read(b->context,MAGIC)==0x54534832&&b->read(b->context,ABI)==0x20000,"TSH2 identity");
 for(unsigned i=0;i<8;i++)NEED(b->read(b->context,SOURCE+4*i)==source[i],"SOURCE_ID mismatch");
 NEED(b->read(b->context,NS)==SAMPLES&&b->read(b->context,NY)==OUTPUTS&&b->read(b->context,FRAMES)==FRAMECOUNT,"geometry");
 NEED(b->read(b->context,ICAP)==256&&b->read(b->context,WCAP)==1024&&b->read(b->context,YCAP)==1024,"FIFO geometry");
 uint64_t before=epoch(b);NEED(before!=UINT64_MAX,"epoch exhausted");
 b->write(b->context,COMMAND,1);uint64_t start=b->now(b->context);bool clear=false;
 for(unsigned n=0;n<10000;n++){if(b->read(b->context,STATUS)==0){clear=true;break;}NEED(b->now(b->context)-start<1000000000ULL,"clear timeout");b->idle(b->context);}
 NEED(clear&&!b->read(b->context,FAULT)&&epoch(b)==before,"clear state");
 NEED(!b->read(b->context,ACCEPTED)&&!b->read(b->context,WLEVEL)&&!b->read(b->context,YLEVEL),"clear counts");
 b->write(b->context,THRLO,(uint32_t)threshold);b->write(b->context,THRHI,(uint32_t)(threshold>>32));b->write(b->context,SPARSE,sparse);
 NEED(b->read(b->context,THRLO)==(uint32_t)threshold&&b->read(b->context,THRHI)==threshold>>32&&b->read(b->context,SPARSE)==sparse,"config readback");
 b->write(b->context,COMMAND,2);r->epoch=epoch(b);NEED(r->epoch==before+1,"accepted epoch mismatch");
 start=b->now(b->context);unsigned sent=0;r->bytes=0;r->ycount=0;bool finished=false;
 for(r->iterations=0;r->iterations<2000000;r->iterations++) {
   NEED(b->now(b->context)-start<45000000000ULL,"stream45s deadline");
   uint32_t status=b->read(b->context,STATUS);NEED(!(status&~63u)&&!(status&4)&&!b->read(b->context,FAULT),"device fault/status");
   NEED((status&3)==1||(status&3)==2,"run state");
   uint32_t wl=b->read(b->context,WLEVEL),yl=b->read(b->context,YLEVEL);
   NEED(wl<=1024&&yl<=1024,"output FIFO bounds");unsigned progress=0;
   for(unsigned i=0,n=minimum(wl,64);i<n;i++) {
     NEED(r->bytes<=MAXWIRE-4,"spectral bounds");uint32_t w=b->read(b->context,WDATA);
     for(unsigned k=0;k<4;k++){r->wire[r->bytes++]=(uint8_t)(w>>(8*k));}progress++;
   }
   for(unsigned i=0,n=minimum(yl,64);i<n;i++) {
     NEED(r->ycount<OUTPUTS,"Y bounds");uint32_t y=b->read(b->context,YDATA);
     NEED(y<=2047||y>=0xfffff800u,"Y sign extension");r->y[r->ycount++]=(int32_t)y;progress++;
   }
   if(sent<SAMPLES&&(status&8)) {
     uint32_t free=b->read(b->context,IFREE);NEED(free<=256,"PCM FIFO bounds");
     for(unsigned i=0,n=minimum(minimum(free,64),SAMPLES-sent);i<n;i++){b->write(b->context,PCM,(uint32_t)input[sent++]);progress++;}
   }
   if((status&2)&&!wl&&!yl){finished=true;break;}
   if(!progress)b->idle(b->context);
 }
 NEED(finished,"stream iteration limit");
 NEED(sent==SAMPLES&&b->read(b->context,ACCEPTED)==SAMPLES&&b->read(b->context,INPUTS)==SAMPLES,"input totals");
 NEED(r->ycount==OUTPUTS&&b->read(b->context,YCOUNT)==OUTPUTS&&b->read(b->context,YREAD)==OUTPUTS,"Y totals");
 NEED(r->bytes>=48*FRAMECOUNT&&r->bytes%8==0&&b->read(b->context,WBYTES)==r->bytes&&b->read(b->context,WREAD)==r->bytes/4,"spectral totals");
 NEED(!b->read(b->context,DROPS)&&b->read(b->context,EMITTED)==FRAMECOUNT,"frame totals/drop");
 r->cycles=b->read(b->context,CYCLES);NEED(r->cycles>0&&r->cycles<=3000000000u,"cycle/watchdog count");
 NEED(b->read(b->context,STATUS)==2&&!b->read(b->context,FAULT)&&epoch(b)==r->epoch,"final identity/state");return true;
}
typedef struct { volatile uint32_t *p; } Mapping;
static uint32_t physical_read(void *v,unsigned a){Mapping *m=v;__sync_synchronize();uint32_t x=m->p[a/4];__sync_synchronize();return x;}
static void physical_write(void *v,unsigned a,uint32_t x){Mapping *m=v;__sync_synchronize();m->p[a/4]=x;__sync_synchronize();}
static uint64_t physical_now(void *v){(void)v;struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))_exit(2);return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
static void physical_idle(void *v){(void)v;struct timespec t={0,50000};nanosleep(&t,NULL);}
static bool number(const char *s,uint64_t max,uint64_t *value){NEED(s&&*s&&*s!='-',"number required");char *end;errno=0;unsigned long long n=strtoull(s,&end,0);NEED(!errno&&!*end&&n<=max,"number range");*value=n;return true;}
static bool source_parse(const char *s,uint32_t words[8]){NEED(s&&strlen(s)==64,"source must be64 hex characters");for(unsigned i=0;i<64;i++)NEED((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f'),"lowercase source hex required");for(unsigned i=0;i<8;i++){char part[9];memcpy(part,s+56-8*i,8);part[8]=0;words[i]=(uint32_t)strtoul(part,NULL,16);}return true;}
static bool read_input(const char *path,int32_t *input){FILE *f=fopen(path,"rb");NEED(f,"open input");for(unsigned i=0;i<SAMPLES;i++){uint8_t bytes[4];if(fread(bytes,1,4,f)!=4){fclose(f);NEED(false,"short input");}uint32_t v=0;for(unsigned k=0;k<4;k++)v|=(uint32_t)bytes[k]<<(8*k);input[i]=(int32_t)v;if(input[i]<-2048||input[i]>2047){fclose(f);NEED(false,"input range");}}bool ok=fgetc(f)==EOF&&!ferror(f);fclose(f);NEED(ok,"trailing input");return true;}
static bool boot_check(const char *expected){NEED(expected&&strlen(expected)==36,"boot id required");FILE *f=fopen("/proc/sys/kernel/random/boot_id","r");NEED(f,"open boot id");char got[80];bool ok=fgets(got,sizeof got,f)!=NULL;fclose(f);NEED(ok,"read boot id");got[strcspn(got,"\r\n")]=0;NEED(strcmp(got,expected)==0,"boot identity mismatch");return true;}
static bool save(const char *prefix,const Result *r,const char *source,const char *boot,uint64_t threshold,unsigned sparse){
 char name[4096];NEED(strlen(prefix)<sizeof name-20,"output prefix length");
 snprintf(name,sizeof name,"%s.tsp1",prefix);FILE *f=fopen(name,"wbx");NEED(f,"fresh TSP1 output");bool ok=fwrite(r->wire,1,r->bytes,f)==r->bytes;if(fclose(f))ok=false;NEED(ok,"write TSP1");
 snprintf(name,sizeof name,"%s.y.i32le",prefix);f=fopen(name,"wbx");NEED(f,"fresh Y output");
 ok=true;for(unsigned i=0;i<r->ycount;i++){uint8_t y[4];for(unsigned k=0;k<4;k++)y[k]=(uint8_t)((uint32_t)r->y[i]>>(8*k));if(fwrite(y,1,4,f)!=4){ok=false;break;}}if(fclose(f))ok=false;NEED(ok,"write Y");
 snprintf(name,sizeof name,"%s.json",prefix);f=fopen(name,"wx");NEED(f,"fresh receipt");
 int n=fprintf(f,"{\"schema\":\"tsh2-stream-client-v1\",\"status\":\"CAPTURED_PENDING_PC_VALIDATION\",\"source_id\":\"%s\",\"boot_id\":\"%s\",\"threshold\":%"PRIu64",\"sparse\":%u,\"epoch\":%"PRIu64",\"input_count\":384000,\"y_count\":384512,\"frames\":3001,\"drops\":0,\"bytes\":%u,\"fabric_cycles_including_host_stalls\":%u,\"poll_iterations\":%u,\"performance_comparison\":false}\n",source,boot,threshold,sparse,r->epoch,r->bytes,r->cycles,r->iterations);ok=n>0;if(fclose(f))ok=false;NEED(ok,"write receipt");return true;
}
/* Mock advances only upon PCM writes; both outputs must be interleaved or
 * overflow is detected. High-bit epochs and spectral words exercise packing. */
typedef struct {uint32_t accepted,lo,hi,sparse,wr,yr,words,ys;uint64_t epoch,now;unsigned writes,mode;bool active,overflow;} Mock;
static uint32_t mock_read(void *p,unsigned a){Mock*m=p;
 unsigned free=minimum(256,(1024-(m->words-m->wr))/2);
 if(a==MAGIC)return m->mode==1?0:0x54534832;
 if(a==ABI)return 0x20000;
 if(a>=SOURCE&&a<SOURCE+32)return m->mode==2?1:0;
 if(a==NS)return SAMPLES;
 if(a==NY)return OUTPUTS;
 if(a==FRAMES)return FRAMECOUNT;
 if(a==ICAP)return m->mode==10?128:256;
 if(a==WCAP||a==YCAP)return 1024;
 if(a==EPOCH)return (uint32_t)m->epoch;
 if(a==EPOCH+4)return (uint32_t)(m->epoch>>32);
 if(a==THRLO)return m->lo;
 if(a==THRHI)return m->hi;
 if(a==SPARSE)return m->sparse;
 if(a==FAULT)return m->overflow||(m->active&&m->mode==4);
 if(a==STATUS)return !m->active?0:(m->accepted==SAMPLES?2:1|((m->mode==3||!free)?0:8))|(m->words>m->wr?16:0)|(m->ys>m->yr?32:0);
 if(a==WLEVEL)return m->mode==11&&m->accepted<SAMPLES&&(m->now/100000)%4==0?0:m->words-m->wr;
 if(a==YLEVEL)return m->mode==11&&m->accepted<SAMPLES&&(m->now/100000)%4==0?0:m->ys-m->yr;
 if(a==IFREE)return m->mode==9?257:free;
 if(a==ACCEPTED||a==INPUTS)return m->accepted;
 if(a==WDATA){if(m->wr==m->words)m->overflow=true;return 0x80000000u^(m->wr++*1234567u);}
 if(a==YDATA){if(m->yr==m->ys)m->overflow=true;unsigned i=m->yr++;return m->mode==5?0xfff:(uint32_t)(int32_t)((int)(i%4096)-2048);}
 if(a==YCOUNT)return m->ys+(m->mode==6);
 if(a==YREAD)return m->yr;
 if(a==WBYTES)return m->words*4;
 if(a==WREAD)return m->wr;
 if(a==DROPS)return m->mode==7;
 if(a==EMITTED)return FRAMECOUNT;
 if(a==CYCLES)return 30000000;
 return 0;
}
static void mock_write(void*p,unsigned a,uint32_t x){Mock*m=p;m->writes++;
 if(a==COMMAND){if(x==1){m->accepted=m->wr=m->yr=m->words=m->ys=0;m->active=false;m->overflow=false;}else{m->active=true;m->epoch+=m->mode==8?2:1;}}
 else if(a==THRLO)m->lo=x;else if(a==THRHI)m->hi=x;else if(a==SPARSE)m->sparse=x;
 else if(a==PCM){if(!m->active||m->accepted>=SAMPLES)m->overflow=true;m->accepted++;m->words+=2;m->ys++;if(m->accepted==SAMPLES)m->ys+=512;if(m->words-m->wr>1024||m->ys-m->yr>1024)m->overflow=true;}
}
static uint64_t mock_now(void*p){Mock*m=p;return m->now+=100000ULL;}
static void mock_idle(void*p){Mock*m=p;if(m->mode==3)m->now+=1000000000ULL;}
static int self_test(void){int32_t*in=calloc(SAMPLES,sizeof *in);Result r={.wire=malloc(MAXWIRE),.y=malloc(OUTPUTS*sizeof(int32_t))};if(!in||!r.wire||!r.y)return 2;uint32_t source[8]={0};
 for(unsigned mode=0;mode<=11;mode++){Mock m={.mode=mode,.epoch=0xfedcba9880000000ULL};Bus b={mock_read,mock_write,mock_now,mock_idle,&m};bool ok=run(&b,in,100000000000ULL,1,source,&r);if(ok!=(mode==0||mode==11)||((mode==1||mode==2||mode==10)&&m.writes)){fprintf(stderr,"mock%u mismatch:%s\n",mode,error_text);return 2;}if(ok){if(r.bytes!=SAMPLES*8||r.epoch!=0xfedcba9880000001ULL||r.ycount!=OUTPUTS)return 2;for(unsigned i=0;i<OUTPUTS;i++)if(r.y[i]!=(int)(i%4096)-2048)return 2;for(unsigned i=0;i<r.bytes/4;i++){uint32_t w=0x80000000u^(i*1234567u);for(unsigned k=0;k<4;k++)if(r.wire[4*i+k]!=(uint8_t)(w>>(8*k)))return 2;}}}
 Mock m={0};Bus b={mock_read,mock_write,mock_now,mock_idle,&m};in[0]=2048;if(run(&b,in,0,0,source,&r)||m.writes)return 2;
 free(in);free(r.wire);free(r.y);puts("{\"status\":\"PASS_OFFBOARD_REGISTER_MOCK\",\"tests\":13,\"hardware_access\":false,\"full_stream_samples\":384000}");return 0;
}
int main(int argc,char**argv){
 if(argc==2&&!strcmp(argv[1],"--self-test"))return self_test();
 if(argc==2&&!strcmp(argv[1],"--help")){puts("--execute-hardware --input FILE --threshold INTEGER --sparse 0|1 --source HEX64 --boot-id UUID --out-prefix FRESH");return 0;}
 const char*inputpath=NULL,*source=NULL,*boot=NULL,*prefix=NULL;uint64_t threshold=0,sparse=2;bool execute=false,gotthreshold=false;
 for(int i=1;i<argc;i++){const char*k=argv[i];if(!strcmp(k,"--execute-hardware")){if(execute)goto fail;execute=true;continue;}if(++i>=argc)goto fail;const char*v=argv[i];if(!strcmp(k,"--input")&&!inputpath)inputpath=v;else if(!strcmp(k,"--source")&&!source)source=v;else if(!strcmp(k,"--boot-id")&&!boot)boot=v;else if(!strcmp(k,"--out-prefix")&&!prefix)prefix=v;else if(!strcmp(k,"--threshold")&&!gotthreshold){gotthreshold=true;if(!number(v,(1ULL<<56)-1,&threshold))goto fail;}else if(!strcmp(k,"--sparse")&&sparse==2){if(!number(v,1,&sparse))goto fail;}else goto fail;}
 if(!execute||!inputpath||!prefix||!gotthreshold||sparse>1)goto fail;
 uint32_t words[8];int32_t*input=malloc(SAMPLES*sizeof *input);Result result={.wire=malloc(MAXWIRE),.y=malloc(OUTPUTS*sizeof(int32_t))};
 if(!input||!result.wire||!result.y||!source_parse(source,words)||!read_input(inputpath,input)||!boot_check(boot))goto fail;
 char file[4096];const char*suffixes[]={".tsp1",".y.i32le",".json"};if(strlen(prefix)>sizeof file-20)goto fail;for(unsigned i=0;i<3;i++){snprintf(file,sizeof file,"%s%s",prefix,suffixes[i]);if(access(file,F_OK)==0){error_text="output exists";goto fail;}}
 int fd=open("/dev/mem",O_RDWR|O_SYNC|O_CLOEXEC);if(fd<0){error_text="open /dev/mem";goto fail;}if(flock(fd,LOCK_EX|LOCK_NB)){close(fd);error_text="exclusive device lock";goto fail;}
 void*address=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,(off_t)0xff200000ULL);if(address==MAP_FAILED){close(fd);error_text="map aperture";goto fail;}
 Mapping map={address};Bus b={physical_read,physical_write,physical_now,physical_idle,&map};bool ok=run(&b,input,threshold,(uint32_t)sparse,words,&result);
 munmap(address,4096);close(fd); /* No automatic MMIO abort after a fault. */
 if(!ok||!boot_check(boot)||!save(prefix,&result,source,boot,threshold,(unsigned)sparse))goto fail;
 free(input);free(result.wire);free(result.y);puts("CAPTURED_PENDING_PC_VALIDATION");return 0;
fail:fprintf(stderr,"TSH2 rejected: %s\n",error_text);return 2;
}
