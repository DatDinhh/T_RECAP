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
#include <unistd.h>

/* No control/configuration/FIFO-pop address exists in the allowlist.
 * Caller must first admit the HPS system state with the separate system probe.
 * An outer timeout is still required for a blocked physical bus access. */
enum { MAGIC=0, ABI=4, STATUS=8, FAULT=12, ACCEPTED=36, EPOCH=40,
 WLEVEL=48, YLEVEL=52, ILEVEL=56, YCOUNT=72, CYCLES=76, DROPS=80,
 EMITTED=84, INPUTS=88, NS=92, WBYTES=96, WREAD=100, YREAD=104,
 NY=108, FRAMES=112, ICAP=116, WCAP=120, YCAP=124, SOURCE=128 };
static const unsigned offsets[]={MAGIC,ABI,STATUS,FAULT,ACCEPTED,EPOCH,EPOCH+4,
 WLEVEL,YLEVEL,ILEVEL,YCOUNT,CYCLES,DROPS,EMITTED,INPUTS,NS,WBYTES,WREAD,
 YREAD,NY,FRAMES,ICAP,WCAP,YCAP,SOURCE,SOURCE+4,SOURCE+8,SOURCE+12,
 SOURCE+16,SOURCE+20,SOURCE+24,SOURCE+28};
typedef uint32_t (*Reader)(void*,unsigned);
typedef struct { uint32_t v[40]; uint64_t epoch; unsigned reads; const char *error; } Snapshot;
#define REQUIRE(p,s) do { if(!(p)){v->error=(s);return false;} } while(0)
static uint32_t read_one(Reader reader,void *ctx,Snapshot *v,unsigned a){v->reads++;return reader(ctx,a);}
static bool epoch_read(Reader reader,void *ctx,Snapshot *v,uint64_t *out){
 for(unsigned i=0;i<8;i++){
  uint32_t h1=read_one(reader,ctx,v,EPOCH+4),l=read_one(reader,ctx,v,EPOCH),h2=read_one(reader,ctx,v,EPOCH+4);
  if(h1==h2){*out=((uint64_t)h1<<32)|l;return true;}
 }
 v->error="unstable_epoch_read";return false;
}
static bool inspect(Reader reader,void *ctx,const uint32_t expected[8],Snapshot *v){
 memset(v,0,sizeof *v);v->error="none";uint64_t before=0,after=0;
 if(!epoch_read(reader,ctx,v,&before))return false;
 for(unsigned i=0;i<sizeof offsets/sizeof offsets[0];i++)v->v[offsets[i]/4]=read_one(reader,ctx,v,offsets[i]);
 if(!epoch_read(reader,ctx,v,&after))return false;
 uint32_t final_status=read_one(reader,ctx,v,STATUS),final_fault=read_one(reader,ctx,v,FAULT);
 v->epoch=((uint64_t)v->v[(EPOCH+4)/4]<<32)|v->v[EPOCH/4];
 REQUIRE(before==after&&before==v->epoch,"epoch_changed_during_probe");
 REQUIRE(final_status==v->v[STATUS/4]&&final_fault==v->v[FAULT/4],"state_changed_during_probe");
 REQUIRE(v->v[MAGIC/4]==0x54534832&&v->v[ABI/4]==0x20000,"TSH2_identity");
 for(unsigned i=0;i<8;i++)REQUIRE(v->v[SOURCE/4+i]==expected[i],"source_identity");
 REQUIRE(v->v[NS/4]==384000&&v->v[NY/4]==384512&&v->v[FRAMES/4]==3001,"sample_geometry");
 REQUIRE(v->v[ICAP/4]==256&&v->v[WCAP/4]==1024&&v->v[YCAP/4]==1024,"FIFO_geometry");
 REQUIRE(v->v[STATUS/4]==0||v->v[STATUS/4]==2,"not_clean_IDLE_or_DONE");
 REQUIRE(v->v[FAULT/4]==0,"device_fault");
 REQUIRE(v->v[WLEVEL/4]==0&&v->v[YLEVEL/4]==0&&v->v[ILEVEL/4]==0,"FIFO_not_empty");
 REQUIRE(v->v[DROPS/4]==0,"dropped_frames");
 if(v->v[STATUS/4]==0){
  /* CLEAR_CORE/WAIT_INIT are busy, so a clean IDLE may retain a few elapsed
   * initialization cycles after CLEAR. Data counters must still be zero. */
  const unsigned zero[]={ACCEPTED,YCOUNT,EMITTED,INPUTS,WBYTES,WREAD,YREAD};
  for(unsigned i=0;i<sizeof zero/sizeof zero[0];i++)REQUIRE(v->v[zero[i]/4]==0,"IDLE_nonzero_counts");
 }else{
  REQUIRE(v->v[ACCEPTED/4]==384000&&v->v[INPUTS/4]==384000,"DONE_input_counts");
  REQUIRE(v->v[YCOUNT/4]==384512&&v->v[YREAD/4]==384512,"DONE_Y_counts");
  REQUIRE(v->v[EMITTED/4]==3001,"DONE_frame_count");
  uint32_t bytes=v->v[WBYTES/4];
  REQUIRE(bytes>=48u*3001u&&bytes<=1080u*3001u&&bytes%8==0&&v->v[WREAD/4]==bytes/4,"DONE_spectral_counts");
  REQUIRE(v->v[CYCLES/4]>0&&v->v[CYCLES/4]<=3000000000u,"DONE_cycle_range");
 }
 return true;
}
static bool parse_source(const char*s,uint32_t words[8]){
 if(strlen(s)!=64)return false;
 for(unsigned i=0;i<64;i++)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return false;
 for(unsigned i=0;i<8;i++){char part[9];memcpy(part,s+56-8*i,8);part[8]=0;words[i]=(uint32_t)strtoul(part,NULL,16);}return true;
}
static void print_snapshot(const Snapshot*v,bool ok){
 printf("{\"status\":\"%s\",\"error\":\"%s\",\"writes_performed\":false,\"fifo_pop_performed\":false,\"reads\":%u,\"source_id\":\"",
 ok?"PASS_TSH2_READ_ONLY_IDLE":"REJECTED_TSH2_READ_ONLY",v->error,v->reads);
 for(int i=7;i>=0;i--)printf("%08"PRIx32,v->v[SOURCE/4+(unsigned)i]);
 printf("\",\"epoch\":%"PRIu64",\"registers\":{",v->epoch);
 for(unsigned i=0;i<sizeof offsets/sizeof offsets[0];i++)printf("%s\"0x%03x\":%"PRIu32,i?",":"",offsets[i],v->v[offsets[i]/4]);
 puts("}}");
}
typedef struct { uint32_t v[40]; unsigned reads; bool forbidden; unsigned change_epoch_at; } Mock;
static uint32_t mock_read(void*ctx,unsigned a){
 Mock*m=ctx;m->reads++;bool allowed=false;
 for(unsigned i=0;i<sizeof offsets/sizeof offsets[0];i++)if(a==offsets[i])allowed=true;
 if(!allowed||a==0x40||a==0x44){m->forbidden=true;return 0;}
 if(m->change_epoch_at&&m->reads>=m->change_epoch_at&&a==EPOCH)return m->v[a/4]+1;
 return m->v[a/4];
}
static Mock good(bool done){
 Mock m={0};m.v[MAGIC/4]=0x54534832;m.v[ABI/4]=0x20000;m.v[NS/4]=384000;m.v[NY/4]=384512;m.v[FRAMES/4]=3001;
 m.v[ICAP/4]=256;m.v[WCAP/4]=m.v[YCAP/4]=1024;m.v[EPOCH/4]=48;m.v[(EPOCH+4)/4]=0xfedcba98;m.v[CYCLES/4]=3;
 for(unsigned i=0;i<8;i++)m.v[SOURCE/4+i]=0x12345678u+i;
 if(done){m.v[STATUS/4]=2;m.v[ACCEPTED/4]=m.v[INPUTS/4]=384000;m.v[YCOUNT/4]=m.v[YREAD/4]=384512;m.v[EMITTED/4]=3001;m.v[WBYTES/4]=3001*1080;m.v[WREAD/4]=m.v[WBYTES/4]/4;m.v[CYCLES/4]=40000000;}
 return m;
}
static int self_test(void){
 uint32_t expected[8];for(unsigned i=0;i<8;i++)expected[i]=0x12345678u+i;unsigned cases=0;
 for(unsigned mode=0;mode<24;mode++){
  Mock m=good(mode!=0);bool want=mode<2;
  switch(mode){case 2:m.v[STATUS/4]=1;break;case 3:m.v[SOURCE/4]^=1;break;case 4:m.v[FAULT/4]=1;break;
   case 5:m.v[WLEVEL/4]=1;break;case 6:m.v[YLEVEL/4]=1;break;case 7:m.v[ILEVEL/4]=1;break;
   case 8:m.v[NS/4]--;break;case 9:m.v[ICAP/4]--;break;case 10:m.v[DROPS/4]=1;break;
   case 11:m.v[ACCEPTED/4]--;break;case 12:m.v[INPUTS/4]--;break;case 13:m.v[YREAD/4]--;break;
   case 14:m.v[WREAD/4]--;break;case 15:m.v[EMITTED/4]--;break;case 16:m.v[CYCLES/4]=0;break;
   case 17:m.v[MAGIC/4]^=1;break;case 18:m.v[ABI/4]^=1;break;case 19:m.change_epoch_at=35;break;
   case 20:m=good(false);m.v[ACCEPTED/4]=1;break;case 21:m.v[WBYTES/4]--;break;
   case 22:m.v[STATUS/4]=0x80000002u;break;case 23:m.v[YCOUNT/4]--;break;default:break;}
  Snapshot s;bool ok=inspect(mock_read,&m,expected,&s);
  if(ok!=want||m.forbidden||s.reads!=m.reads||s.reads>64){fprintf(stderr,"mock %u failed: %s\n",mode,s.error);return 2;}cases++;
 }
 char valid[]="0000000000000000000000000000000000000000000000000000000000000001";uint32_t parsed[8];
 if(!parse_source(valid,parsed)||parsed[0]!=1||parsed[7]!=0||parse_source("bad",parsed))return 2;
 valid[0]='g';if(parse_source(valid,parsed))return 2;
 printf("{\"status\":\"PASS_TSH2_PROBE_MOCK\",\"register_cases\":%u,\"source_parser_cases\":3,\"hardware_access\":false,\"writes_performed\":false,\"fifo_pop_performed\":false}\n",cases);return 0;
}
static uint32_t physical_read(void*ctx,unsigned a){const volatile uint32_t*p=ctx;__sync_synchronize();uint32_t v=p[a/4];__sync_synchronize();return v;}
int main(int argc,char**argv){
 if(argc==2&&!strcmp(argv[1],"--self-test"))return self_test();
 uint32_t expected[8];
 if(argc!=4||strcmp(argv[1],"--read-only")||strcmp(argv[2],"--source")||!parse_source(argv[3],expected)){
  fprintf(stderr,"--self-test OR --read-only --source lowercase_hex64; root must admit HPS state before aperture access\n");return 2;}
 alarm(5);
 int fd=open("/dev/mem",O_RDONLY|O_SYNC|O_CLOEXEC);if(fd<0){perror("open /dev/mem");return 2;}
 if(flock(fd,LOCK_EX|LOCK_NB)){perror("exclusive /dev/mem lock");close(fd);return 2;}
 void *p=mmap(NULL,4096,PROT_READ,MAP_SHARED,fd,(off_t)UINT64_C(0xff200000));
 if(p==MAP_FAILED){perror("map fixed TSH2 aperture");close(fd);return 2;}
 Snapshot s;bool ok=inspect(physical_read,p,expected,&s);int unmap_rc=munmap(p,4096),close_rc=close(fd);alarm(0);
 if(unmap_rc||close_rc){perror("close read-only mapping");return 2;}
 print_snapshot(&s,ok);return ok?0:1;
}
