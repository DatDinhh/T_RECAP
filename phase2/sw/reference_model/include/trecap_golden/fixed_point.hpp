// SPDX-License-Identifier: MIT
#pragma once

#include "trecap_golden/signed_int.hpp"
#include "trecap_golden/rounding.hpp"
#include "trecap_golden/saturation.hpp"
#include "trecap_golden/q_format.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

struct FixedPointValue final {
    std::int64_t value{};
    QFormat format{};

    [[nodiscard]] constexpr bool fits_declared_width() const {
        if (format.is_signed) {
            return fits_signed(value, format.width);
        }
        return value >= 0 && fits_unsigned(static_cast<std::uint64_t>(value), format.width);
    }

    [[nodiscard]] constexpr std::uint64_t encoded() const {
        if (format.is_signed) {
            return encode_signed_twos_complement(value, format.width);
        }
        if (value < 0) {
            throw contract_error("cannot encode negative value as unsigned fixed-point");
        }
        return encode_unsigned(static_cast<std::uint64_t>(value), format.width);
    }
};

[[nodiscard]] constexpr FixedPointValue sample_value(const std::int64_t value, const unsigned sample_width_n = 12U) {
    return FixedPointValue{require_signed_fit(value, sample_width_n), q_external_sample(sample_width_n)};
}

[[nodiscard]] inline FixedPointValue window_value(const std::uint64_t value, const unsigned fractional_bits = 15U) {
    const QFormat format = q_window(fractional_bits);
    return FixedPointValue{static_cast<std::int64_t>(require_unsigned_fit(value, format.width)), format};
}

[[nodiscard]] constexpr FixedPointValue twiddle_value(const std::int64_t value, const unsigned fractional_bits = 15U) {
    const QFormat format = q_twiddle(fractional_bits);
    return FixedPointValue{require_signed_fit(value, format.width), format};
}

}  // namespace trecap::golden
