// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <limits>
#include <string_view>

#include "trecap_golden/rounding.hpp"
#include "trecap_golden/signed_int.hpp"

namespace trecap::golden {

struct QFormat final {
    unsigned width{};
    unsigned frac{};
    bool is_signed{};
    std::string_view name{};

    [[nodiscard]] constexpr std::int64_t min_value() const {
        return is_signed ? signed_min(width) : 0;
    }

    [[nodiscard]] constexpr std::uint64_t max_unsigned_value() const {
        return bit_mask(width);
    }

    [[nodiscard]] constexpr std::int64_t max_signed_value() const {
        return is_signed ? signed_max(width) : static_cast<std::int64_t>(bit_mask(width));
    }
};

inline constexpr QFormat q_external_sample(const unsigned width_n = 12U) {
    return QFormat{width_n, 0U, true, "sample_q0"};
}

inline constexpr QFormat q_window(const unsigned fractional_bits = 15U) {
    return QFormat{fractional_bits + 1U, fractional_bits, false, "window_qF"};
}

inline constexpr QFormat q_twiddle(const unsigned fractional_bits = 15U) {
    return QFormat{fractional_bits + 2U, fractional_bits, true, "twiddle_qF"};
}

inline constexpr bool multiplication_fits_i64(const std::int64_t a, const std::int64_t b) {
    if (a == 0 || b == 0) {
        return true;
    }
    if (a == std::numeric_limits<std::int64_t>::min()) {
        return b == 1;
    }
    if (b == std::numeric_limits<std::int64_t>::min()) {
        return a == 1;
    }
    const std::uint64_t aa = abs_u64(a);
    const std::uint64_t bb = abs_u64(b);
    const bool negative_product = (a < 0) != (b < 0);
    const std::uint64_t limit = negative_product
                                    ? static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) +
                                          std::uint64_t{1}
                                    : static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
    return aa <= limit / bb;
}

[[nodiscard]] std::int64_t checked_mul_i64(std::int64_t a, std::int64_t b);

[[nodiscard]] std::int64_t mul_to_fraction(std::int64_t a,
                                           unsigned frac_a,
                                           std::int64_t b,
                                           unsigned frac_b,
                                           unsigned frac_out);

[[nodiscard]] std::int64_t mulF(std::int64_t a, std::int64_t b, unsigned frac_a, unsigned frac_b, unsigned F);

[[nodiscard]] std::int64_t exact_product(std::int64_t a, std::int64_t b);

}  // namespace trecap::golden
