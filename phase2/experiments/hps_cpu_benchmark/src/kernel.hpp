// SPDX-License-Identifier: MIT
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace trecap_bench {
constexpr std::size_t L=256, H=128, G=128, D=384;
template<class T> struct Complex { T re{},im{}; };
struct Coefficients {
    std::array<std::uint16_t,L> window{};
    std::array<Complex<std::int32_t>,L> forward{},inverse{};
};
struct Geometry { std::size_t inputs{},frames{},tau_last{},outputs{}; };
Geometry geometry(std::size_t inputs);

// Owns all algorithm state/output storage. Constructor allocations happen once,
// outside timing. Each epoch resets the two rings and pointers; transform scratch
// and output are completely overwritten before observation, requiring no clear.
class Kernel {
public:
    Kernel(const Coefficients& coefficients,std::size_t input_count);
    void run_epoch(const std::int16_t* input,std::uint64_t threshold);
    void run_epoch_checked(const std::int16_t* input,std::uint64_t threshold);
    const std::vector<std::int16_t>& output() const noexcept { return output_; }
    Geometry shape() const noexcept { return geometry_; }
private:
    template<bool Checked> void execute(const std::int16_t*,std::uint64_t);
    const Coefficients& coefficients_;
    Geometry geometry_;
    std::array<std::uint16_t,L> bit_reverse_{};
    std::array<std::int16_t,L> sample_ring_{};
    std::array<std::int64_t,D> ola_{};
    std::array<Complex<std::int32_t>,L> fft_{};
    std::array<Complex<std::int64_t>,L> ifft_{};
    std::vector<std::int16_t> output_;
};
// Separate translation unit, intentionally opaque to the timed caller. CMake
// disables LTO. One volatile sample read and rolling checksum per completed epoch.
void consume_epoch(const std::int16_t* output,std::size_t count,std::uint64_t epoch) noexcept;
std::uint64_t consumer_checksum() noexcept;
} // namespace trecap_bench
