#include "codec.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <intrin.h>
#endif

namespace fs=std::filesystem;
using namespace trecap;
using Clock=std::chrono::steady_clock;
static void check(bool value,const std::string& message) {if(!value) throw std::runtime_error(message);}
static std::string strip(std::string s) {
    if(!s.empty()&&s.back()=='\r') s.pop_back();
    if(s.size()>=3&&static_cast<unsigned char>(s[0])==0xef&&static_cast<unsigned char>(s[1])==0xbb&&static_cast<unsigned char>(s[2])==0xbf) s.erase(0,3);
    return s;
}
static std::vector<std::string> split(const std::string& s,char separator) {
    std::vector<std::string> out; std::istringstream in(s); std::string v;
    while(std::getline(in,v,separator)) out.push_back(v);
    if(!s.empty()&&s.back()==separator) out.emplace_back();
    return out;
}
static std::uint64_t number(const std::string& s) {
    check(!s.empty()&&s[0]!='-',"invalid unsigned integer: "+s);
    std::size_t pos=0; auto n=std::stoull(s,&pos,10);
    check(pos==s.size(),"integer has trailing characters: "+s);return n;
}
static fs::path utf8_path(const std::string& s) {
    return fs::path(std::u8string(reinterpret_cast<const char8_t*>(s.data()),s.size()));
}
static std::string quote(const std::string& s) {
    std::ostringstream out;out<<'"';
    for(unsigned char ch:s) {if(ch=='"'||ch=='\\')out<<'\\'<<ch;else if(ch=='\n')out<<"\\n";else if(ch=='\r')out<<"\\r";else if(ch=='\t')out<<"\\t";else if(ch<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<static_cast<int>(ch)<<std::dec;else out<<ch;}
    out<<'"';return out.str();
}
static std::string hex(std::uint64_t v) {std::ostringstream o;o<<std::hex<<std::setw(16)<<std::setfill('0')<<v;return o.str();}
static std::uint64_t file_hash(const fs::path& path) {
    std::ifstream in(path,std::ios::binary);check(bool(in),"cannot read "+path.string());
    std::uint64_t h=14695981039346656037ULL;char c;while(in.get(c)){h^=static_cast<unsigned char>(c);h*=1099511628211ULL;}return h;
}
static void write_le(Packet& p,std::size_t offset,std::uint64_t v,std::size_t n) {for(std::size_t i=0;i<n;++i)p.bytes[offset+i]=static_cast<std::uint8_t>(v>>(8*i));}
static void resign(Packet& p) {write_le(p,40,checksum(p.view()),8);}

struct SelfTest {std::size_t positive=0,negative=0;};
static SelfTest self_test() {
    SelfTest result;
    auto expect_reject=[&](const Packet& p,Expected e,Encoding encoding,const std::string& label) {
        bool rejected=false;try {if(encoding==Encoding::dense){Dense d;decode_dense(p.view(),e,d);}else{Sparse s;decode_sparse(p.view(),e,s);}}catch(const std::exception&){rejected=true;}
        check(rejected,"negative test accepted: "+label);++result.negative;
    };
    Dense zero{};Packet dense;encode_dense(zero,{42,0},dense);
    check(dense.size==952,"dense exact length");
    check(checksum(dense.view())==0x56da9bacea0f9f1eULL,"independent allzero dense golden checksum");
    check(dense.bytes[0]==0x54&&dense.bytes[1]==0x53&&dense.bytes[2]==0x50&&dense.bytes[3]==0x31&&dense.bytes[951]==0,"golden layout");
    Dense decoded;decode_dense(dense.view(),{42,0},decoded);check(decoded==zero,"zero roundtrip");++result.positive;
    Sparse dc;dc.count=1;dc.entries[0]=0;Packet sparse;encode_sparse(dc,{43,10},sparse);
    check(sparse.size==56&&checksum(sparse.view())==0x9479c3ec145354f2ULL,"independent protected zeroDC sparse golden");
    Sparse decoded_s;decode_sparse(sparse.view(),{43,10},decoded_s);check(decoded_s.count==1&&decoded_s.entries[0]==0,"protected zeroDC");++result.positive;
    for(std::uint64_t t:{0ULL,1ULL,256ULL,65536ULL,72057594037927935ULL,72057594037927936ULL}) {
        Dense original{},masked{};std::array<bool,bins> mask{};
        for(std::size_t k=0;k<bins;++k){original[k]=(k%3==0)?0:((k%3==1)?k*k:mag_mask);mask[k]=k!=0&&original[k]<t;masked[k]=mask[k]?0:original[k];}
        const auto s=make_sparse(original,mask);Packet p;encode_sparse(s,{9,t},p);Sparse r;decode_sparse(p.view(),{9,t},r);
        check(r.count==s.count&&std::equal(s.entries.begin(),s.entries.begin()+s.count,r.entries.begin()),"sparse extrema roundtrip");
        encode_dense(masked,{9,t},p);decode_dense(p.view(),{9,t},decoded);check(masked==decoded,"dense extrema roundtrip");
        Features f{},g{},independent{};consume_dense(masked,f);consume_sparse(s,g);
        for(std::size_t k=0;k<bins;++k)independent[16*k/129]+=(k==0||k==128)?masked[k]:2*masked[k];
        check(f==g&&f==independent,"band boundary/weight/extrema equality");++result.positive;
    }
    auto mutate_dense=[&](std::size_t offset,std::uint64_t value,std::size_t size,const char* name) {auto p=dense;write_le(p,offset,value,size);resign(p);expect_reject(p,{42,0},Encoding::dense,name);};
    mutate_dense(0,0,4,"magic");mutate_dense(4,2,2,"version");mutate_dense(6,1,2,"encoding");mutate_dense(8,2,4,"config");
    mutate_dense(12,904,4,"payload");mutate_dense(16,41,8,"frame");mutate_dense(24,1,8,"threshold");mutate_dense(32,128,2,"count");
    mutate_dense(34,0,2,"flags0");mutate_dense(34,3,2,"flags3");mutate_dense(36,1,4,"reserved");mutate_dense(951,1,1,"padding");
    auto p=dense;p.bytes[48]^=1;expect_reject(p,{42,0},Encoding::dense,"corruption");
    p=dense;--p.size;expect_reject(p,{42,0},Encoding::dense,"truncated");p=dense;++p.size;expect_reject(p,{42,0},Encoding::dense,"trailing");
    p=dense;p.size=47;expect_reject(p,{42,0},Encoding::dense,"short header");
    Dense low{};low[1]=1;encode_dense(low,{44,2},p);expect_reject(p,{44,2},Encoding::dense,"masked low dense value");
    Sparse two;two.count=2;two.entries[0]=0;two.entries[1]=(10ULL<<8)|1;Packet validtwo;encode_sparse(two,{43,10},validtwo);
    auto mutate_sparse=[&](std::size_t offset,std::uint64_t value,std::size_t size,const char* name) {auto q=validtwo;write_le(q,offset,value,size);resign(q);expect_reject(q,{43,10},Encoding::sparse,name);};
    mutate_sparse(48,1,8,"missingDC");mutate_sparse(56,10ULL<<8,8,"duplicateDC");mutate_sparse(56,(10ULL<<8)|129,8,"index129");
    mutate_sparse(56,(9ULL<<8)|1,8,"belowthreshold");mutate_sparse(32,0,2,"empty sparse");mutate_sparse(32,130,2,"too many");
    Sparse three;three.count=3;three.entries[0]=0;three.entries[1]=(10ULL<<8)|2;three.entries[2]=(10ULL<<8)|1;encode_sparse(three,{43,10},p);expect_reject(p,{43,10},Encoding::sparse,"descending");
    encode_sparse(dc,{43,0},p);expect_reject(p,{43,0},Encoding::sparse,"threshold zero missing zero bins");
    for(auto count:{std::size_t{0},std::size_t{130}}){Sparse invalid;invalid.count=count;bool rejected=false;try{encode_sparse(invalid,{1,1},p);}catch(const std::exception&){rejected=true;}check(rejected,"encoder invalid count accepted");++result.negative;}
    std::cout<<"self-test PASS: "<<result.positive<<" positive, "<<result.negative<<" negative checks\n";return result;
}

struct Frame {
    std::uint64_t id=0;
    Dense original{};
    std::array<bool,bins> mask{};
    Dense dense{};
    Sparse sparse{};
    Features expected{};
    Packet dense_packet{},sparse_packet{};
};
struct Case {
    std::string id,signal;std::uint64_t threshold=0;fs::path bins_path,features_path;
    std::vector<Frame> frames;
    std::uint64_t dense_bytes=0,sparse_bytes=0,dense_hash=0,sparse_hash=0,feature_hash=0;
    std::size_t kept=0;
};
static std::map<std::string,std::size_t> columns(const std::string& line,char delimiter) {
    std::map<std::string,std::size_t> out;const auto names=split(strip(line),delimiter);
    for(std::size_t i=0;i<names.size();++i){check(out.emplace(names[i],i).second,"duplicate column "+names[i]);}return out;
}
static std::string field(const std::vector<std::string>& row,const std::map<std::string,std::size_t>& col,const std::string& name) {
    const auto it=col.find(name);check(it!=col.end(),"missing column "+name);check(it->second<row.size(),"short row at "+name);return row[it->second];
}
static void load_case(Case& c) {
    std::ifstream in(c.bins_path);check(bool(in),"cannot open "+c.bins_path.string());std::string line;check(bool(std::getline(in,line)),"empty bin fixture");const auto col=columns(line,',');
    Dense original{};std::array<bool,bins> mask{};std::size_t next=0;std::uint64_t id=0;bool first=true;
    while(std::getline(in,line)) {
        line=strip(line);if(line.empty())continue;auto row=split(line,',');const auto fid=number(field(row,col,"frame_idx"));const auto k=number(field(row,col,"bin_idx"));
        if(next==0){check(first||fid>id,"frame IDs must strictly increase");id=fid;first=false;}
        check(fid==id&&k==next,"missing/duplicate/out-of-order bin in fixture");
        const auto mag=number(field(row,col,"mag2"));check(mag<=mag_mask,"fixture magnitude exceeds u56");const auto m=number(field(row,col,"mask"));check(m<=1,"invalid fixture mask");
        const auto eligible=number(field(row,col,"eligible"));check(eligible==(k!=0?1ULL:0ULL),"fixture protection contract mismatch");
        check(m==((k!=0&&mag<c.threshold)?1ULL:0ULL),"fixture mask differs from frozen threshold contract");
        original[next]=mag;mask[next]=m!=0;++next;
        if(next==bins){Frame f;f.id=id;f.original=original;f.mask=mask;for(std::size_t j=0;j<bins;++j)f.dense[j]=mask[j]?0:original[j];f.sparse=make_sparse(original,mask);encode_dense(f.dense,{id,c.threshold},f.dense_packet);encode_sparse(f.sparse,{id,c.threshold},f.sparse_packet);c.frames.push_back(f);next=0;}
    }
    check(next==0&&!c.frames.empty(),"incomplete/empty fixture");
    std::ifstream expected(c.features_path);check(bool(expected),"cannot open expected features");check(bool(std::getline(expected,line)),"empty expected features");const auto ec=columns(line,',');std::size_t index=0;
    while(std::getline(expected,line)){line=strip(line);if(line.empty())continue;const auto row=split(line,',');check(index<c.frames.size(),"too many expected feature frames");auto& f=c.frames[index++];check(number(field(row,ec,"frame_idx"))==f.id,"expected feature frame ID mismatch");for(std::size_t b=0;b<bands;++b)f.expected[b]=number(field(row,ec,"band"+std::to_string(b)));}
    check(index==c.frames.size(),"missing expected features");
    c.dense_hash=c.sparse_hash=c.feature_hash=14695981039346656037ULL;
    for(const auto& f:c.frames){
        Dense d;Sparse s;decode_dense(f.dense_packet.view(),{f.id,c.threshold},d);decode_sparse(f.sparse_packet.view(),{f.id,c.threshold},s);check(d==f.dense,"initial dense roundtrip");check(s.count==f.sparse.count&&std::equal(s.entries.begin(),s.entries.begin()+s.count,f.sparse.entries.begin()),"initial sparse roundtrip");
        Features a{},b{};consume_dense(d,a);consume_sparse(s,b);check(a==f.expected&&b==f.expected,"independent expected feature mismatch: "+c.id);
        c.dense_bytes+=f.dense_packet.size;c.sparse_bytes+=f.sparse_packet.size;c.kept+=s.count;
        c.dense_hash=(c.dense_hash^byte_hash(f.dense_packet.view()))*1099511628211ULL;c.sparse_hash=(c.sparse_hash^byte_hash(f.sparse_packet.view()))*1099511628211ULL;
        for(auto v:f.expected)c.feature_hash=(c.feature_hash^v)*1099511628211ULL;
    }
}
static std::vector<Case> load_cases(const fs::path& list) {
    std::ifstream in(list);check(bool(in),"cannot open case TSV");std::string line;check(bool(std::getline(in,line)),"empty case TSV");auto col=columns(line,'\t');std::vector<Case> out;std::map<std::string,bool> ids;
    while(std::getline(in,line)){line=strip(line);if(line.empty())continue;auto row=split(line,'\t');Case c;c.id=field(row,col,"case_id");c.signal=field(row,col,"signal_id");c.threshold=number(field(row,col,"threshold"));c.bins_path=utf8_path(field(row,col,"bin_stats"));c.features_path=utf8_path(field(row,col,"expected_features"));check(ids.emplace(c.id,true).second,"duplicate case ID");check(c.id.find_first_of(",\r\n\"/\\")==std::string::npos&&c.signal.find_first_of(",\r\n\"")==std::string::npos,"case ID contains unsafe CSV/path syntax");load_case(c);out.push_back(std::move(c));}
    check(!out.empty(),"no cases");return out;
}

enum class Stage{encode,decode,consumer,receive_consumer,complete};
constexpr std::array<Stage,5> stages={Stage::encode,Stage::decode,Stage::consumer,Stage::receive_consumer,Stage::complete};
static const char* name(Stage s){switch(s){case Stage::encode:return "encode";case Stage::decode:return "decode";case Stage::consumer:return "consumer";case Stage::receive_consumer:return "receive_consumer";default:return "complete";}}
struct Workspace {std::vector<Packet> packets;std::vector<Dense> dense;std::vector<Sparse> sparse;std::vector<Features> features;explicit Workspace(std::size_t n):packets(n),dense(n),sparse(n),features(n){}};
static std::int64_t timed(const Case& c,bool sparse,Stage stage,std::size_t repeats,Workspace& w) {
    const auto start=Clock::now();
    for(std::size_t repeat=0;repeat<repeats;++repeat)for(std::size_t i=0;i<c.frames.size();++i){
        const auto& f=c.frames[i];const Expected e{f.id,c.threshold};
        if(stage==Stage::encode||stage==Stage::complete){if(sparse){prepare_sparse(f.original,f.mask,w.sparse[i]);encode_sparse(w.sparse[i],e,w.packets[i]);}else{for(std::size_t k=0;k<bins;++k)w.dense[i][k]=f.mask[k]?0:f.original[k];encode_dense(w.dense[i],e,w.packets[i]);}}
        if(stage==Stage::decode||stage==Stage::receive_consumer||stage==Stage::complete){const auto& p=stage==Stage::complete?w.packets[i]:(sparse?f.sparse_packet:f.dense_packet);if(sparse)decode_sparse(p.view(),e,w.sparse[i]);else decode_dense(p.view(),e,w.dense[i]);}
        if(stage==Stage::consumer){if(sparse)consume_sparse(f.sparse,w.features[i]);else consume_dense(f.dense,w.features[i]);}
        if(stage==Stage::receive_consumer||stage==Stage::complete){if(sparse)consume_sparse(w.sparse[i],w.features[i]);else consume_dense(w.dense[i],w.features[i]);}
        if(stage==Stage::encode)observe(w.packets[i].bytes.data(),w.packets[i].size);
        else if(stage==Stage::decode){if(sparse)observe(w.sparse[i].entries.data(),w.sparse[i].count*sizeof(std::uint64_t));else observe(w.dense[i].data(),sizeof(Dense));}
        else observe(w.features[i].data(),sizeof(Features));
    }
    const auto stop=Clock::now();
    return std::chrono::duration_cast<std::chrono::nanoseconds>(stop-start).count();
}
static void validate_outputs(const Case& c,bool sparse,Stage stage,const Workspace& w) {
    for(std::size_t i=0;i<c.frames.size();++i){const auto& f=c.frames[i];
        if(stage==Stage::encode||stage==Stage::complete){const auto& expected=sparse?f.sparse_packet:f.dense_packet;check(w.packets[i].size==expected.size&&std::equal(expected.bytes.begin(),expected.bytes.begin()+expected.size,w.packets[i].bytes.begin()),"post-timing packet bytes differ: "+c.id);}
        if(stage==Stage::decode||stage==Stage::receive_consumer||stage==Stage::complete){Features features{};if(sparse){check(w.sparse[i].count==f.sparse.count&&std::equal(f.sparse.entries.begin(),f.sparse.entries.begin()+f.sparse.count,w.sparse[i].entries.begin()),"post-timing sparse decode differs");consume_sparse(w.sparse[i],features);}else{check(w.dense[i]==f.dense,"post-timing dense decode differs");consume_dense(w.dense[i],features);}check(features==f.expected,"post-timing decoded feature differs");}
        if(stage==Stage::consumer||stage==Stage::receive_consumer||stage==Stage::complete)check(w.features[i]==f.expected,"post-timing consumer feature differs: "+c.id);
    }
}
static std::size_t calibrate(const Case& c,Workspace& w) {
    std::size_t repeats=16;
    while(true){const auto b=timed(c,false,Stage::complete,repeats,w);validate_outputs(c,false,Stage::complete,w);const auto s=timed(c,true,Stage::complete,repeats,w);validate_outputs(c,true,Stage::complete,w);if(std::max(b,s)>=10000000||repeats==4096)break;repeats=std::min(std::size_t{4096},repeats*2);}
    return repeats;
}
static std::string cpu_name() {
#if defined(_MSC_VER) && (defined(_M_X64) || defined(_M_IX86))
    int info[4];__cpuid(info,static_cast<int>(0x80000000));if(static_cast<unsigned>(info[0])>=0x80000004){char brand[49]{};for(int j=0;j<3;++j){__cpuid(info,static_cast<int>(0x80000002)+j);std::memcpy(brand+16*j,info,16);}return brand;}
#endif
#ifdef _WIN32
    char identifier[256]{};const auto length=GetEnvironmentVariableA("PROCESSOR_IDENTIFIER",identifier,sizeof(identifier));return length&&length<sizeof(identifier)?identifier:"unavailable";
#else
    const char* identifier=std::getenv("PROCESSOR_IDENTIFIER");return identifier?identifier:"unavailable";
#endif
}
static double percentile(std::vector<double> values,double p){std::sort(values.begin(),values.end());const double x=p*(values.size()-1);const auto a=static_cast<std::size_t>(x);const auto b=std::min(a+1,values.size()-1);return values[a]+(values[b]-values[a])*(x-a);}
static std::string compiler() {
#ifdef _MSC_FULL_VER
    return "MSVC "+std::to_string(_MSC_FULL_VER);
#elif defined(__clang__)
    return std::string("Clang ")+__clang_version__;
#elif defined(__GNUC__)
    return std::string("GCC ")+__VERSION__;
#else
    return "unknown";
#endif
}
static void benchmark(std::vector<Case>& cases,const fs::path& case_file,const fs::path& out,SelfTest test) {
#ifndef NDEBUG
    throw std::runtime_error("Use an optimized Release build for timing");
#endif
    check(!fs::exists(out),"output directory already exists; use a fresh --out");fs::create_directories(out);
    std::ofstream raw(out/"raw_trials.csv");check(bool(raw),"cannot create raw CSV");
    raw.exceptions(std::ios::failbit|std::ios::badbit);
    raw<<"case_id,signal_id,threshold,trial,warmup,pair_order,stage,mode,baseline_role,repeats,frames,total_frames,duration_ns,ns_per_frame,bytes_per_pass,packet_hash,feature_hash\n"<<std::setprecision(17);
    std::ofstream summary(out/"summary.json");summary<<std::setprecision(17)<<"{\n  \"schema\": \"trecap_sparse_benchmark_v1\",\n  \"cases\": [\n";
    summary.exceptions(std::ios::failbit|std::ios::badbit);
    std::size_t validations=0,records=0;
    fs::create_directories(out/"packets");
    for(const auto& c:cases){for(bool sparse:{false,true}){std::ofstream packets(out/"packets"/(c.id+(sparse?"_sparse.bin":"_dense.bin")),std::ios::binary);check(bool(packets),"cannot export packet corpus");for(const auto& f:c.frames){const auto& p=sparse?f.sparse_packet:f.dense_packet;packets.write(reinterpret_cast<const char*>(p.bytes.data()),static_cast<std::streamsize>(p.size));}check(bool(packets),"packet export write failed");}}
    for(std::size_t ci=0;ci<cases.size();++ci){auto& c=cases[ci];Workspace w(c.frames.size());const auto repeats=calibrate(c,w);std::map<std::string,std::vector<double>> measurements;
        std::cout<<"benchmark "<<ci+1<<"/"<<cases.size()<<" "<<c.id<<" frames="<<c.frames.size()<<" repeats="<<repeats<<std::endl;
        for(int trial=-3;trial<30;++trial){const bool warmup=trial<0;const bool sparse_first=((trial+3)%2)!=0;for(auto stage:stages){for(int order=0;order<2;++order){const bool sparse=order==0?sparse_first:!sparse_first;const auto ns=timed(c,sparse,stage,repeats,w);validate_outputs(c,sparse,stage,w);++validations;const auto total=repeats*c.frames.size();const double per=static_cast<double>(ns)/static_cast<double>(total);const std::string mode=sparse?"C":"B";if(!warmup)measurements[std::string(name(stage))+"_"+mode].push_back(per);
            raw<<c.id<<','<<c.signal<<','<<c.threshold<<','<<trial<<','<<(warmup?1:0)<<','<<order<<','<<name(stage)<<','<<mode<<','<<(!sparse&&c.threshold==0?"A_unmasked_dense":"masked")<<','<<repeats<<','<<c.frames.size()<<','<<total<<','<<ns<<','<<per<<','<<(sparse?c.sparse_bytes:c.dense_bytes)<<','<<hex(sparse?c.sparse_hash:c.dense_hash)<<','<<hex(c.feature_hash)<<'\n';++records;
        }}raw.flush();}
        if(ci)summary<<",\n";summary<<"    {\"case_id\": "<<quote(c.id)<<", \"signal_id\": "<<quote(c.signal)<<", \"threshold\": "<<c.threshold<<", \"frames\": "<<c.frames.size()<<", \"repeats\": "<<repeats<<", \"retained_entries\": "<<c.kept<<", \"dense_bytes\": "<<c.dense_bytes<<", \"sparse_bytes\": "<<c.sparse_bytes<<", \"bin_stats_fnv1a64\": "<<quote(hex(file_hash(c.bins_path)))<<", \"expected_features_fnv1a64\": "<<quote(hex(file_hash(c.features_path)))<<", \"timings_ns_per_frame\": {";
        bool comma=false;for(const auto& [key,values]:measurements){if(comma)summary<<',';comma=true;summary<<'\n'<<"      "<<quote(key)<<": {\"median\": "<<percentile(values,0.5)<<", \"p25\": "<<percentile(values,0.25)<<", \"p75\": "<<percentile(values,0.75)<<", \"p95\": "<<percentile(values,0.95)<<", \"n\": "<<values.size()<<'}';}summary<<"\n    }}";summary.flush();
    }
    summary<<"\n  ]\n}\n";summary.close();raw.close();
    std::ofstream metadata(out/"qualification.json");metadata<<"{\n  \"status\": \"PASS\",\n  \"scope\": \"Host CPU RAM-only software replay; not FPGA, ARM, transport, AI inference, CPU utilization or energy measurement\",\n  \"compiler\": "<<quote(compiler())<<",\n  \"cpu\": "<<quote(cpu_name())<<",\n  \"logical_processors\": "<<std::thread::hardware_concurrency()<<",\n  \"pointer_bits\": "<<sizeof(void*)*8<<",\n  \"timer\": \"std::chrono::steady_clock monotonic wall elapsed\",\n  \"clock_is_steady\": "<<(Clock::is_steady?"true":"false")<<",\n  \"clock_period_numerator\": "<<Clock::period::num<<",\n  \"clock_period_denominator\": "<<Clock::period::den<<",\n";
#ifdef _WIN32
    LARGE_INTEGER frequency;QueryPerformanceFrequency(&frequency);metadata<<"  \"windows_qpc_frequency_hz\": "<<frequency.QuadPart<<",\n";
#endif
    metadata<<"  \"build\": \"Release optimized C++20; separate translation units; LTO disabled\",\n  \"affinity\": \"OS default, no thread pinning\",\n  \"threads_in_benchmark\": 1,\n  \"warmup_trials_per_case_stage_mode\": 3,\n  \"measured_trials_per_case_stage_mode\": 30,\n  \"calibration\": \"Common repeat count for B/C and all stages; slower complete stage target >=10ms, repeats16..4096\",\n  \"timing_inclusions\": \"Encode includes preparing masked dense or scanning/gathering sparse from the same original magnitudes plus mask flags. Codec stages include FNV integrity checks; all stages include one identical opaque output observer call per frame. Full pipeline includes preparation, encode, decode validation, and consume. Consumer inputs are already decoded.\",\n  \"timing_exclusions\": \"Source FFT/IFFT, file IO, allocations, setup, transport, output validation, AI inference\",\n  \"validation_boundary\": \"Every timed trial compares final repetition of every frame outside timing. All repetitions invoke opaque observer on real output memory; intermediate repetitions are not individually fully compared. Encode compares exact bytes; decode compares every value/index and features; applicable consumer stages compare all16 expected integer features.\",\n  \"baseline_A\": \"Threshold0 dense B measurements serve as unmasked A baseline; A is not redundantly rerun.\",\n  \"case_count\": "<<cases.size()<<",\n  \"raw_record_count\": "<<records<<",\n  \"successful_timed_trial_validations\": "<<validations<<",\n  \"self_test_positive\": "<<test.positive<<",\n  \"self_test_negative\": "<<test.negative<<",\n  \"case_file_fnv1a64\": "<<quote(hex(file_hash(case_file)))<<",\n  \"raw_trials_fnv1a64\": "<<quote(hex(file_hash(out/"raw_trials.csv")))<<",\n  \"observer_final\": "<<quote(hex(observer_value()))<<"\n}\n";
    metadata.close();check(bool(metadata),"qualification write failed");
    std::cout<<"PASS: "<<records<<" timed trial records; outputs in "<<out.string()<<std::endl;
}
int main(int argc,char** argv) {
    try {
        if(argc==2&&std::string(argv[1])=="--self-test"){self_test();return 0;}
        fs::path list,out;bool validate_only=false;
        for(int i=1;i<argc;++i){const std::string arg=argv[i];if(arg=="--cases"&&i+1<argc)list=utf8_path(argv[++i]);else if(arg=="--out"&&i+1<argc)out=utf8_path(argv[++i]);else if(arg=="--validate-only")validate_only=true;else throw std::runtime_error("Usage: --self-test OR --cases cases.tsv [--validate-only | --out fresh-directory]");}
        check(!list.empty(),"--cases is required");auto tests=self_test();auto cases=load_cases(list);std::cout<<"Validated "<<cases.size()<<" cases against independent expected features"<<std::endl;
        if(validate_only)return 0;check(!out.empty(),"--out fresh-directory is required");benchmark(cases,list,out,tests);return 0;
    }catch(const std::exception& e){std::cerr<<"ERROR: "<<e.what()<<std::endl;return 1;}
}
