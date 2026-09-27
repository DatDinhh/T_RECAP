// SPDX-License-Identifier: MIT
#include "kernel.hpp"
#include <algorithm>
#include <chrono>
#include <cctype>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#if defined(__linux__)
#include <time.h>
#include <sys/utsname.h>
#include <sched.h>
#endif
#ifndef TRECAP_BUILD_FLAGS
#define TRECAP_BUILD_FLAGS "not embedded; retain the external build command/manifest"
#endif

namespace tb=trecap_bench;
namespace {
struct Options {
    std::string input,expected,coeff_dir,output,output_samples;
    std::uint64_t threshold=0,epochs=1,trials=20,warmup=3;
    int cpu=-1;
    bool verify_only=false,threshold_given=false;
};
void require(bool ok,const std::string& message) {if(!ok)throw std::runtime_error(message);}
std::uint64_t decimal(const std::string& s) {
    require(!s.empty() && s.find_first_not_of("0123456789")==std::string::npos,"invalid unsigned decimal: "+s);
    std::size_t end=0;const auto v=std::stoull(s,&end,10);require(end==s.size(),"invalid decimal");return v;
}
Options parse(int argc,char**argv) {
    Options o;
    for(int i=1;i<argc;++i) {
        const std::string arg=argv[i];
        if(arg=="--verify-only") {o.verify_only=true;continue;}
        if(arg=="--help") {std::cout<<"trecap_cpu_benchmark --input INPUT.memh --expected OUTPUT.memh --coeff-dir DIR --threshold U56 --epochs 1 --trials 20 --warmup 3 --output NEW.json [--cpu N (Linux only)] [--verify-only] [--output-samples NEW.memh]\n";std::exit(0);}
        require(i+1<argc,"missing value for "+arg);const std::string value=argv[++i];
        if(arg=="--input")o.input=value;else if(arg=="--expected")o.expected=value;else if(arg=="--coeff-dir")o.coeff_dir=value;else if(arg=="--output")o.output=value;else if(arg=="--output-samples")o.output_samples=value;
        else if(arg=="--threshold") {o.threshold=decimal(value);o.threshold_given=true;}
        else if(arg=="--cpu") {const auto cpu=decimal(value);require(cpu<=static_cast<std::uint64_t>(std::numeric_limits<int>::max()),"CPU index exceeds int range");o.cpu=static_cast<int>(cpu);}
        else if(arg=="--epochs")o.epochs=decimal(value);else if(arg=="--trials")o.trials=decimal(value);else if(arg=="--warmup")o.warmup=decimal(value);else throw std::runtime_error("unknown argument: "+arg);
    }
    require(!o.input.empty()&&!o.expected.empty()&&!o.coeff_dir.empty()&&!o.output.empty()&&o.threshold_given,"input, expected, coeff-dir, threshold, and output are required");
    require(o.threshold<(std::uint64_t{1}<<56),"threshold must fit unsigned56");
    require(o.epochs>=1&&o.epochs<=1000000&&o.trials>=1&&o.trials<=10000&&o.warmup<=1000000,"epoch/trial/warmup bound exceeded");
    require(!std::filesystem::exists(o.output),"output already exists; choose a new JSON file");
    require(o.output_samples.empty()||!std::filesystem::exists(o.output_samples),"output-samples already exists");
    require(o.output_samples.empty()||o.output_samples!=o.output,"output and output-samples must differ");
    return o;
}
void apply_affinity(int requested_cpu) {
    if(requested_cpu<0)return; // Leave inherited affinity unchanged by default.
#if defined(__linux__)
    require(requested_cpu<CPU_SETSIZE,"requested CPU exceeds supported affinity-set size");
    cpu_set_t desired;CPU_ZERO(&desired);CPU_SET(requested_cpu,&desired);
    if(sched_setaffinity(0,sizeof(desired),&desired)!=0)
        throw std::runtime_error(std::string("sched_setaffinity failed: ")+std::strerror(errno));
    cpu_set_t actual;CPU_ZERO(&actual);
    if(sched_getaffinity(0,sizeof(actual),&actual)!=0)
        throw std::runtime_error(std::string("affinity readback failed: ")+std::strerror(errno));
    for(int i=0;i<CPU_SETSIZE;++i)
        require(bool(CPU_ISSET(i,&actual))==(i==requested_cpu),"affinity readback differs from requested single CPU");
#else
    throw std::runtime_error("--cpu is supported only on Linux; affinity was not changed");
#endif
}
std::vector<std::int64_t> memh(const std::string& path,unsigned width,bool sign) {
    std::ifstream f(path);require(f.good(),"cannot read "+path);std::string line;std::vector<std::int64_t> values;
    while(std::getline(f,line)) {
        const auto comment=line.find("//");if(comment!=std::string::npos)line.resize(comment);
        std::istringstream row(line);std::string token;
        while(row>>token) {
            require(token.size()<=(width+3)/4&&token.find_first_not_of("0123456789abcdefABCDEF")==std::string::npos,"invalid MEMH token in "+path);
            const auto v=std::stoull(token,nullptr,16);require(v<(std::uint64_t{1}<<width),"MEMH value exceeds declared width in "+path);
            const auto decoded=sign&&(v&(std::uint64_t{1}<<(width-1)))?static_cast<std::int64_t>(v)-static_cast<std::int64_t>(std::uint64_t{1}<<width):static_cast<std::int64_t>(v);
            values.push_back(decoded);require(values.size()<=16777216,"MEMH safety length bound exceeded");
        }
    }
    require(f.eof()&&!values.empty(),"empty or unreadable MEMH "+path);return values;
}
std::string join(const std::string& directory,const std::string& name) {
    return directory+((directory.back()=='/'||directory.back()=='\\')?"":"/")+name;
}
tb::Coefficients load_coefficients(const std::string& directory) {
    tb::Coefficients c;const auto window=memh(join(directory,"window_qw.memh"),16,false);require(window.size()==tb::L,"window must have256 entries");
    for(std::size_t i=0;i<tb::L;++i) {require(window[i]<=32768,"window outside frozen Q15 domain");c.window[i]=static_cast<std::uint16_t>(window[i]);}
    for(bool inv:{false,true}) {
        const std::string prefix=inv?"twiddle_inv_":"twiddle_";
        const auto real=memh(join(directory,prefix+"re.memh"),17,true),imag=memh(join(directory,prefix+"im.memh"),17,true);
        require(real.size()==tb::L&&imag.size()==tb::L,"twiddle must have256 entries");auto& table=inv?c.inverse:c.forward;
        for(std::size_t i=0;i<tb::L;++i) {
            require(real[i]>=-32768&&real[i]<=32768&&imag[i]>=-32768&&imag[i]<=32768,"twiddle outside Q15 unit-coefficient component domain");
            table[i]={static_cast<std::int32_t>(real[i]),static_cast<std::int32_t>(imag[i])};
        }
    }
    return c;
}
std::size_t compare(const std::vector<std::int16_t>& got,const std::vector<std::int16_t>& expected,const std::string& phase) {
    require(got.size()==expected.size(),phase+" output length mismatch");std::size_t mismatches=0,first=0;
    for(std::size_t i=0;i<got.size();++i)if(got[i]!=expected[i]) {if(mismatches==0)first=i;++mismatches;}
    require(mismatches==0,phase+" full-output mismatch count="+std::to_string(mismatches)+" first="+std::to_string(first));return got.size();
}
std::string quoted(const std::string& s) {
    std::ostringstream o;o<<'"';for(unsigned char c:s) {if(c=='"'||c=='\\')o<<'\\'<<static_cast<char>(c);else if(c<32)o<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<unsigned(c)<<std::dec;else o<<static_cast<char>(c);}o<<'"';return o.str();
}
struct Timer {
    std::string wall_name="std::chrono::steady_clock",thread_name="unavailable";
    bool thread_available=false;
    std::uint64_t wall_resolution_ns=0,thread_resolution_ns=0;
#if defined(__linux__)
    clockid_t wall_id=CLOCK_MONOTONIC;
    static std::uint64_t get(clockid_t id) {timespec t{};if(clock_gettime(id,&t)!=0)throw std::runtime_error("clock_gettime failed");return static_cast<std::uint64_t>(t.tv_sec)*1000000000ULL+static_cast<std::uint64_t>(t.tv_nsec);}
    static std::uint64_t resolution(clockid_t id) {timespec t{};if(clock_getres(id,&t)!=0)throw std::runtime_error("clock_getres failed");return static_cast<std::uint64_t>(t.tv_sec)*1000000000ULL+static_cast<std::uint64_t>(t.tv_nsec);}
#endif
    Timer() {
#if defined(__linux__)
#ifdef CLOCK_MONOTONIC_RAW
        timespec t{};if(clock_gettime(CLOCK_MONOTONIC_RAW,&t)==0)wall_id=CLOCK_MONOTONIC_RAW;
        wall_name=wall_id==CLOCK_MONOTONIC_RAW?"CLOCK_MONOTONIC_RAW":"CLOCK_MONOTONIC";
#else
        wall_name="CLOCK_MONOTONIC";
#endif
        wall_resolution_ns=resolution(wall_id);
#ifdef CLOCK_THREAD_CPUTIME_ID
        timespec cpu{};thread_available=clock_gettime(CLOCK_THREAD_CPUTIME_ID,&cpu)==0;
        if(thread_available) {thread_name="CLOCK_THREAD_CPUTIME_ID";thread_resolution_ns=resolution(CLOCK_THREAD_CPUTIME_ID);}
#endif
#else
        static_assert(std::chrono::steady_clock::is_steady,"monotonic fallback required");
        wall_resolution_ns=static_cast<std::uint64_t>(1.0e9*std::chrono::steady_clock::period::num/std::chrono::steady_clock::period::den);
#endif
    }
    std::uint64_t wall() const {
#if defined(__linux__)
        return get(wall_id);
#else
        return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());
#endif
    }
    std::uint64_t thread() const {
#if defined(__linux__) && defined(CLOCK_THREAD_CPUTIME_ID)
        return thread_available?get(CLOCK_THREAD_CPUTIME_ID):0;
#else
        return 0;
#endif
    }
};
std::string environment(int requested_cpu) {
    std::ostringstream out;
#if defined(__arm__)
    const char* architecture="arm32";const char* label="arm32_kernel_run_board_identity_not_attested";
#elif defined(__aarch64__)
    const char* architecture="aarch64";const char* label="aarch64_host_not_cortex_a9_measurement";
#elif defined(__x86_64__) || defined(_M_X64)
    const char* architecture="x86_64";const char* label="host_smoke_not_arm_measurement";
#else
    const char* architecture="other";const char* label="host_smoke_not_arm_measurement";
#endif
    out<<"{\"compile_architecture\":"<<quoted(architecture)<<",\"execution_label\":"<<quoted(label)<<",\"board_identity_attested\":false,\"cpu_frequency_hz\":null,\"frequency_note\":\"Not measured; do not infer frequency from a target flag\",\"compiler\":";
#if defined(__VERSION__)
    out<<quoted(__VERSION__);
#elif defined(_MSC_VER)
    out<<quoted("MSVC "+std::to_string(_MSC_VER));
#else
    out<<"\"unknown\"";
#endif
    out<<",\"cplusplus\":"<<__cplusplus<<",\"build_flags\":"<<quoted(TRECAP_BUILD_FLAGS);
    out<<",\"requested_cpu\":";
    if(requested_cpu>=0)out<<requested_cpu;else out<<"null";
    out<<",\"requested_affinity_applied_and_read_back\":"<<(requested_cpu>=0?"true":"false");
#if defined(__linux__)
    utsname u{};require(uname(&u)==0,"uname failed");out<<",\"uname\":{\"sysname\":"<<quoted(u.sysname)<<",\"release\":"<<quoted(u.release)<<",\"machine\":"<<quoted(u.machine)<<"}";
    cpu_set_t set;CPU_ZERO(&set);out<<",\"allowed_cpus\":[";bool first=true;
    if(sched_getaffinity(0,sizeof(set),&set)==0)for(int i=0;i<CPU_SETSIZE;++i)if(CPU_ISSET(i,&set)) {if(!first)out<<',';out<<i;first=false;}
    out<<"],\"cpu_at_metadata_collection\":"<<sched_getcpu();
    std::ifstream info("/proc/cpuinfo");std::string line;out<<",\"cpuinfo_selected\":{ ";first=true;
    std::vector<std::string> seen;
    while(std::getline(info,line)) {
        const auto pos=line.find(':');if(pos==std::string::npos)continue;std::string key=line.substr(0,pos),value=line.substr(pos+1);
        while(!key.empty()&&std::isspace(static_cast<unsigned char>(key.back())))key.pop_back();
        while(!value.empty()&&std::isspace(static_cast<unsigned char>(value.front())))value.erase(value.begin());
        if((key=="model name"||key=="Processor"||key=="CPU architecture"||key=="Features"||key=="CPU implementer"||key=="CPU part")&&std::find(seen.begin(),seen.end(),key)==seen.end()) {if(!first)out<<',';out<<quoted(key)<<':'<<quoted(value);first=false;seen.push_back(key);}
    }
    out<<'}';
#endif
    out<<'}';return out.str();
}
struct Record {std::uint64_t wall_ns{},thread_ns{},checksum{};};
} // namespace

int main(int argc,char**argv) {
    try {
        const auto options=parse(argc,argv);
        apply_affinity(options.cpu); // Before loading, checked admission, and warmup.
        const auto coefficients=load_coefficients(options.coeff_dir);
        const auto loaded_input=memh(options.input,12,true),loaded_expected=memh(options.expected,12,true);
        std::vector<std::int16_t> input(loaded_input.begin(),loaded_input.end()),expected(loaded_expected.begin(),loaded_expected.end());
        tb::Kernel kernel(coefficients,input.size());const auto shape=kernel.shape();require(expected.size()==shape.outputs,"expected-output length disagrees with full-tail geometry");
        // Checked admission and all page-touching/loading occur before timing.
        kernel.run_epoch_checked(input.data(),options.threshold);std::uint64_t checked_samples=compare(kernel.output(),expected,"initial checked admission");
        kernel.run_epoch(input.data(),options.threshold);checked_samples+=compare(kernel.output(),expected,"initial fast-kernel admission");
        std::uint64_t consumed_epochs=0;
        if(!options.verify_only)for(std::uint64_t e=0;e<options.warmup;++e) {kernel.run_epoch(input.data(),options.threshold);tb::consume_epoch(kernel.output().data(),shape.outputs,consumed_epochs++);}
        const Timer timer;const auto environment_json=environment(options.cpu);
        std::vector<Record> records(static_cast<std::size_t>(options.verify_only?0:options.trials));
        for(auto& record:records) {
            kernel.run_epoch_checked(input.data(),options.threshold);checked_samples+=compare(kernel.output(),expected,"pre-record checked admission");
            // No file I/O, allocation, oracle loop, or metrics computation here.
            // Thread CPU timestamps enclose the wall timestamps and timed loop.
            const auto cpu_before=timer.thread(),wall_before=timer.wall();
            for(std::uint64_t e=0;e<options.epochs;++e) {
                kernel.run_epoch(input.data(),options.threshold);
                tb::consume_epoch(kernel.output().data(),shape.outputs,consumed_epochs++);
            }
            const auto wall_after=timer.wall(),cpu_after=timer.thread();
            require(wall_after>wall_before&&cpu_after>=cpu_before,"invalid timer interval");
            record={wall_after-wall_before,cpu_after-cpu_before,tb::consumer_checksum()};
            // Check the actual last timed result before any new run overwrites it.
            checked_samples+=compare(kernel.output(),expected,"post-record last timed output");
            kernel.run_epoch_checked(input.data(),options.threshold);checked_samples+=compare(kernel.output(),expected,"post-record checked admission");
        }
        if(!options.output_samples.empty()) {
            std::ofstream samples(options.output_samples,std::ios::out);require(samples.good(),"cannot create output-samples");samples<<std::hex<<std::setfill('0');
            for(auto y:kernel.output()) {
                samples<<std::setw(3)<<(static_cast<std::uint16_t>(y)&0xfff)<<'\n';
            }
            samples.flush();
            require(samples.good(),"sample output write failed");
        }
        std::ostringstream json;json<<std::setprecision(17);
        json<<"{\n  \"schema\":\"trecap-preallocated-cpu-benchmark-1\",\n  \"status\":\"PASS_FUNCTIONAL_ADMISSION\",\n  \"verify_only\":"<<(options.verify_only?"true":"false")<<",\n  \"kernel\":\"scalar-source fixed-point full finite STFT/mask/IFFT/WOLA; compiler auto-vectorization allowed\",\n  \"contract\":{\"N\":12,\"L\":256,\"H\":128,\"F\":15,\"G\":128,\"D\":384,\"rounding\":\"nearest ties away from zero\",\"final_saturation_bits\":12,\"threshold_comparison\":\"strict mag2 < threshold; DC protected, Nyquist eligible\"},\n";
        json<<"  \"threshold2\":"<<options.threshold<<",\n  \"geometry\":{\"inputs_per_epoch\":"<<shape.inputs<<",\"frames_per_epoch\":"<<shape.frames<<",\"tau_last\":"<<shape.tau_last<<",\"outputs_per_epoch\":"<<shape.outputs<<"},\n";
        json<<"  \"epochs_per_trial\":"<<options.epochs<<",\n  \"trials\":"<<records.size()<<",\n  \"warmup_epochs\":"<<(options.verify_only?0:options.warmup)<<",\n  \"timed_total_epochs\":"<<records.size()*options.epochs<<",\n  \"timed_input_samples\":"<<records.size()*options.epochs*shape.inputs<<",\n  \"timed_output_samples\":"<<records.size()*options.epochs*shape.outputs<<",\n  \"timed_frames\":"<<records.size()*options.epochs*shape.frames<<",\n";
        json<<"  \"validation\":{\"mismatches\":0,\"full_output_samples_checked_outside_timing\":"<<checked_samples<<",\"internal_ranges_checked_outside_timing\":true,\"timed_kernel_internal_guards\":false,\"timed_kernel_assumption\":\"Repeated immutable admitted input, coefficients, and threshold; exact same arithmetic as checked instantiation\",\"last_timed_epoch_checked_each_record\":true,\"all_timed_epochs_individually_full_checked\":"<<(options.epochs==1?"true":"false")<<"},\n";
        json<<"  \"timing\":{\"wall_clock\":"<<quoted(timer.wall_name)<<",\"wall_resolution_ns\":"<<timer.wall_resolution_ns<<",\"thread_cpu_clock\":"<<quoted(timer.thread_name)<<",\"thread_cpu_resolution_ns\":"<<timer.thread_resolution_ns<<",\"includes\":[\"per-epoch logical state reset\",\"all finite input/tail/output work\",\"one opaque O(1) output consumer per epoch\"],\"excludes\":[\"file I/O\",\"allocations\",\"full output comparison\",\"coefficient validation\",\"reference quality/telemetry metric aggregation\",\"host transfers/JTAG\"],\"thread_timer_encloses_wall_timer\":true},\n";
        json<<"  \"environment\":"<<environment_json<<",\n  \"input_files\":{\"input\":"<<quoted(options.input)<<",\"expected\":"<<quoted(options.expected)<<",\"coefficient_directory\":"<<quoted(options.coeff_dir)<<",\"coefficient_names\":[\"window_qw.memh\",\"twiddle_re.memh\",\"twiddle_im.memh\",\"twiddle_inv_re.memh\",\"twiddle_inv_im.memh\"],\"hashes\":\"Retain external source/input/executable SHA256 manifest\"},\n  \"records\":[\n";
        for(std::size_t i=0;i<records.size();++i) {const auto& r=records[i];if(i)json<<",\n";json<<"    {\"trial\":"<<i+1<<",\"epochs\":"<<options.epochs<<",\"wall_ns\":"<<r.wall_ns<<",\"wall_s\":"<<r.wall_ns/1e9<<",\"wall_ns_per_epoch\":"<<static_cast<double>(r.wall_ns)/options.epochs<<",\"thread_cpu_ns\":";if(timer.thread_available)json<<r.thread_ns;else json<<"null";json<<",\"checksum\":"<<r.checksum<<",\"full_pre_post_validation\":true}";}
        json<<"\n  ],\n  \"final_consumer_checksum\":"<<tb::consumer_checksum()<<"\n}\n";
        std::ofstream output(options.output,std::ios::out);require(output.good(),"cannot create output JSON");output<<json.str();output.flush();require(output.good(),"JSON write failed");
        std::cout<<"PASS: "<<records.size()<<" timing records; "<<checked_samples<<" output samples checked outside timing. Result: "<<options.output<<'\n';return 0;
    }catch(const std::exception& e) {std::cerr<<"trecap_cpu_benchmark: "<<e.what()<<'\n';return 1;}
}
