#include "codec.hpp"
#include <algorithm>
#include <stdexcept>
#include <string>

namespace trecap { namespace {
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
void put(std::uint8_t* p, std::uint64_t value, std::size_t n) {
    for (std::size_t i = 0; i < n; ++i) p[i] = static_cast<std::uint8_t>(value >> (8*i));
}
std::uint64_t get(const std::uint8_t* p, std::size_t n) {
    std::uint64_t v=0;
    for (std::size_t i=0; i<n; ++i) v |= static_cast<std::uint64_t>(p[i]) << (8*i);
    return v;
}
void header(Packet& p, Encoding encoding, Expected e, std::size_t count, std::size_t payload) {
    p.size = (48 + payload + 7) & ~std::size_t{7};
    std::fill(p.bytes.begin(), p.bytes.begin()+48, std::uint8_t{0});
    std::fill(p.bytes.begin()+48+payload, p.bytes.begin()+p.size, std::uint8_t{0});
    put(p.bytes.data(), 0x31505354, 4);
    put(p.bytes.data()+4, 1, 2);
    put(p.bytes.data()+6, static_cast<std::uint16_t>(encoding), 2);
    put(p.bytes.data()+8, 0x00010001, 4);
    put(p.bytes.data()+12, payload, 4);
    put(p.bytes.data()+16, e.frame, 8);
    put(p.bytes.data()+24, e.threshold, 8);
    put(p.bytes.data()+32, count, 2);
    put(p.bytes.data()+34, 1, 2);
}
std::size_t validate(std::span<const std::uint8_t> p, Expected e, Encoding encoding) {
    require(p.size()>=48 && p.size()<=max_packet, "record length out of bounds");
    require(get(p.data(),4)==0x31505354, "invalid magic");
    require(get(p.data()+4,2)==1, "invalid version");
    require(get(p.data()+6,2)==static_cast<std::uint16_t>(encoding), "wrong encoding");
    require(get(p.data()+8,4)==0x00010001, "wrong configuration");
    require(get(p.data()+16,8)==e.frame, "wrong frame");
    require(get(p.data()+24,8)==e.threshold, "wrong threshold");
    require(get(p.data()+34,2)==1, "invalid protection flags");
    require(get(p.data()+36,4)==0, "nonzero reserved field");
    const auto count=static_cast<std::size_t>(get(p.data()+32,2));
    require(count>=1 && count<=bins, "invalid count");
    if(encoding==Encoding::dense) require(count==bins,"dense count must be129");
    const auto payload=static_cast<std::size_t>(get(p.data()+12,4));
    require(payload==(encoding==Encoding::dense?903:8*count),"wrong payload length");
    require(p.size()==((48+payload+7)&~std::size_t{7}),"wrong exact record length");
    for(std::size_t i=48+payload;i<p.size();++i) require(p[i]==0,"nonzero padding");
    require(get(p.data()+40,8)==checksum(p),"checksum mismatch");
    return count;
}
}
std::uint64_t byte_hash(std::span<const std::uint8_t> b) {
    std::uint64_t h=14695981039346656037ULL;
    for(auto v:b) { h^=v; h*=1099511628211ULL; }
    return h;
}
std::uint64_t checksum(std::span<const std::uint8_t> b) {
    std::uint64_t h=14695981039346656037ULL;
    for(std::size_t i=0;i<b.size();++i) {
        if(i>=40 && i<48) continue;
        h^=b[i]; h*=1099511628211ULL;
    }
    return h;
}
void encode_dense(const Dense& d, Expected e, Packet& p) {
    header(p,Encoding::dense,e,bins,903);
    for(std::size_t i=0;i<bins;++i) put(p.bytes.data()+48+7*i,d[i],7);
    put(p.bytes.data()+40,checksum(p.view()),8);
}
void encode_sparse(const Sparse& s, Expected e, Packet& p) {
    require(s.count>=1 && s.count<=bins,"encoder sparse count out of bounds");
    header(p,Encoding::sparse,e,s.count,8*s.count);
    for(std::size_t i=0;i<s.count;++i) put(p.bytes.data()+48+8*i,s.entries[i],8);
    put(p.bytes.data()+40,checksum(p.view()),8);
}
void decode_dense(std::span<const std::uint8_t> p, Expected e, Dense& d) {
    validate(p,e,Encoding::dense);
    for(std::size_t k=0;k<bins;++k) {
        d[k]=get(p.data()+48+7*k,7);
        require(k==0 || d[k]==0 || d[k]>=e.threshold,"dense value violates mask threshold");
    }
}
void decode_sparse(std::span<const std::uint8_t> p, Expected e, Sparse& s) {
    const auto count=validate(p,e,Encoding::sparse);
    int previous=-1;
    for(std::size_t i=0;i<count;++i) {
        const auto entry=get(p.data()+48+8*i,8);
        const auto index=static_cast<unsigned>(entry&255);
        const auto mag=entry>>8;
        require(index<bins,"sparse index out of range");
        require(static_cast<int>(index)>previous,"sparse indices not strictly increasing");
        require(i!=0 || index==0,"missing protected DC");
        require(index==0 || mag>=e.threshold,"sparse value violates mask threshold");
        s.entries[i]=entry;
        previous=static_cast<int>(index);
    }
    // At zero threshold every bin is retained, including zero magnitudes.
    require(e.threshold!=0 || count==bins,"zero threshold must retain all bins");
    s.count=count;
}
Sparse make_sparse(const Dense& original, const std::array<bool,bins>& masked) {
    Sparse s;
    for(auto v:original) require(v<=mag_mask,"magnitude exceeds unsigned56");
    prepare_sparse(original,masked,s);
    return s;
}
void prepare_sparse(const Dense& original, const std::array<bool,bins>& masked, Sparse& s) {
    s.count=0;
    for(std::size_t k=0;k<bins;++k) if(!masked[k]) {
        s.entries[s.count++]=(original[k]<<8)|k;
    }
}
}
