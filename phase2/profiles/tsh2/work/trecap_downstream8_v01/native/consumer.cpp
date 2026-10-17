#include "codec.hpp"
namespace trecap {
void consume_dense(const Dense& d, Features& out) {
    // Disjoint contiguous band loops allow the compiler to vectorize reductions.
    // First compute twice all magnitudes; correct the unique DC/Nyquist weights.
    for(std::size_t band=0;band<bands;++band) {
        const std::size_t begin=(band*bins+bands-1)/bands;
        const std::size_t end=((band+1)*bins+bands-1)/bands;
        std::uint64_t sum=0;
        for(std::size_t k=begin;k<end;++k) sum+=2*d[k];
        out[band]=sum;
    }
    out[0]-=d[0];
    out[bands-1]-=d[bins-1];
}
void consume_sparse(const Sparse& s, Features& out) {
    out.fill(0);
    for(std::size_t i=0;i<s.count;++i) {
        const auto k=static_cast<std::size_t>(s.entries[i]&255);
        const auto magnitude=s.entries[i]>>8;
        out[(bands*k)/bins]+=(k==0 || k==bins-1)?magnitude:2*magnitude;
    }
}
}
