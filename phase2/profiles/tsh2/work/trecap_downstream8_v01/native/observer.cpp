#include "codec.hpp"
namespace trecap {
namespace { volatile std::uint64_t value=0; }
void observe(const void* memory, std::size_t bytes) {
    // The caller cannot see which bytes are observed because LTO is disabled.
    // Sample actual output memory; use the same call boundary for both modes.
    const auto* p=static_cast<const std::uint8_t*>(memory);
    if(bytes) value=(value*1099511628211ULL)^p[0]^
        (static_cast<std::uint64_t>(p[bytes/2])<<8)^
        (static_cast<std::uint64_t>(p[bytes-1])<<16);
}
std::uint64_t observer_value(){return value;}
}
