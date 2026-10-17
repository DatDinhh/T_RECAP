/* Include the frozen qualified controller without changing any numerical/MMIO path. */
#define main frozen_host02_main
#include "../../trecap_cpu_fpga_bench_v01/host02/tsh2_client.c"
#undef main
#include <arpa/inet.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/wait.h>
enum {REQUEST_MAGIC=0x31515254,REPLY_MAGIC=0x31535254,INPUT_BYTES=SAMPLES*4,REPLY_BYTES=40};
static uint64_t getle(const uint8_t*p,unsigned n){uint64_t v=0;for(unsigned i=0;i<n;i++)v|=(uint64_t)p[i]<<(8*i);return v;}
static void putle(uint8_t*p,uint64_t v,unsigned n){for(unsigned i=0;i<n;i++)p[i]=(uint8_t)(v>>(8*i));}
static bool ready(int fd,short events,uint64_t deadline){
 for(;;){uint64_t now=physical_now(NULL);NEED(now<deadline,"socket phase10s deadline");struct pollfd p={fd,events,0};
 int rc=poll(&p,1,(int)((deadline-now+999999)/1000000));if(rc<0&&errno==EINTR)continue;NEED(rc>0&&!(p.revents&(POLLNVAL|POLLERR)),"socket poll");return true;}
}
static bool transfer(int fd,void*data,size_t n,bool sending,uint64_t deadline){
 uint8_t*p=data;while(n){if(!ready(fd,sending?POLLOUT:POLLIN,deadline))return false;
 ssize_t k=sending?send(fd,p,n,MSG_NOSIGNAL|MSG_DONTWAIT):recv(fd,p,n,MSG_DONTWAIT);
 if(k<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;
 NEED(k>0,"short or failed socket transfer");p+=k;n-=(size_t)k;}return true;
}
static bool expect_eof(int fd,uint64_t deadline){
 for(;;){if(!ready(fd,POLLIN,deadline))return false;uint8_t b;ssize_t k=recv(fd,&b,1,MSG_DONTWAIT);
 if(k<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;
 NEED(k==0,"request must end after exact PCM bytes");return true;}
}
static bool serve_one(int fd,Bus*b,int32_t*input,Result*r,const uint32_t source[8],const char*boot,unsigned sequence){
 uint8_t header[16],reply[REPLY_BYTES]={0};uint64_t threshold=0,deadline=physical_now(NULL)+10000000000ULL;bool ok=false;
 if(!transfer(fd,header,sizeof header,false,deadline))goto finish;
 if(getle(header,4)!=REQUEST_MAGIC||getle(header+12,4)!=INPUT_BYTES){error_text="request identity/length";goto finish;}
 threshold=getle(header+4,8);if(threshold>=(1ULL<<56)){error_text="threshold range";goto finish;}
 if(!transfer(fd,input,INPUT_BYTES,false,deadline)||!expect_eof(fd,deadline))goto finish;
 if(boot&&!boot_check(boot))goto finish;
 if(!prefault_outputs(r))goto finish;
 ok=timed_run(b,input,threshold,1,source,r);
 if(ok&&boot)ok=boot_check(boot);
finish:
 putle(reply,REPLY_MAGIC,4);putle(reply+4,ok?0:1,4);
 if(ok){putle(reply+8,r->ycount*4,4);putle(reply+12,r->bytes,4);putle(reply+16,r->epoch,8);putle(reply+24,r->host_wall_ns,8);putle(reply+32,r->host_thread_cpu_ns,8);}
 deadline=physical_now(NULL)+10000000000ULL;
 bool sent=transfer(fd,reply,sizeof reply,true,deadline);
 if(ok&&sent)sent=transfer(fd,r->y,r->ycount*4,true,deadline)&&transfer(fd,r->wire,r->bytes,true,deadline);
 if(boot){printf("{\"sequence\":%u,\"threshold\":%"PRIu64",\"success\":%s,\"reply_sent\":%s,\"epoch\":%"PRIu64",\"board_wall_ns\":%"PRIu64",\"board_thread_ns\":%"PRIu64",\"outputs_prefaulted\":true,\"cpu_affinity_zero_verified\":true}\n",sequence,threshold,ok?"true":"false",sent?"true":"false",ok?r->epoch:0,ok?r->host_wall_ns:0,ok?r->host_thread_cpu_ns:0);fflush(stdout);}
 return ok&&sent;
}
static int socket_test(unsigned bad){
 int sockets[2];if(socketpair(AF_UNIX,SOCK_STREAM,0,sockets))return 2;pid_t child=fork();if(child<0)return 2;
 if(child==0){close(sockets[0]);int32_t*input=calloc(SAMPLES,sizeof *input);Result r={.wire=malloc(MAXWIRE),.y=malloc(OUTPUTS*4)};
  if(!input||!r.wire||!r.y)_exit(2);
  Mock m={.epoch=0xfedcba9880000000ULL};Bus b={mock_read,mock_write,mock_now,mock_idle,&m};uint32_t source[8]={0};
  bool ok=serve_one(sockets[1],&b,input,&r,source,NULL,0);bool correct=bad?(!ok&&m.writes==0):ok;
  free(input);free(r.wire);free(r.y);close(sockets[1]);_exit(correct?0:2);}
 close(sockets[1]);uint8_t h[16]={0},reply[REPLY_BYTES];int32_t*input=calloc(SAMPLES,sizeof *input);bool ok=input!=NULL;
 putle(h,bad==1?0:REQUEST_MAGIC,4);putle(h+4,100000000000ULL,8);putle(h+12,bad==2?1:INPUT_BYTES,4);
 uint64_t deadline=physical_now(NULL)+10000000000ULL;
 if(ok)ok=transfer(sockets[0],h,sizeof h,true,deadline);
 if(ok&&bad!=1&&bad!=2)ok=transfer(sockets[0],input,bad==3?8:INPUT_BYTES,true,deadline);
 if(ok&&bad==4){uint8_t extra=1;ok=transfer(sockets[0],&extra,1,true,deadline);}
 shutdown(sockets[0],SHUT_WR);if(ok)ok=transfer(sockets[0],reply,sizeof reply,false,deadline);
 if(ok)ok=getle(reply,4)==REPLY_MAGIC&&getle(reply+4,4)==(bad?1:0);
 if(ok&&!bad){uint32_t ny=(uint32_t)getle(reply+8,4),nw=(uint32_t)getle(reply+12,4);uint8_t*y=malloc(ny),*w=malloc(nw);
  ok=y&&w&&ny==OUTPUTS*4&&nw==SAMPLES*8&&getle(reply+16,8)==0xfedcba9880000001ULL&&getle(reply+24,8)>0&&getle(reply+32,8)>0;
  if(ok)ok=transfer(sockets[0],y,ny,false,deadline)&&transfer(sockets[0],w,nw,false,deadline);
  if(ok){for(unsigned i=0;i<OUTPUTS;i++)if((int32_t)getle(y+4*i,4)!=(int)(i%4096)-2048)ok=false;
   for(unsigned i=0;i<nw/4;i++)if(getle(w+4*i,4)!=(0x80000000u^(i*1234567u)))ok=false;}
  free(y);free(w);}
 free(input);close(sockets[0]);int status=0;waitpid(child,&status,0);return ok&&WIFEXITED(status)&&WEXITSTATUS(status)==0?0:2;
}
int main(int argc,char**argv){
 if(argc==2&&!strcmp(argv[1],"--mock")){if(self_test())return 2;for(unsigned i=0;i<5;i++)if(socket_test(i))return 2;puts("{\"status\":\"PASS_SOCKETPAIR_FRAMING_AND_FULL_OUTPUT\",\"cases\":5,\"hardware_access\":false}");return 0;}
 if(argc!=8||strcmp(argv[1],"--execute-hardware")||strcmp(argv[2],"--source")||strcmp(argv[4],"--boot-id")||strcmp(argv[6],"--requests")){fprintf(stderr,"--execute-hardware --source HEX64 --boot-id UUID --requests 1..165\n");return 2;}
 uint16_t endian=1;uint64_t requests=0;uint32_t source[8];
 if(*(uint8_t*)&endian!=1||!number(argv[7],165,&requests)||!requests||!source_parse(argv[3],source)||!boot_check(argv[5])||!affinity_zero())goto fail;
 int32_t*input=calloc(SAMPLES,sizeof *input);Result result={.wire=malloc(MAXWIRE),.y=malloc(OUTPUTS*4),.cpu_affinity_zero_verified=true};
 if(!input||!result.wire||!result.y||!prefault_outputs(&result))goto fail;
 int mem=open("/dev/mem",O_RDWR|O_SYNC|O_CLOEXEC);if(mem<0){error_text="open /dev/mem";goto fail;}
 if(flock(mem,LOCK_EX|LOCK_NB)){close(mem);error_text="exclusive device lock";goto fail;}
 void*address=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,mem,(off_t)0xff200000ULL);
 if(address==MAP_FAILED){close(mem);error_text="map aperture";goto fail;}
 Mapping mapping={address};Bus bus={physical_read,physical_write,physical_now,physical_idle,&mapping};
 int listener=socket(AF_INET,SOCK_STREAM|SOCK_CLOEXEC,0);struct sockaddr_in addr={.sin_family=AF_INET,.sin_port=htons(18082)};
 bool ok=listener>=0&&inet_pton(AF_INET,"169.254.196.128",&addr.sin_addr)==1&&bind(listener,(struct sockaddr*)&addr,sizeof addr)==0&&listen(listener,1)==0;
 if(!ok){error_text="bind/listen169.254.196.128:18082";goto cleanup;}
 printf("{\"status\":\"LISTENING_FINITE\",\"requests\":%"PRIu64",\"source_id\":\"%s\",\"boot_id\":\"%s\"}\n",requests,argv[3],argv[5]);fflush(stdout);
 for(unsigned n=0;n<requests;n++){if(!ready(listener,POLLIN,physical_now(NULL)+10000000000ULL)){ok=false;break;}
  int client=accept4(listener,NULL,NULL,SOCK_CLOEXEC);if(client<0){ok=false;error_text="accept";break;}
  alarm(60);ok=serve_one(client,&bus,input,&result,source,argv[5],n);alarm(0);close(client);if(!ok)break;}
cleanup:
 if(listener>=0)close(listener);
 munmap(address,4096);close(mem);free(input);free(result.wire);free(result.y);
 if(ok){puts("{\"status\":\"COMPLETED_FINITE_SERVICE\"}");return 0;}
fail:fprintf(stderr,"TSH2 service rejected: %s\n",error_text);return 2;
}
