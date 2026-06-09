// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>

#include "trecap_golden/signed_int.hpp"

namespace trecap::golden {

enum class SaturationKind : std::uint8_t {
    none = 0,
    low = 1,
    high = 2,
};

struct SaturationResult final {
    std::int64_t value{};
    SaturationKind kind{SaturationKind::none};

    [[nodiscard]] constexpr bool saturated() const noexcept {
        return kind != SaturationKind::none;
    }
};

constexpr SaturationResult saturate_signed_result(const std::int64_t value, const unsigned width) {
    const std::int64_t lo = signed_min(width);
    const std::int64_t hi = signed_max(width);
    if (value < lo) {
        return SaturationResult{lo, SaturationKind::low};
    }
    if (value > hi) {
        return SaturationResult{hi, SaturationKind::high};
    }
    return SaturationResult{value, SaturationKind::none};
}

constexpr std::int64_t sat_signed(const std::int64_t value, const unsigned width) {
    return saturate_signed_result(value, width).value;
}

constexpr std::int64_t sat_sample(const std::int64_t value, const unsigned sample_width_n = 12U) {
    return sat_signed(value, sample_width_n);
}

constexpr std::int64_t checked_signed_assignment(const std::int64_t value, const unsigned width) {
    return require_signed_fit(value, width);
}

constexpr std::uint64_t checked_unsigned_assignment(const std::uint64_t value, const unsigned width) {
    return require_unsigned_fit(value, width);
}

}  // namespace trecap::golden
