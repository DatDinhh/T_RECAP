// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <limits>

#include "trecap_golden/signed_int.hpp"

namespace trecap::golden {

constexpr int sgn(const std::int64_t value) noexcept {
    return (value > 0) ? 1 : ((value < 0) ? -1 : 0);
}

constexpr std::int64_t asr(const std::int64_t value, const unsigned shift) {
    if (shift >= 63U) {
        if (value >= 0) {
            return 0;
        }
        return -1;
    }
    if (shift == 0U) {
        return value;
    }
    if (value >= 0) {
        return static_cast<std::int64_t>(static_cast<std::uint64_t>(value) >> shift);
    }
    const std::uint64_t divisor = std::uint64_t{1} << shift;
    const std::uint64_t magnitude = abs_u64(value);
    const std::uint64_t quotient = (magnitude + divisor - std::uint64_t{1}) >> shift;
    return -static_cast<std::int64_t>(quotient);
}

constexpr std::int64_t rnd_shr(const std::int64_t value, const unsigned shift) {
    if (shift == 0U) {
        return value;
    }
    if (shift >= 63U) {
        return 0;
    }

    const std::uint64_t bias = std::uint64_t{1} << (shift - 1U);
    const std::uint64_t magnitude = abs_u64(value);
    if (magnitude > std::numeric_limits<std::uint64_t>::max() - bias) {
        throw contract_error("rounded shift input overflows accumulator");
    }
    const std::uint64_t quotient = (magnitude + bias) >> shift;
    if (value < 0) {
        return -static_cast<std::int64_t>(quotient);
    }
    return static_cast<std::int64_t>(quotient);
}

constexpr std::int64_t rnd2(const std::int64_t value) {
    return rnd_shr(value, 1U);
}

[[nodiscard]] std::int64_t qcoef(long double value, unsigned fractional_bits);

}  // namespace trecap::golden
