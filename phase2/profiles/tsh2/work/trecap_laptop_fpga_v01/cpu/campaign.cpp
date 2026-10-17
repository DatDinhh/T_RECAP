#include <cstring>
#include "shared.hpp"
int main(int argc,char**argv){try{
 need(argc==2,"usage campaign.exe FIXTUREDIR");const auto mask=pin_native_thread();const fs::path f=argv[1];Context ctx((f/"coefficients").string().c_str(),(f/"input.i32le").string().c_str());
 SYSTEM_INFO si{};GetSystemInfo(&si);std::cout<<"{\"kind\":\"environment\",\"environment\":\"native_windows_msvc_x64\",\"cpu\":\""<<processor_name()<<"\",\"logical_processors\":"<<si.dwNumberOfProcessors<<",\"thread_affinity_mask\":"<<mask<<",\"compiler_msc_ver\":"<<_MSC_VER<<",\"timing_scope\":\"resident_PCM_to_resident_full_Y_and_sparse_TSP1\"}\n";
 for(uint64_t threshold:{0ULL,100000000ULL,1000000000ULL,10000000000ULL,100000000000ULL}){
  const auto dir=f/("flute8s_thr"+std::to_string(threshold));const auto gold_y=pcm(dir/"y.i32le",NY);const auto gold=bytes(dir/"sparse.tsp1");
  for(int trial=-3;trial<30;trial++){
   ctx.touch();const auto ws=nsclock(false),ps=process_ns(),ts=nsclock(true);ctx.runner.epoch(ctx.input,threshold);const auto te=nsclock(true),pe=process_ns(),we=nsclock(false);
   need(ctx.runner.y==gold_y,"full Y mismatch");need(ctx.runner.count==gold.size()&&std::equal(gold.begin(),gold.end(),ctx.runner.wire.begin()),"full TSP1 mismatch");
   std::cout<<"{\"kind\":\"trial\",\"status\":\"PASS_EXACT\",\"threshold\":"<<threshold<<",\"trial\":"<<trial<<",\"wall_start_ns\":"<<ws<<",\"wall_end_ns\":"<<we<<",\"wall_ns\":"<<we-ws<<",\"process_cpu_start_ns\":"<<ps<<",\"process_cpu_end_ns\":"<<pe<<",\"process_cpu_ns\":"<<pe-ps<<",\"thread_cpu_start_ns\":"<<ts<<",\"thread_cpu_end_ns\":"<<te<<",\"thread_cpu_ns\":"<<te-ts<<",\"y_samples\":"<<NY<<",\"frames\":"<<NFRAMES<<",\"spectral_bytes\":"<<ctx.runner.count<<"}\n";
  }
 }
 std::cout<<"{\"kind\":\"completion\",\"status\":\"PASS_165_EXACT_NATIVE_LAPTOP_EPOCHS\",\"measured_epochs\":150,\"warmup_epochs\":15}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 2;}}
