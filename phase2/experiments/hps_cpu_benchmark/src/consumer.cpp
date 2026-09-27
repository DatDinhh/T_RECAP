// SPDX-License-Identifier: MIT
#include "kernel.hpp"
#include <atomic>
namespace trecap_bench {
namespace { volatile std::uint64_t sink=0; }
#if defined(__GNUC__) || defined(__clang__)
__attribute__((noinline))
#endif
void consume_epoch(const std::int16_t* output,std::size_t count,std::uint64_t epoch) noexcept {
#if defined(__GNUC__) || defined(__clang__)
    asm volatile("" : : "r"(output),"r"(count) : "memory");
#else
    std::atomic_signal_fence(std::memory_order_seq_cst);
#endif
    const volatile std::int16_t* observed=output;
    const auto sample=static_cast<std::uint16_t>(observed[static_cast<std::size_t>(epoch%count)]);
    const std::uint64_t old=sink;
    sink=((old<<7)|(old>>57))^sample^(epoch+0x9e3779b97f4a7c15ULL);
}
std::uint64_t consumer_checksum() noexcept {return sink;}
} // namespace trecap_bench
