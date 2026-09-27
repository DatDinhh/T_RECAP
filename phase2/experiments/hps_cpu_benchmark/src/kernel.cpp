// SPDX-License-Identifier: MIT
#include "kernel.hpp"
#include <limits>
#include <stdexcept>
#include <string>

#if defined(_MSC_VER)
#define TREC_NO_INLINE __declspec(noinline)
#elif defined(__GNUC__) || defined(__clang__)
#define TREC_NO_INLINE __attribute__((noinline))
#else
#define TREC_NO_INLINE
#endif

namespace trecap_bench {
namespace {
// No signed right-shift assumption, signed-overflow arithmetic, or 128-bit type.
// Actual products/pre-sums are at most 54 bits. The unsigned magnitude form also
// handles INT64_MIN without evaluating its undefined signed negation.
inline std::int64_t rounded(std::int64_t value,unsigned shift) noexcept {
    const auto magnitude=value<0 ? std::uint64_t{0}-static_cast<std::uint64_t>(value) : static_cast<std::uint64_t>(value);
    const auto result=(magnitude+(std::uint64_t{1}<<(shift-1)))>>shift;
    return value<0 ? -static_cast<std::int64_t>(result) : static_cast<std::int64_t>(result);
}
template<unsigned Width,bool Checked> inline std::int64_t fit(std::int64_t value) {
    if constexpr(Checked) {
        constexpr auto lo=-(std::int64_t{1}<<(Width-1));
        constexpr auto hi=(std::int64_t{1}<<(Width-1))-1;
        if(value<lo || value>hi) throw std::runtime_error("internal fixed-point width exceeded: signed"+std::to_string(Width));
    }
    return value;
}
inline std::int16_t saturated_output(std::int64_t value) noexcept {
    return static_cast<std::int16_t>(value < -2048 ? -2048 : value>2047 ? 2047 : value);
}
template<bool Inverse,bool Checked,class T>
void transform(std::array<Complex<T>,L>& a,const std::array<Complex<std::int32_t>,L>& twiddle) {
    constexpr unsigned Width=Inverse?36:28;
    for(std::size_t span=2;span<=L;span*=2) {
        const std::size_t half=span/2,step=L/span;
        for(std::size_t base=0;base<L;base+=span) {
            for(std::size_t j=0;j<half;++j) {
                const auto b=a[base+j+half];const auto w=twiddle[j*step];const auto old=a[base+j];
                const std::int64_t rr=static_cast<std::int64_t>(b.re)*w.re;
                const std::int64_t ii=static_cast<std::int64_t>(b.im)*w.im;
                const std::int64_t ri=static_cast<std::int64_t>(b.re)*w.im;
                const std::int64_t ir=static_cast<std::int64_t>(b.im)*w.re;
                const auto tr=fit<Width,Checked>(rounded(rr-ii,15));
                const auto ti=fit<Width,Checked>(rounded(ri+ir,15));
                std::int64_t sr=static_cast<std::int64_t>(old.re)+tr,si=static_cast<std::int64_t>(old.im)+ti;
                std::int64_t dr=static_cast<std::int64_t>(old.re)-tr,di=static_cast<std::int64_t>(old.im)-ti;
                if constexpr(!Inverse) { sr=rounded(sr,1);si=rounded(si,1);dr=rounded(dr,1);di=rounded(di,1); }
                a[base+j]={static_cast<T>(fit<Width,Checked>(sr)),static_cast<T>(fit<Width,Checked>(si))};
                a[base+j+half]={static_cast<T>(fit<Width,Checked>(dr)),static_cast<T>(fit<Width,Checked>(di))};
            }
        }
    }
}
inline std::uint64_t mag2(Complex<std::int32_t> v) noexcept {
    return static_cast<std::uint64_t>(static_cast<std::int64_t>(v.re)*v.re)+static_cast<std::uint64_t>(static_cast<std::int64_t>(v.im)*v.im);
}
} // namespace

Geometry geometry(std::size_t n) {
    if(n==0 || n>std::numeric_limits<std::size_t>::max()-L-D) throw std::invalid_argument("invalid finite input length");
    const auto frames=(n+L-2)/H,tau=frames*H;
    return {n,frames,tau,tau+G+L};
}
Kernel::Kernel(const Coefficients& coefficients,std::size_t input_count):coefficients_(coefficients),geometry_(geometry(input_count)),output_(geometry_.outputs) {
    for(std::size_t i=0;i<L;++i) {
        auto n=i;std::uint16_t reversed=0;
        for(unsigned b=0;b<8;++b) {reversed=static_cast<std::uint16_t>((reversed<<1)|(n&1));n>>=1;}
        bit_reverse_[i]=reversed;
    }
}
template<bool Checked> void Kernel::execute(const std::int16_t* input,std::uint64_t threshold) {
    sample_ring_.fill(0);ola_.fill(0);
    std::size_t wr=0,rd=0;
    for(std::size_t n=0;n<geometry_.outputs;++n) {
        const auto xin=n<geometry_.inputs?input[n]:std::int16_t{0};
        if constexpr(Checked) {fit<12,true>(xin);if(threshold>=(std::uint64_t{1}<<56))throw std::runtime_error("threshold outside unsigned56");}
        sample_ring_[wr]=xin;wr=(wr+1)&255;
        output_[n]=saturated_output(rounded(ola_[rd],15));ola_[rd]=0;if(++rd==D)rd=0;
        const auto tau=n+1;
        if((tau&(H-1))!=0 || tau>geometry_.tau_last)continue;
        for(std::size_t i=0;i<L;++i) {
            const auto product=static_cast<std::int64_t>(sample_ring_[(wr+i)&255])*coefficients_.window[i];
            fft_[bit_reverse_[i]]={static_cast<std::int32_t>(fit<27,Checked>(product)),0};
        }
        transform<false,Checked>(fft_,coefficients_.forward);
        // Round the positive pair once, then conjugate that rounded result.
        // DC is protected; Nyquist remains eligible for strict mag2 < threshold.
        fft_[0].im=0;fft_[128].im=0;
        for(std::size_t k=1;k<128;++k) {
            const auto a=fft_[k],b=fft_[L-k];
            const auto real=fit<28,Checked>(rounded(static_cast<std::int64_t>(a.re)+b.re,1));
            const auto imag=fit<28,Checked>(rounded(static_cast<std::int64_t>(a.im)-b.im,1));
            fit<28,Checked>(-imag);
            Complex<std::int32_t> c{static_cast<std::int32_t>(real),static_cast<std::int32_t>(imag)};
            if(mag2(c)<threshold)c={0,0};
            fft_[k]=c;fft_[L-k]={c.re,static_cast<std::int32_t>(fit<28,Checked>(-static_cast<std::int64_t>(c.im)))};
        }
        if(mag2(fft_[128])<threshold)fft_[128]={0,0};
        for(std::size_t i=0;i<L;++i)ifft_[bit_reverse_[i]]={fft_[i].re,fft_[i].im};
        transform<true,Checked>(ifft_,coefficients_.inverse);
        for(std::size_t i=0;i<L;++i) {
            const auto z=fit<36,Checked>(rounded(ifft_[i].re*coefficients_.window[i],15));
            auto target=rd+G+i;if(target>=D)target-=D;
            ola_[target]=fit<37,Checked>(ola_[target]+z);
        }
    }
}
TREC_NO_INLINE void Kernel::run_epoch(const std::int16_t* input,std::uint64_t threshold) {execute<false>(input,threshold);}
TREC_NO_INLINE void Kernel::run_epoch_checked(const std::int16_t* input,std::uint64_t threshold) {execute<true>(input,threshold);}
} // namespace trecap_bench
