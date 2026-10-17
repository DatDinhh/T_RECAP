#include <cstring>
#include "../../trecap_laptop_fpga_v01/cpu/shared.hpp"
#include "../../trecap_downstream8_v01/native/codec.hpp"

// The included shared.hpp supplies the frozen coefficient loader and CPU02
// arithmetic. No affinity helper or old CLI entry point is called here.
namespace {
constexpr uint64_t sample_limit=120ULL*48000;
thread_local std::string last_error;
struct State {
    cpu02::Kernel kernel;
    cpu02::Frame ring{},frame{},z{};
    std::array<int64_t,384> ola{};
    std::vector<int32_t> y;
    std::vector<uint8_t> wire;
    std::vector<uint64_t> features;
    uint64_t capacity,frames=0,y_count=0,wire_count=0;
    bool valid=false,full=false;
    explicit State(const char*coeff,uint64_t cap):capacity(cap) {
        need(coeff&&cap&&cap<=sample_limit&&cap%128==0,"capacity must be positive multiple128 up to5760000");
        Runner loader(coeff);kernel=loader.kernel;
        y.resize(size_t(cap+512));wire.resize(size_t((cap/128+1)*1080));features.resize(size_t((cap/128+1)*16));
    }
    void invalidate(){valid=false;full=false;frames=y_count=wire_count=0;}
    void epoch(const int32_t*input,uint64_t ns,uint64_t threshold,bool want_full) {
        invalidate();need(input&&ns&&ns<=capacity&&ns%128==0,"input pointer/length");
        need(reinterpret_cast<uintptr_t>(input)%alignof(int32_t)==0,"unaligned int32 input");
        need(threshold<(1ULL<<56),"threshold exceeds unsigned56");
        for(uint64_t i=0;i<ns;i++)need(input[i]>=-2048&&input[i]<=2047,"input exceeds signed12");
        ring.fill(0);frame.fill(0);ola.fill(0);size_t wr=0,rd=0,frame_id=0;
        const uint64_t ny=ns+512,analysis_end=ns+128,total=want_full?ny:analysis_end;
        trecap::Sparse sparse;trecap::Packet packet;
        for(uint64_t n=0;n<total;n++) {
            ring[wr]=n<ns?input[n]:0;wr=(wr+1)%256;
            if(want_full){y[size_t(n)]=int32_t(cpu02::saturate12(cpu02::round_shift<15>(ola[rd])));ola[rd]=0;rd=(rd+1)%384;}
            if((n+1)%128!=0||n+1>analysis_end)continue;
            for(size_t i=0;i<256;i++)frame[i]=ring[(wr+i)%256];
            kernel.analyze(frame);auto& canonical=kernel.canonical;
            auto*out=features.data()+16*frame_id;std::fill_n(out,16,uint64_t{0});sparse.count=0;
            for(unsigned k=0;k<129;k++) {
                const auto re=canonical[k].re,im=canonical[k].im;
                const uint64_t magnitude=uint64_t(re*re)+uint64_t(im*im);need(magnitude<(1ULL<<56),"magnitude width");
                const bool keep=k==0||magnitude>=threshold;
                if(keep){out[(16*k)/129]+=(k==0||k==128)?magnitude:2*magnitude;if(want_full)sparse.entries[sparse.count++]=(magnitude<<8)|k;}
                else if(want_full){canonical[k]={0,0};if(k!=128)canonical[256-k]={0,0};}
            }
            if(want_full){
                trecap::encode_sparse(sparse,{frame_id,threshold},packet);
                need(wire_count+packet.size<=wire.size(),"packet buffer bound");
                std::memcpy(wire.data()+wire_count,packet.bytes.data(),packet.size);wire_count+=packet.size;
                kernel.synthesize(z);
                for(size_t i=0;i<256;i++){const size_t pos=(rd+128+i)%384;ola[pos]=cpu02::fit<37>(ola[pos]+z[i]);}
            }
            ++frame_id;
        }
        need(frame_id==ns/128+1,"frame total");frames=frame_id;y_count=want_full?ny:0;full=want_full;valid=true;
    }
    static uint64_t le(const uint8_t*p,unsigned n){uint64_t v=0;for(unsigned i=0;i<n;i++)v|=uint64_t(p[i])<<(8*i);return v;}
    void decode(const uint8_t*data,uint64_t nbytes,uint64_t expected_frames,uint64_t threshold) {
        invalidate();need(data&&expected_frames&&expected_frames<=capacity/128+1,"decode pointer/frame bound");
        need(threshold<(1ULL<<56)&&nbytes>=56*expected_frames&&nbytes<=1080*expected_frames,"decode threshold/byte bounds");
        size_t offset=0;trecap::Dense dense;trecap::Sparse sparse;trecap::Features bands;
        for(uint64_t f=0;f<expected_frames;f++) {
            need(nbytes-offset>=48,"truncated header");const auto*p=data+offset;
            const uint64_t length=(48+le(p+12,4)+7)&~uint64_t{7};
            need(length<=1080&&length<=nbytes-offset,"packet size");const std::span<const uint8_t> packet(p,size_t(length));
            const auto encoding=le(p+6,2);
            if(encoding==0){trecap::decode_dense(packet,{f,threshold},dense);trecap::consume_dense(dense,bands);}
            else{need(encoding==1,"unknown encoding");trecap::decode_sparse(packet,{f,threshold},sparse);trecap::consume_sparse(sparse,bands);}
            std::copy(bands.begin(),bands.end(),features.begin()+size_t(f*16));offset+=size_t(length);
        }
        need(offset==nbytes,"trailing packet bytes");frames=expected_frames;valid=true;
    }
};
State& state(void*p){need(p!=nullptr,"null context");return *static_cast<State*>(p);}
template<class F> int checked_call(void*p,F fn) noexcept {
    try{state(p).invalidate();fn(state(p));last_error.clear();return 0;}
    catch(const std::exception&e){if(p)static_cast<State*>(p)->invalidate();last_error=e.what();return -1;}
    catch(...){if(p)static_cast<State*>(p)->invalidate();last_error="unknown native error";return -1;}
}
}
#define API extern "C" __declspec(dllexport)
API uint32_t tsa_version(){return 0x00010000;}
API void* tsa_create(const char*coeff,uint64_t max_samples){try{auto*p=new State(coeff,max_samples);last_error.clear();return p;}catch(const std::exception&e){last_error=e.what();return nullptr;}catch(...){last_error="unknown creation error";return nullptr;}}
API int tsa_full(void*p,const int32_t*input,uint64_t ns,uint64_t threshold){return checked_call(p,[&](State&s){s.epoch(input,ns,threshold,true);});}
API int tsa_spectral(void*p,const int32_t*input,uint64_t ns,uint64_t threshold){return checked_call(p,[&](State&s){s.epoch(input,ns,threshold,false);});}
API int tsa_decode(void*p,const uint8_t*data,uint64_t bytes,uint64_t frames,uint64_t threshold){return checked_call(p,[&](State&s){s.decode(data,bytes,frames,threshold);});}
API const uint64_t* tsa_features(void*p){auto*s=static_cast<State*>(p);return s&&s->valid?s->features.data():nullptr;}
API uint64_t tsa_frames(void*p){auto*s=static_cast<State*>(p);return s&&s->valid?s->frames:0;}
API const int32_t* tsa_y(void*p){auto*s=static_cast<State*>(p);return s&&s->valid&&s->full?s->y.data():nullptr;}
API uint64_t tsa_y_count(void*p){auto*s=static_cast<State*>(p);return s&&s->valid&&s->full?s->y_count:0;}
API const uint8_t* tsa_tsp1(void*p){auto*s=static_cast<State*>(p);return s&&s->valid&&s->full?s->wire.data():nullptr;}
API uint64_t tsa_tsp1_bytes(void*p){auto*s=static_cast<State*>(p);return s&&s->valid&&s->full?s->wire_count:0;}
API const char* tsa_error(){return last_error.c_str();}
API void tsa_destroy(void*p){delete static_cast<State*>(p);}
