#pragma once
#define main preserved_cpu02_cli_main
#include "../../trecap_cpu_fpga_bench_v01/cpu02/main.cpp"
#undef main
#include <intrin.h>
inline DWORD_PTR pin_native_thread(){DWORD_PTR process=0,system=0;need(GetProcessAffinityMask(GetCurrentProcess(),&process,&system)!=0&&process,"affinity query");DWORD_PTR chosen=process&(~process+1);need(SetThreadAffinityMask(GetCurrentThread(),chosen)!=0,"pin thread");GROUP_AFFINITY actual{};need(GetThreadGroupAffinity(GetCurrentThread(),&actual)&&actual.Mask==chosen,"verify affinity");return chosen;}
inline uint64_t process_ns(){FILETIME c,e,k,u;need(GetProcessTimes(GetCurrentProcess(),&c,&e,&k,&u)!=0,"process clock");ULARGE_INTEGER a{},b{};a.LowPart=k.dwLowDateTime;a.HighPart=k.dwHighDateTime;b.LowPart=u.dwLowDateTime;b.HighPart=u.dwHighDateTime;return(a.QuadPart+b.QuadPart)*100;}
inline std::string processor_name(){char brand[49]{};for(int i=0;i<3;i++){int regs[4];__cpuid(regs,0x80000002+i);std::memcpy(brand+16*i,regs,16);}return brand;}
struct Context{std::vector<int32_t> input;Runner runner;Context(const char*coeff,const char*path):input(pcm(path,NS)),runner(coeff){}void touch(){prefault(input.data(),input.size()*sizeof input[0]);runner.prefault_buffers();}};
