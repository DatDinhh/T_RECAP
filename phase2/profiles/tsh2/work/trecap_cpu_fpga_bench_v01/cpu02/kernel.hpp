// Fixed Revision J baseline: N=12, L=256, H=128, F=15.
// Bounds and numerical rules are documented in NUMERICS.md.
#pragma once
#include <array>
#include <cstdint>
#include <stdexcept>
namespace cpu02 {
struct Complex { int64_t re{}, im{}; bool operator==(const Complex&) const = default; };
template<unsigned W> inline int64_t fit(int64_t x) {
 static_assert(W>0 && W<63);
 if(x < -(int64_t(1)<<(W-1)) || x > (int64_t(1)<<(W-1))-1) throw std::runtime_error("fixed width exceeded");
 return x;
}
template<unsigned S> inline int64_t round_shift(int64_t x) {
 static_assert(S>0 && S<63);
 const uint64_t m=x<0?uint64_t(-(x+1))+1:uint64_t(x);
 const auto q=int64_t((m+(uint64_t(1)<<(S-1)))>>S);
 return x<0?-q:q;
}
inline int64_t saturate12(int64_t x) {return x<-2048?-2048:(x>2047?2047:x);}
inline Complex multiply(Complex x,Complex w) {
 // Callers enforce data signed36 and coefficient signed17; each summed
 // product is at most 2^52 in magnitude, safely within signed64.
 return {round_shift<15>(x.re*w.re-x.im*w.im),round_shift<15>(x.re*w.im+x.im*w.re)};
}
using Frame=std::array<int64_t,256>;
using Spectrum=std::array<Complex,256>;
struct Kernel {
 std::array<uint16_t,256> window{};
 Spectrum forward{},inverse{},a{},canonical{},b{};
 std::array<uint8_t,256> reverse{};
 void prepare(){for(unsigned i=0;i<256;i++){unsigned r=0;for(unsigned j=0;j<8;j++)r=(r<<1)|((i>>j)&1);reverse[i]=uint8_t(r);fit<17>(forward[i].re);fit<17>(forward[i].im);fit<17>(inverse[i].re);fit<17>(inverse[i].im);}}
 void analyze(const Frame& frame){
  for(unsigned k=0;k<256;k++){unsigned i=reverse[k];a[k]={fit<27>(fit<12>(frame[i])*window[i]),0};}
  transform<true>(a,forward);
  canonical[0]={fit<28>(a[0].re),0};canonical[128]={fit<28>(a[128].re),0};
  for(unsigned k=1;k<128;k++){
   const int64_t re=fit<28>(round_shift<1>(a[k].re+a[256-k].re));
   const int64_t im=fit<28>(round_shift<1>(a[k].im-a[256-k].im));
   canonical[k]={re,im};canonical[256-k]={re,fit<28>(-im)};
  }
 }
 void synthesize(Frame& z){
  for(unsigned k=0;k<256;k++){const auto v=canonical[reverse[k]];b[k]={fit<28>(v.re),fit<28>(v.im)};}
  transform<false>(b,inverse);
  for(unsigned i=0;i<256;i++)z[i]=fit<36>(round_shift<15>(b[i].re*window[i]));
 }
 template<bool Normalized> static void transform(Spectrum& v,const Spectrum& tw){
  for(unsigned span=2;span<=256;span*=2){const unsigned half=span/2,step=256/span;
   for(unsigned base=0;base<256;base+=span)for(unsigned j=0;j<half;j++){
    const auto t=multiply(v[base+j+half],tw[j*step]);const auto old=v[base+j];
    Complex sum{old.re+t.re,old.im+t.im},diff{old.re-t.re,old.im-t.im};
    if constexpr(Normalized){sum={fit<28>(round_shift<1>(sum.re)),fit<28>(round_shift<1>(sum.im))};diff={fit<28>(round_shift<1>(diff.re)),fit<28>(round_shift<1>(diff.im))};}
    else{sum={fit<36>(sum.re),fit<36>(sum.im)};diff={fit<36>(diff.re),fit<36>(diff.im)};}
    v[base+j]=sum;v[base+j+half]=diff;
   }
  }
 }
};
}
