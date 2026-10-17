// Allocation-free scalar fixed-width CPU02. See NUMERICS.md.
#include <array>
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>
#include "kernel.hpp"
#ifdef _WIN32
#include <windows.h>
#else
#include <sched.h>
#include <time.h>
#include <unistd.h>
#endif
using namespace cpu02;
namespace fs=std::filesystem;
constexpr size_t NS=384000,NY=384512,NFRAMES=3001,MAXWIRE=3241080;
void need(bool v,const char* s){if(!v)throw std::runtime_error(s);}
void prefault(void* p,size_t n){
#ifdef _WIN32
 SYSTEM_INFO info{};GetSystemInfo(&info);const size_t page=info.dwPageSize;
#else
 const long page_size=sysconf(_SC_PAGESIZE);need(page_size>0,"page size");const size_t page=static_cast<size_t>(page_size);
#endif
 auto b=static_cast<volatile uint8_t*>(p);for(size_t i=0;i<n;i+=page){const uint8_t x=b[i];b[i]=x;}if(n){const uint8_t x=b[n-1];b[n-1]=x;}}
void pin_cpu0(){
#ifdef _WIN32
 need(false,"Primary measurement requires Linux HPS; Windows qualification only");
#else
 cpu_set_t set;CPU_ZERO(&set);CPU_SET(0,&set);need(sched_setaffinity(0,sizeof set,&set)==0,"pin CPU0");CPU_ZERO(&set);need(sched_getaffinity(0,sizeof set,&set)==0&&CPU_COUNT(&set)==1&&CPU_ISSET(0,&set),"verify CPU0 affinity");
#endif
}
std::vector<uint8_t> bytes(const fs::path&p){std::ifstream f(p,std::ios::binary);need(bool(f),"open binary");return {std::istreambuf_iterator<char>(f),{}};}
std::vector<int32_t> pcm(const fs::path&p,size_t n){auto b=bytes(p);need(b.size()==n*4,"PCM byte count");std::vector<int32_t>v(n);for(size_t i=0;i<n;i++){uint32_t x=0;for(unsigned k=0;k<4;k++)x|=uint32_t(b[4*i+k])<<(8*k);v[i]=static_cast<int32_t>(x);}return v;}
std::vector<int64_t> memh(const fs::path&p,unsigned bits,bool sign){std::ifstream f(p);need(bool(f),"open coefficients");std::vector<int64_t>v;std::string s;while(f>>s){size_t used=0;auto x=std::stoull(s,&used,16);need(used==s.size()&&x<(uint64_t(1)<<bits),"coefficient encoding");v.push_back(sign&&(x&(uint64_t(1)<<(bits-1)))?int64_t(x)-int64_t(uint64_t(1)<<bits):int64_t(x));}need(v.size()==256,"coefficient count");return v;}
uint64_t nsclock(bool cpu){
#ifdef _WIN32
 if(cpu){FILETIME c,e,k,u;need(GetThreadTimes(GetCurrentThread(),&c,&e,&k,&u)!=0,"thread clock");ULARGE_INTEGER a{},b{};a.LowPart=k.dwLowDateTime;a.HighPart=k.dwHighDateTime;b.LowPart=u.dwLowDateTime;b.HighPart=u.dwHighDateTime;return(a.QuadPart+b.QuadPart)*100;}
 LARGE_INTEGER t,f;QueryPerformanceCounter(&t);QueryPerformanceFrequency(&f);return uint64_t((long double)t.QuadPart*1000000000.0L/f.QuadPart);
#else
 timespec t{};need(clock_gettime(cpu?CLOCK_THREAD_CPUTIME_ID:CLOCK_MONOTONIC,&t)==0,"clock_gettime");return uint64_t(t.tv_sec)*1000000000ULL+uint64_t(t.tv_nsec);
#endif
}
struct Runner {
 Kernel kernel;
 std::array<int64_t,256> z{};
 std::array<int64_t,256> input_ring{},frame{};
 std::array<int64_t,384> ola{};
 std::array<uint64_t,129> magnitudes{};
 std::array<bool,129> keep{};
 std::vector<int32_t> y=std::vector<int32_t>(NY);
 std::vector<uint8_t> wire=std::vector<uint8_t>(MAXWIRE);
 size_t count=0;
 explicit Runner(const fs::path&dir){auto w=memh(dir/"window_qw.memh",16,false),r=memh(dir/"twiddle_re.memh",17,true),im=memh(dir/"twiddle_im.memh",17,true),ir=memh(dir/"twiddle_inv_re.memh",17,true),ii=memh(dir/"twiddle_inv_im.memh",17,true);for(size_t i=0;i<256;i++){kernel.window[i]=uint16_t(w[i]);kernel.forward[i]={r[i],im[i]};kernel.inverse[i]={ir[i],ii[i]};}kernel.prepare();}
 void prefault_buffers(){prefault(input_ring.data(),sizeof input_ring);prefault(frame.data(),sizeof frame);prefault(ola.data(),sizeof ola);prefault(magnitudes.data(),sizeof magnitudes);prefault(keep.data(),sizeof keep);prefault(y.data(),y.size()*sizeof y[0]);prefault(wire.data(),wire.size());prefault(&kernel,sizeof kernel);prefault(z.data(),sizeof z);}
 void put(size_t p,uint64_t v,unsigned n){need(p+n<=wire.size(),"wire bounds");for(unsigned k=0;k<n;k++)wire[p+k]=uint8_t(v>>(8*k));}
 void record(uint64_t frame_id,uint64_t threshold){unsigned kept=0;for(bool v:keep)kept+=v;size_t start=count,size=48+8*kept;need(start+size<=MAXWIRE,"wire capacity");
  put(start,0x31505354,4);put(start+4,1,2);put(start+6,1,2);put(start+8,0x10001,4);put(start+12,8*kept,4);put(start+16,frame_id,8);put(start+24,threshold,8);put(start+32,kept,2);put(start+34,1,2);put(start+36,0,4);
  size_t p=start+48;for(unsigned k=0;k<129;k++)if(keep[k]){put(p,(magnitudes[k]<<8)|k,8);p+=8;}
  uint64_t h=14695981039346656037ULL;for(size_t i=start;i<start+40;i++)h=(h^wire[i])*1099511628211ULL;for(size_t i=start+48;i<p;i++)h=(h^wire[i])*1099511628211ULL;put(start+40,h,8);count=p;
 }
 void epoch(std::span<const int32_t>x,uint64_t threshold){
  need(x.size()==NS&&threshold<(1ULL<<56),"epoch geometry/config");for(auto v:x)need(v>=-2048&&v<=2047,"input range");
  input_ring.fill(0);frame.fill(0);ola.fill(0);magnitudes.fill(0);keep.fill(false);count=0;size_t wr=0,rd=0,frames=0;
  for(size_t n=0;n<NY;n++){
   input_ring[wr]=n<NS?x[n]:0;wr=(wr+1)%256;
   y[n]=static_cast<int32_t>(saturate12(round_shift<15>(ola[rd])));ola[rd]=0;rd=(rd+1)%384;
   if((n+1)%128==0&&(n+1)<=384128){
    for(size_t i=0;i<256;i++)frame[i]=input_ring[(wr+i)%256];
    kernel.analyze(frame);auto& canonical=kernel.canonical;
    for(unsigned k=0;k<129;k++){const auto re=canonical[k].re,im=canonical[k].im;magnitudes[k]=uint64_t(re*re)+uint64_t(im*im);need(magnitudes[k]<(1ULL<<56),"magnitude width");keep[k]=k==0||magnitudes[k]>=threshold;if(!keep[k]){canonical[k]={0,0};if(k!=128)canonical[256-k]={0,0};}}
    record(frames,threshold);kernel.synthesize(z);
    for(size_t i=0;i<256;i++){const size_t p=(rd+128+i)%384;ola[p]=fit<37>(ola[p]+z[i]);}
    frames++;
   }
  }
  need(frames==NFRAMES&&count>=NFRAMES*56&&count<=MAXWIRE&&count%8==0,"final counts");
 }
};
int main(int argc,char**argv){try{
 need(argc==8,"usage: runner --qualify|--measure-once input.i32le coefficient_dir threshold goldY.i32le gold.tsp1 outprefix|- ");
 const bool measured=std::string(argv[1])=="--measure-once";need(measured||std::string(argv[1])=="--qualify","explicit mode required");
 if(measured){pin_cpu0();}
 const bool check_gold=std::string(argv[5])!="-"&&std::string(argv[6])!="-";need(check_gold||(measured&&std::string(argv[5])=="-"&&std::string(argv[6])=="-"&&std::string(argv[7])!="-"),"qualification requires gold; unvalidated measurement must save both outputs");
 auto input=pcm(argv[2],NS);const auto gold_y=check_gold?pcm(argv[5],NY):std::vector<int32_t>{};const auto gold_wire=check_gold?bytes(argv[6]):std::vector<uint8_t>{};size_t used=0;const uint64_t threshold=std::stoull(argv[4],&used);need(used==std::string(argv[4]).size(),"threshold parse");Runner runner(argv[3]);
 prefault(input.data(),input.size()*sizeof input[0]);runner.prefault_buffers();
 uint64_t wall_start=0,cpu_start=0,wall_end=0,cpu_end=0;if(measured){wall_start=nsclock(false);cpu_start=nsclock(true);}runner.epoch(input,threshold);if(measured){cpu_end=nsclock(true);wall_end=nsclock(false);}
 const uint64_t wall=wall_end-wall_start,cpu=cpu_end-cpu_start;
 if(check_gold){need(runner.y==gold_y,"fullY mismatch");need(runner.count==gold_wire.size()&&std::equal(gold_wire.begin(),gold_wire.end(),runner.wire.begin()),"TSP1 mismatch");}
 if(std::string(argv[7])!="-"){const fs::path p=argv[7];need(!fs::exists(p.string()+".y.i32le")&&!fs::exists(p.string()+".tsp1"),"fresh outputs required");std::ofstream y(p.string()+".y.i32le",std::ios::binary),w(p.string()+".tsp1",std::ios::binary);for(int32_t v:runner.y)for(unsigned k=0;k<4;k++)y.put(char(uint32_t(v)>>(8*k)));w.write(reinterpret_cast<const char*>(runner.wire.data()),std::streamsize(runner.count));need(bool(y)&&bool(w),"output write");}
 std::cout<<"{\"status\":\""<<(check_gold?"PASS_EXACT_CPU_EPOCH":"CPU_EPOCH_PENDING_PC_VALIDATION")<<"\",\"threshold\":"<<threshold<<",\"y_samples\":"<<NY<<",\"frames\":"<<NFRAMES<<",\"spectral_bytes\":"<<runner.count<<",\"timing_enabled\":"<<(measured?"true":"false")<<",\"wall_start_ns\":"<<wall_start<<",\"wall_end_ns\":"<<wall_end<<",\"thread_cpu_start_ns\":"<<cpu_start<<",\"thread_cpu_end_ns\":"<<cpu_end<<",\"wall_ns\":"<<wall<<",\"thread_cpu_ns\":"<<cpu<<",\"affinity_cpu0\":"<<(measured?"true":"false")<<",\"resident_buffers_prefaulted\":true,\"transform_internal_allocations\":false,\"kernel\":\"cpu02_fixed_width_scalar\",\"campaign_qualified\":false}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 2;}}
