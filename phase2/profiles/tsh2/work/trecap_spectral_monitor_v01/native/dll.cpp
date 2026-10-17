#include <cstring>
#include "../../trecap_laptop_fpga_v01/cpu/shared.hpp"
#include "../../trecap_downstream8_v01/native/codec.hpp"

namespace {
constexpr uint64_t sample_limit=120ULL*48000, columns=21;
thread_local std::string last_error;
using Monitor=std::array<uint64_t,columns>;
void clear(Monitor& o){o.fill(0);o[19]=UINT64_MAX;}
void add(Monitor& o,unsigned k,uint64_t magnitude){
    const uint64_t w=(k==0||k==128)?magnitude:2*magnitude;
    o[16]+=w;o[(16*k)/129]+=w;
    uint64_t hi=0;const uint64_t lo=_umul128(w,k,&hi),old=o[17];
    o[17]+=lo;o[20]+=hi+(o[17]<old);
    if(magnitude>o[18]){o[18]=magnitude;o[19]=k;}
}
void consume(const trecap::Dense& d,Monitor& o){clear(o);for(unsigned k=0;k<129;k++)add(o,k,d[k]);}
void consume(const trecap::Sparse& s,Monitor& o){clear(o);for(size_t i=0;i<s.count;i++)add(o,unsigned(s.entries[i]&255),s.entries[i]>>8);}
struct State {
    cpu02::Kernel kernel;
    cpu02::Frame ring{},frame{};
    std::vector<uint8_t> wire;
    std::vector<uint64_t> features,spectra;
    uint64_t capacity,frames=0,wire_count=0;
    bool valid=false,has_wire=false,has_spectra=false;
    explicit State(const char*coeff,uint64_t cap):capacity(cap){
        need(coeff&&cap&&cap<=sample_limit&&cap%128==0,"capacity must be positive multiple128 up to5760000");
        Runner loader(coeff);kernel=loader.kernel;
        const size_t nf=size_t(cap/128+1);
        wire.resize(nf*1080);features.resize(nf*columns);spectra.resize(nf*129);
    }
    void invalidate(){valid=has_wire=has_spectra=false;frames=wire_count=0;}
    void store(uint64_t f,const Monitor& m){std::copy(m.begin(),m.end(),features.begin()+size_t(f*columns));}
    void emit(const trecap::Packet& p){need(wire_count+p.size<=wire.size(),"wire bound");std::memcpy(wire.data()+wire_count,p.bytes.data(),p.size);wire_count+=p.size;}
    static uint64_t le(const uint8_t*p,unsigned n){uint64_t v=0;for(unsigned i=0;i<n;i++)v|=uint64_t(p[i])<<(8*i);return v;}
    void decode(const uint8_t*data,uint64_t bytes,uint64_t nf,uint64_t thr,unsigned encoding,bool prepare){
        invalidate();need(data&&nf&&nf<=capacity/128+1,"decode pointer/frame bound");
        need(thr<(1ULL<<56)&&bytes>=56*nf&&bytes<=1080*nf,"decode threshold/byte bounds");
        need(encoding<=1,"invalid expected encoding");
        uint64_t offset=0;trecap::Dense dense;trecap::Sparse sparse;Monitor m;trecap::Packet packet;
        for(uint64_t f=0;f<nf;f++){
            need(bytes-offset>=48,"truncated header");const auto*p=data+offset;
            const uint64_t len=(48+le(p+12,4)+7)&~uint64_t{7};need(len<=1080&&len<=bytes-offset,"packet size");
            std::span<const uint8_t> view(p,size_t(len));
            if(encoding==0){trecap::decode_dense(view,{f,thr},dense);consume(dense,m);}
            else {trecap::decode_sparse(view,{f,thr},sparse);consume(sparse,m);}
            store(f,m);
            if(prepare){
                if(encoding==1){dense.fill(0);for(size_t i=0;i<sparse.count;i++)dense[size_t(sparse.entries[i]&255)]=sparse.entries[i]>>8;}
                std::copy(dense.begin(),dense.end(),spectra.begin()+size_t(f*129));
                trecap::encode_dense(dense,{f,thr},packet);emit(packet);
            }
            offset+=len;
        }
        need(offset==bytes,"trailing packet bytes");frames=nf;valid=true;has_wire=has_spectra=prepare;
    }
    void pcm(const int32_t*input,uint64_t ns,uint64_t thr,bool produce){
        invalidate();need(input&&ns&&ns<=capacity&&ns%128==0,"input pointer/length");
        need(reinterpret_cast<uintptr_t>(input)%alignof(int32_t)==0,"unaligned int32 input");
        need(thr<(1ULL<<56),"threshold exceeds unsigned56");
        for(uint64_t i=0;i<ns;i++)need(input[i]>=-2048&&input[i]<=2047,"input exceeds signed12");
        ring.fill(0);frame.fill(0);size_t wr=0;uint64_t f=0;Monitor m;trecap::Sparse sparse;trecap::Packet packet;
        for(uint64_t n=0;n<ns+128;n++){
            ring[wr]=n<ns?input[n]:0;wr=(wr+1)%256;
            if((n+1)%128)continue;
            for(size_t i=0;i<256;i++)frame[i]=ring[(wr+i)%256];
            kernel.analyze(frame);clear(m);sparse.count=0;
            for(unsigned k=0;k<129;k++){
                const auto re=kernel.canonical[k].re,im=kernel.canonical[k].im;
                const uint64_t mag=uint64_t(re*re)+uint64_t(im*im);need(mag<(1ULL<<56),"magnitude width");
                const bool keep=k==0||mag>=thr;
                if(keep){add(m,k,mag);if(produce)sparse.entries[sparse.count++]=(mag<<8)|k;}
                if(produce)spectra[size_t(f*129+k)]=keep?mag:0;
            }
            store(f,m);if(produce){trecap::encode_sparse(sparse,{f,thr},packet);emit(packet);}++f;
        }
        need(f==ns/128+1,"frame total");frames=f;valid=true;has_wire=has_spectra=produce;
    }
    void matrix(const uint64_t*data,uint64_t nf){
        invalidate();need(data&&nf&&nf<=capacity/128+1,"matrix pointer/frame bound");
        trecap::Dense d;Monitor m;
        for(uint64_t f=0;f<nf;f++){
            std::copy_n(data+129*f,129,d.begin());for(auto v:d)need(v<=trecap::mag_mask,"matrix magnitude exceeds unsigned56");
            consume(d,m);store(f,m);
        }
        frames=nf;valid=true;
    }
};
State& state(void*p){need(p!=nullptr,"null context");return *static_cast<State*>(p);}
template<class F>int checked(void*p,F fn)noexcept{try{state(p).invalidate();fn(state(p));last_error.clear();return 0;}catch(const std::exception&e){if(p)static_cast<State*>(p)->invalidate();last_error=e.what();return -1;}catch(...){if(p)static_cast<State*>(p)->invalidate();last_error="unknown native error";return -1;}}
}
#define API extern "C" __declspec(dllexport)
API uint32_t tsm_version(){return 0x10000;}
API void* tsm_create(const char*coeff,uint64_t cap){try{auto*p=new State(coeff,cap);last_error.clear();return p;}catch(const std::exception&e){last_error=e.what();return nullptr;}catch(...){last_error="unknown creation error";return nullptr;}}
API int tsm_decode(void*p,const uint8_t*data,uint64_t bytes,uint64_t frames,uint64_t threshold,unsigned encoding,int prepare){return checked(p,[&](State&s){s.decode(data,bytes,frames,threshold,encoding,prepare!=0);});}
API int tsm_pcm(void*p,const int32_t*input,uint64_t ns,uint64_t threshold,int produce){return checked(p,[&](State&s){s.pcm(input,ns,threshold,produce!=0);});}
API int tsm_matrix(void*p,const uint64_t*data,uint64_t nf){return checked(p,[&](State&s){s.matrix(data,nf);});}
API const uint64_t* tsm_features(void*p){auto*s=static_cast<State*>(p);return s&&s->valid?s->features.data():nullptr;}
API uint64_t tsm_frames(void*p){auto*s=static_cast<State*>(p);return s&&s->valid?s->frames:0;}
API const uint64_t* tsm_spectra(void*p){auto*s=static_cast<State*>(p);return s&&s->valid&&s->has_spectra?s->spectra.data():nullptr;}
API const uint8_t* tsm_wire(void*p){auto*s=static_cast<State*>(p);return s&&s->valid&&s->has_wire?s->wire.data():nullptr;}
API uint64_t tsm_wire_bytes(void*p){auto*s=static_cast<State*>(p);return s&&s->valid&&s->has_wire?s->wire_count:0;}
API const char* tsm_error(){return last_error.c_str();}
API void tsm_destroy(void*p){delete static_cast<State*>(p);}
