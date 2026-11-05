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

/* The parent must admit bridge/reset/boot/source identity before invocation.
 * This client only transports raw CU8 and captures results. It performs no DSP.
 * An outer timeout is required because a hung physical MMIO cannot be timed out
 * by an in-process software deadline. No automatic recovery writes on failure. */
enum { MAGIC=0, ABI=4, STATUS=8, FAULT=12, COMMAND=16, THRLO=20,
 THRHI=24, SPARSE=28, IQ=32, ACCEPTED=36, EPOCH=40, WLEVEL=48,
 YLEVEL=52, ILEVEL=56, IFREE=60, WDATA=64, YDATA=68, YCOUNT=72,
 CYCLES=76, DROPS=80, EMITTED=84, INPUTS=88, NS=92, WBYTES=96,
 WREAD=100, YREAD=104, NY=108, FRAMES=112, ICAP=116, WCAP=120,
 YCAP=124, SOURCE=128, PAIRS=160, GAIN=164, RFOUTPUTS=168,
 RFINPUTS=172, CLIPS=176, RFSTATUS=180, VALID=184,
 SAMPLES=384000, OUTPUTS=384512, MAXPAIRS=96000,
 FRAMECOUNT=3001, MAXWIRE=3241080 };
typedef struct { uint32_t (*read)(void *,unsigned); void (*write)(void *,unsigned,uint32_t);
 uint64_t (*now)(void *); void (*idle)(void *); void *context; } Bus;
typedef struct { uint8_t *wire; int32_t *y; uint32_t bytes,ycount,cycles,iterations;
 uint32_t pairs,gain,clips,rf_status,rf_input_count,rf_output_count,valid_samples;
 uint64_t epoch; } Result;
static const char *error_text="invalid arguments";
#define NEED(v,s) do { if(!(v)){error_text=(s);return false;} } while(0)
static unsigned minimum(unsigned a,unsigned b){return a<b?a:b;}
static uint64_t epoch(Bus *b){
 for(unsigned n=0;n<8;n++){uint32_t h1=b->read(b->context,EPOCH+4),l=b->read(b->context,EPOCH),h2=b->read(b->context,EPOCH+4);if(h1==h2)return (uint64_t)h1<<32|l;}return UINT64_MAX;
}
static bool run(Bus *b,const uint8_t *input,unsigned pairs,unsigned gain,
                uint64_t threshold,unsigned sparse,const uint32_t source[8],Result *r){
 NEED(input&&pairs>=1&&pairs<=MAXPAIRS&&gain<=3&&threshold<(1ULL<<56)&&sparse<=1,"configuration range");
 NEED(b->read(b->context,MAGIC)==0x54524631&&b->read(b->context,ABI)==0x10000,"TRF1 identity");
 for(unsigned i=0;i<8;i++)NEED(b->read(b->context,SOURCE+4*i)==source[i],"SOURCE_ID mismatch");
 NEED(b->read(b->context,NS)==SAMPLES&&b->read(b->context,NY)==OUTPUTS&&b->read(b->context,FRAMES)==FRAMECOUNT,"geometry");
 NEED(b->read(b->context,ICAP)==256&&b->read(b->context,WCAP)==1024&&b->read(b->context,YCAP)==1024,"FIFO geometry");
 uint32_t initial=b->read(b->context,STATUS);NEED(!(initial&~63u)&&!(initial&1),"device already busy");
 uint64_t before=epoch(b);NEED(before!=UINT64_MAX,"epoch exhausted");
 b->write(b->context,COMMAND,1);uint64_t start=b->now(b->context);bool clear=false;
 for(unsigned n=0;n<10000;n++){
   if(b->read(b->context,STATUS)==0){clear=true;break;}
   NEED(b->now(b->context)-start<1000000000ULL,"clear timeout");b->idle(b->context);
 }
 NEED(clear&&!b->read(b->context,FAULT)&&epoch(b)==before,"clear state");
 NEED(!b->read(b->context,ACCEPTED)&&!b->read(b->context,WLEVEL)&&!b->read(b->context,YLEVEL)&&
      !b->read(b->context,RFOUTPUTS)&&!b->read(b->context,RFINPUTS)&&!b->read(b->context,CLIPS)&&!b->read(b->context,RFSTATUS),"clear counts");
 b->write(b->context,THRLO,(uint32_t)threshold);b->write(b->context,THRHI,(uint32_t)(threshold>>32));
 b->write(b->context,SPARSE,sparse);b->write(b->context,PAIRS,pairs);b->write(b->context,GAIN,gain);
 NEED(b->read(b->context,THRLO)==(uint32_t)threshold&&b->read(b->context,THRHI)==threshold>>32&&
      b->read(b->context,SPARSE)==sparse&&b->read(b->context,PAIRS)==pairs&&b->read(b->context,GAIN)==gain,"config readback");
 b->write(b->context,COMMAND,2);r->epoch=epoch(b);NEED(r->epoch==before+1,"accepted epoch mismatch");
 start=b->now(b->context);unsigned sent=0;r->bytes=0;r->ycount=0;bool finished=false;
 for(r->iterations=0;r->iterations<2000000;r->iterations++){
   NEED(b->now(b->context)-start<45000000000ULL,"stream45s deadline");
   uint32_t status=b->read(b->context,STATUS);
   NEED(!(status&~63u)&&!(status&4)&&!b->read(b->context,FAULT),"device fault/status");
   NEED((status&3)==1||(status&3)==2,"run state");
   uint32_t rf=b->read(b->context,RFSTATUS);NEED(!(rf&~15u)&&!(rf&8),"RF fault/status");
   uint32_t wl=b->read(b->context,WLEVEL),yl=b->read(b->context,YLEVEL);
   NEED(wl<=1024&&yl<=1024,"output FIFO bounds");unsigned progress=0;
   for(unsigned i=0,n=minimum(wl,64);i<n;i++){
     NEED(r->bytes<=MAXWIRE-4,"spectral bounds");uint32_t w=b->read(b->context,WDATA);
     for(unsigned k=0;k<4;k++)r->wire[r->bytes++]=(uint8_t)(w>>(8*k));
     progress++;
   }
   for(unsigned i=0,n=minimum(yl,64);i<n;i++){
     NEED(r->ycount<OUTPUTS,"Y bounds");uint32_t y=b->read(b->context,YDATA);
     NEED(y<=2047||y>=0xfffff800u,"Y sign extension");r->y[r->ycount++]=(int32_t)y;progress++;
   }
   if(sent<pairs&&(status&8)){
     uint32_t free=b->read(b->context,IFREE);NEED(free<=256,"IQ FIFO bounds");
     for(unsigned i=0,n=minimum(minimum(free,64),pairs-sent);i<n;i++){
       uint32_t word=(uint32_t)input[2*sent]|(uint32_t)input[2*sent+1]<<8;
       b->write(b->context,IQ,word);sent++;progress++;
     }
   }
   if((status&2)&&!wl&&!yl){finished=true;break;}
   if(!progress)b->idle(b->context);
 }
 NEED(finished,"stream iteration limit");
 NEED(sent==pairs&&b->read(b->context,ACCEPTED)==pairs&&b->read(b->context,INPUTS)==SAMPLES,"input totals");
 NEED(r->ycount==OUTPUTS&&b->read(b->context,YCOUNT)==OUTPUTS&&b->read(b->context,YREAD)==OUTPUTS,"Y totals");
 NEED(r->bytes>=48*FRAMECOUNT&&r->bytes%8==0&&b->read(b->context,WBYTES)==r->bytes&&b->read(b->context,WREAD)==r->bytes/4,"spectral totals");
 NEED(!b->read(b->context,DROPS)&&b->read(b->context,EMITTED)==FRAMECOUNT,"frame totals/drop");
 r->pairs=pairs;r->gain=gain;r->clips=b->read(b->context,CLIPS);r->rf_status=b->read(b->context,RFSTATUS);
 r->rf_input_count=b->read(b->context,RFINPUTS);r->rf_output_count=b->read(b->context,RFOUTPUTS);r->valid_samples=b->read(b->context,VALID);
 NEED(r->rf_input_count==pairs&&r->rf_output_count==pairs*4&&r->valid_samples==pairs*4,"RF input/output totals");
 NEED(r->clips<=pairs*4&&r->rf_status==(2u|(r->clips?4u:0u)),"RF final status/clipping consistency");
 NEED(gain>1||r->clips==0,"unexpected clipping at guaranteed-headroom gain");
 NEED(b->read(b->context,PAIRS)==pairs&&b->read(b->context,GAIN)==gain,"RF final configuration");
 r->cycles=b->read(b->context,CYCLES);NEED(r->cycles>0&&r->cycles<=3000000000u,"cycle/watchdog count");
 NEED(b->read(b->context,STATUS)==2&&!b->read(b->context,FAULT)&&epoch(b)==r->epoch,"final identity/state");
 return true;
}

typedef struct {volatile uint32_t *p;} Mapping;
static uint32_t physical_read(void *v,unsigned a){Mapping*m=v;__sync_synchronize();uint32_t x=m->p[a/4];__sync_synchronize();return x;}
static void physical_write(void*v,unsigned a,uint32_t x){Mapping*m=v;__sync_synchronize();m->p[a/4]=x;__sync_synchronize();}
static uint64_t physical_now(void*v){(void)v;struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))_exit(2);return(uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
static void physical_idle(void*v){(void)v;struct timespec t={0,50000};nanosleep(&t,NULL);}
static bool number(const char*s,uint64_t max,uint64_t*value){NEED(s&&*s&&*s!='-',"number required");char*end;errno=0;unsigned long long n=strtoull(s,&end,0);NEED(!errno&&!*end&&n<=max,"number range");*value=n;return true;}
static bool source_parse(const char*s,uint32_t words[8]){NEED(s&&strlen(s)==64,"source must be64 hex characters");for(unsigned i=0;i<64;i++)NEED((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f'),"lowercase source hex required");for(unsigned i=0;i<8;i++){char part[9];memcpy(part,s+56-8*i,8);part[8]=0;words[i]=(uint32_t)strtoul(part,NULL,16);}return true;}
static bool read_input(const char*path,uint8_t*input,unsigned*pairs){
 FILE*f=fopen(path,"rb");NEED(f,"open input");struct stat st;
 if(fstat(fileno(f),&st)||!S_ISREG(st.st_mode)||st.st_size<2||st.st_size>MAXPAIRS*2||st.st_size%2){fclose(f);NEED(false,"CU8 length must be even and between2 and192000 bytes");}
 size_t n=(size_t)st.st_size;bool ok=fread(input,1,n,f)==n&&fgetc(f)==EOF&&!ferror(f);
 if(fclose(f))ok=false;
 NEED(ok,"read exact CU8 file");*pairs=(unsigned)n/2;return true;
}
static bool boot_check(const char*expected){NEED(expected&&strlen(expected)==36,"boot id required");FILE*f=fopen("/proc/sys/kernel/random/boot_id","r");NEED(f,"open boot id");char got[80];bool ok=fgets(got,sizeof got,f)!=NULL;fclose(f);NEED(ok,"read boot id");got[strcspn(got,"\r\n")]=0;NEED(!strcmp(got,expected),"boot identity mismatch");return true;}
static bool save(const char*prefix,const Result*r,const char*source,const char*boot,uint64_t threshold,unsigned sparse){
 char name[4096];NEED(strlen(prefix)<sizeof name-20,"output prefix length");
 snprintf(name,sizeof name,"%s.tsp1",prefix);FILE*f=fopen(name,"wbx");NEED(f,"fresh TSP1 output");bool ok=fwrite(r->wire,1,r->bytes,f)==r->bytes;if(fclose(f))ok=false;NEED(ok,"write TSP1");
 snprintf(name,sizeof name,"%s.y.i32le",prefix);f=fopen(name,"wbx");NEED(f,"fresh Y output");ok=true;
 for(unsigned i=0;i<r->ycount;i++){uint8_t y[4];for(unsigned k=0;k<4;k++)y[k]=(uint8_t)((uint32_t)r->y[i]>>(8*k));if(fwrite(y,1,4,f)!=4){ok=false;break;}}if(fclose(f))ok=false;NEED(ok,"write Y");
 snprintf(name,sizeof name,"%s.json",prefix);f=fopen(name,"wx");NEED(f,"fresh receipt");
 int n=fprintf(f,"{\"schema\":\"trf1-file-client-v1\",\"status\":\"CAPTURED_PENDING_PC_VALIDATION\",\"input_format\":\"CU8_I_then_Q\",\"source_id\":\"%s\",\"boot_id\":\"%s\",\"threshold\":%"PRIu64",\"sparse\":%u,\"epoch\":%"PRIu64",\"pair_count\":%u,\"input_bytes\":%u,\"gain_shift\":%u,\"valid_rf_samples\":%u,\"rf_input_count\":%u,\"rf_output_count\":%u,\"clip_count\":%u,\"rf_status\":%u,\"input_count\":384000,\"y_count\":384512,\"frames\":3001,\"drops\":0,\"bytes\":%u,\"fabric_cycles_including_host_stalls\":%u,\"poll_iterations\":%u,\"host_performed_dsp\":false,\"performance_comparison\":false}\n",source,boot,threshold,sparse,r->epoch,r->pairs,2*r->pairs,r->gain,r->valid_samples,r->rf_input_count,r->rf_output_count,r->clips,r->rf_status,r->bytes,r->cycles,r->iterations);
 ok=n>0;if(fclose(f))ok=false;NEED(ok,"write receipt");return true;
}

/* Bounded producer/consumer mock. Raw IQ writes are checked byte-for-byte.
 * Outputs continue after the final IQ pair so clients must drain the padded
 * real transaction rather than assume IQ count equals real sample count. */
enum { MOCK_WORDS=60020 };
typedef struct {unsigned mode,writes,accepted,pairs,gain,wr,yr,words,ys,lo,hi,sparse,clips;
 uint64_t epoch,now;bool active,overflow,done;const uint8_t*input;} Mock;
static void mock_step(Mock*m){
 if(!m->active||m->done||m->mode==3||m->mode==21)return;
 unsigned limit=m->accepted==m->pairs?OUTPUTS:(unsigned)((uint64_t)m->accepted*SAMPLES/m->pairs);
 unsigned add=minimum(32,minimum(1024-(m->ys-m->yr),limit-m->ys));m->ys+=add;
 unsigned target=(unsigned)((uint64_t)m->ys*MOCK_WORDS/OUTPUTS);
 m->words+=minimum(16,minimum(1024-(m->words-m->wr),target-m->words));
 if(m->accepted==m->pairs&&m->ys==OUTPUTS&&m->words==MOCK_WORDS){m->done=true;m->clips=(m->mode==17||m->mode==18||m->mode==19)?7:0;}
}
static uint32_t mock_read(void*p,unsigned a){Mock*m=p;
 if(a==MAGIC)return m->mode==1?0:0x54524631;
 if(a==ABI)return m->mode==20?0x20000:0x10000;
 if(a>=SOURCE&&a<SOURCE+32)return m->mode==2?1:0;
 if(a==NS)return SAMPLES;
 if(a==NY)return OUTPUTS;
 if(a==FRAMES)return FRAMECOUNT;
 if(a==ICAP)return m->mode==10?128:256;
 if(a==WCAP||a==YCAP)return 1024;
 if(a==EPOCH)return(uint32_t)m->epoch;
 if(a==EPOCH+4)return(uint32_t)(m->epoch>>32);
 if(a==THRLO)return m->lo;
 if(a==THRHI)return m->hi;
 if(a==SPARSE)return m->sparse;
 if(a==PAIRS)return m->pairs+(m->mode==12);
 if(a==GAIN)return m->gain;
 if(a==FAULT)return m->overflow||(m->active&&m->mode==4);
 if(a==STATUS){mock_step(m);return !m->active?(m->mode==22?1:0):(m->done?2:1|((m->mode==3||m->mode==21||m->accepted==m->pairs)?0:8))|(m->words>m->wr?16:0)|(m->ys>m->yr?32:0);}
 if(a==RFSTATUS)return !m->active?0:(m->done?2|(m->clips&&m->mode!=18?4:0):1)|(m->mode==16?8:0);
 if(a==WLEVEL)return m->mode==11&&m->active&&!m->done&&(m->now/100000)%4==0?0:m->words-m->wr;
 if(a==YLEVEL)return m->mode==11&&m->active&&!m->done&&(m->now/100000)%4==0?0:m->ys-m->yr;
 if(a==IFREE)return m->mode==9?257:256;
 if(a==ACCEPTED)return m->accepted;
 if(a==INPUTS)return m->done?SAMPLES:0;
 if(a==RFINPUTS)return m->accepted+(m->done&&m->mode==13);
 if(a==RFOUTPUTS)return m->active?4*m->accepted+(m->done&&m->mode==14):0;
 if(a==VALID)return 4*m->pairs+(m->done&&m->mode==15);
 if(a==CLIPS)return m->clips;
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
 if(a==COMMAND){if(x==1){m->accepted=m->wr=m->yr=m->words=m->ys=m->clips=0;m->active=m->overflow=m->done=false;m->pairs=MAXPAIRS;m->gain=1;}else{m->active=true;m->epoch+=m->mode==8?2:1;}}
 else if(a==THRLO)m->lo=x;else if(a==THRHI)m->hi=x;else if(a==SPARSE)m->sparse=x;else if(a==PAIRS)m->pairs=x;else if(a==GAIN)m->gain=x;
 else if(a==IQ){if(!m->active||m->accepted>=m->pairs||x!=((uint32_t)m->input[2*m->accepted]|(uint32_t)m->input[2*m->accepted+1]<<8))m->overflow=true;m->accepted++;}
}
static uint64_t mock_now(void*p){Mock*m=p;return m->now+=100000ULL;}
static void mock_idle(void*p){Mock*m=p;if(m->mode==3||m->mode==21)m->now+=1000000000ULL;}
static int self_test(void){
 uint8_t*in=malloc(MAXPAIRS*2);Result r={.wire=malloc(MAXWIRE),.y=malloc(OUTPUTS*sizeof(int32_t))};
 if(!in||!r.wire||!r.y)return 2;
 for(unsigned i=0;i<MAXPAIRS*2;i++)in[i]=(uint8_t)(i*73+19);
 uint32_t source[8]={0};unsigned tests=0;
 for(unsigned mode=0;mode<=22;mode++){
   Mock m={.mode=mode,.epoch=0xfedcba9880000000ULL,.input=in};Bus b={mock_read,mock_write,mock_now,mock_idle,&m};
   unsigned gain=mode==17?3:1;bool ok=run(&b,in,65536,gain,100000000000ULL,1,source,&r);
   bool expected=mode==0||mode==11||mode==17;
   if(ok!=expected||((mode==1||mode==2||mode==10||mode==20||mode==22)&&m.writes)){fprintf(stderr,"mock%u mismatch:%s\n",mode,error_text);return 2;}
   if(ok){
     if(r.bytes!=MOCK_WORDS*4||r.epoch!=0xfedcba9880000001ULL||r.ycount!=OUTPUTS||r.pairs!=65536||r.valid_samples!=262144)return 2;
     for(unsigned i=0;i<OUTPUTS;i++)if(r.y[i]!=(int)(i%4096)-2048)return 2;
     for(unsigned i=0;i<r.bytes/4;i++){uint32_t w=0x80000000u^(i*1234567u);for(unsigned k=0;k<4;k++)if(r.wire[4*i+k]!=(uint8_t)(w>>(8*k)))return 2;}
   }
   tests++;
 }
 for(unsigned n=0;n<3;n++){Mock m={.input=in};Bus b={mock_read,mock_write,mock_now,mock_idle,&m};unsigned pairs=n==0?0:n==1?MAXPAIRS+1:1,gain=n==2?4:1;if(run(&b,in,pairs,gain,0,0,source,&r)||m.writes)return 2;tests++;}
 for(unsigned n=0;n<2;n++){Mock m={.input=in};Bus b={mock_read,mock_write,mock_now,mock_idle,&m};unsigned pairs=n?MAXPAIRS:1;if(!run(&b,in,pairs,1,0,0,source,&r)){fprintf(stderr,"boundary%u:%s\n",pairs,error_text);return 2;}tests++;}
 free(in);free(r.wire);free(r.y);printf("{\"status\":\"PASS_OFFBOARD_REGISTER_MOCK\",\"tests\":%u,\"hardware_access\":false,\"raw_cu8_transport\":true,\"full_stream_samples\":384000}\n",tests);return 0;
}
int main(int argc,char**argv){
 if(argc==2&&!strcmp(argv[1],"--self-test"))return self_test();
 if(argc==2&&!strcmp(argv[1],"--help")){puts("--execute-hardware --input FILE.cu8 --gain-shift 0|1|2|3 --threshold INTEGER --sparse 0|1 --source HEX64 --boot-id UUID --out-prefix FRESH");return 0;}
 const char*inputpath=NULL,*source=NULL,*boot=NULL,*prefix=NULL;uint64_t threshold=0,sparse=2,gain=4;bool execute=false,gotthreshold=false;
 for(int i=1;i<argc;i++){const char*k=argv[i];if(!strcmp(k,"--execute-hardware")){if(execute)goto fail;execute=true;continue;}if(++i>=argc)goto fail;const char*v=argv[i];
   if(!strcmp(k,"--input")&&!inputpath)inputpath=v;else if(!strcmp(k,"--source")&&!source)source=v;else if(!strcmp(k,"--boot-id")&&!boot)boot=v;else if(!strcmp(k,"--out-prefix")&&!prefix)prefix=v;
   else if(!strcmp(k,"--threshold")&&!gotthreshold){gotthreshold=true;if(!number(v,(1ULL<<56)-1,&threshold))goto fail;}
   else if(!strcmp(k,"--sparse")&&sparse==2){if(!number(v,1,&sparse))goto fail;}
   else if(!strcmp(k,"--gain-shift")&&gain==4){if(!number(v,3,&gain))goto fail;}else goto fail;
 }
 if(!execute||!inputpath||!prefix||!gotthreshold||sparse>1||gain>3)goto fail;
 uint32_t words[8];unsigned pairs=0;uint8_t*input=malloc(MAXPAIRS*2);Result result={.wire=malloc(MAXWIRE),.y=malloc(OUTPUTS*sizeof(int32_t))};
 if(!input||!result.wire||!result.y||!source_parse(source,words)||!read_input(inputpath,input,&pairs)||!boot_check(boot))goto fail;
 char file[4096];const char*suffixes[]={".tsp1",".y.i32le",".json"};if(strlen(prefix)>sizeof file-20)goto fail;
 for(unsigned i=0;i<3;i++){snprintf(file,sizeof file,"%s%s",prefix,suffixes[i]);if(access(file,F_OK)==0){error_text="output exists";goto fail;}}
 int fd=open("/dev/mem",O_RDWR|O_SYNC|O_CLOEXEC);if(fd<0){error_text="open /dev/mem";goto fail;}
 if(flock(fd,LOCK_EX|LOCK_NB)){close(fd);error_text="exclusive device lock";goto fail;}
 void*address=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,(off_t)0xff200000ULL);if(address==MAP_FAILED){close(fd);error_text="map aperture";goto fail;}
 Mapping map={address};Bus b={physical_read,physical_write,physical_now,physical_idle,&map};bool ok=run(&b,input,pairs,(unsigned)gain,threshold,(unsigned)sparse,words,&result);
 munmap(address,4096);close(fd);
 if(!ok||!boot_check(boot)||!save(prefix,&result,source,boot,threshold,(unsigned)sparse))goto fail;
 free(input);free(result.wire);free(result.y);puts("CAPTURED_PENDING_PC_VALIDATION");return 0;
fail:fprintf(stderr,"TRF1 rejected: %s\n",error_text);return 2;
}
