// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <vector>

#include "trecap_golden/coeffs.hpp"
#include "trecap_golden/complex_int.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

[[nodiscard]] constexpr std::uint32_t bit_reverse(std::uint32_t value, const unsigned bits) {
    std::uint32_t reversed = 0U;
    for (unsigned i = 0U; i < bits; ++i) {
        reversed <<= 1U;
        reversed |= value & 1U;
        value >>= 1U;
    }
    return reversed;
}

[[nodiscard]] constexpr unsigned twiddle_exponent(const unsigned j, const unsigned span, const CoreConfig& cfg) {
    if (span == 0U || span > cfg.L || (cfg.L % span) != 0U) {
        throw contract_error("illegal FFT span for twiddle exponent");
    }
    return j * (cfg.L / span);
}

struct TwiddleTables final {
    CoreConfig cfg{CoreConfig::baseline()};
    std::vector<ComplexI64> forward{};
    std::vector<ComplexI64> inverse{};

    [[nodiscard]] static TwiddleTables generated(const CoreConfig& core = CoreConfig::baseline());

    void validate() const;

    [[nodiscard]] ComplexI64 fwd(unsigned exponent) const;

    [[nodiscard]] ComplexI64 inv(unsigned exponent) const;
};

[[nodiscard]] std::vector<ComplexI64> make_forward_twiddle_table(const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<ComplexI64> make_inverse_twiddle_table(const CoreConfig& cfg = CoreConfig::baseline());

}  // namespace trecap::golden
