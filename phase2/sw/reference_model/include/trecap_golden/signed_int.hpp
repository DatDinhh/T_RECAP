// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace trecap::golden {

class contract_error final : public std::runtime_error {
public:
    explicit contract_error(const std::string& message) : std::runtime_error(message) {}
};

constexpr unsigned require_width(const unsigned width, const unsigned max_width = 64U) {
    if (width == 0U || width > max_width) {
        throw contract_error("illegal integer width");
    }
    return width;
}

constexpr std::uint64_t bit_mask(const unsigned width) {
    require_width(width, 64U);
    if (width == 64U) {
        return std::numeric_limits<std::uint64_t>::max();
    }
    return (std::uint64_t{1} << width) - std::uint64_t{1};
}

constexpr std::uint64_t sign_bit_mask(const unsigned width) {
    require_width(width, 64U);
    return std::uint64_t{1} << (width - 1U);
}

constexpr std::int64_t signed_min(const unsigned width) {
    require_width(width, 64U);
    if (width == 64U) {
        return std::numeric_limits<std::int64_t>::min();
    }
    return -static_cast<std::int64_t>(std::uint64_t{1} << (width - 1U));
}

constexpr std::int64_t signed_max(const unsigned width) {
    require_width(width, 64U);
    if (width == 64U) {
        return std::numeric_limits<std::int64_t>::max();
    }
    return static_cast<std::int64_t>((std::uint64_t{1} << (width - 1U)) - std::uint64_t{1});
}

constexpr bool fits_signed(const std::int64_t value, const unsigned width) {
    return value >= signed_min(width) && value <= signed_max(width);
}

constexpr bool fits_unsigned(const std::uint64_t value, const unsigned width) {
    require_width(width, 64U);
    return width == 64U || value < (std::uint64_t{1} << width);
}

constexpr std::uint64_t encode_unsigned(const std::uint64_t value, const unsigned width) {
    require_width(width, 64U);
    if (!fits_unsigned(value, width)) {
        throw contract_error("unsigned value does not fit declared width");
    }
    return value & bit_mask(width);
}

constexpr std::uint64_t encode_signed_twos_complement(const std::int64_t value, const unsigned width) {
    require_width(width, 64U);
    if (!fits_signed(value, width)) {
        throw contract_error("signed value does not fit declared width");
    }
    return static_cast<std::uint64_t>(value) & bit_mask(width);
}

constexpr std::int64_t sign_extend_twos_complement(const std::uint64_t encoded, const unsigned width) {
    require_width(width, 64U);
    const std::uint64_t masked = encoded & bit_mask(width);
    if (width == 64U) {
        return static_cast<std::int64_t>(masked);
    }
    const std::uint64_t sign = sign_bit_mask(width);
    if ((masked & sign) == 0U) {
        return static_cast<std::int64_t>(masked);
    }
    const std::uint64_t magnitude = ((~masked) & bit_mask(width)) + std::uint64_t{1};
    return -static_cast<std::int64_t>(magnitude);
}

constexpr std::uint64_t abs_u64(const std::int64_t value) {
    if (value >= 0) {
        return static_cast<std::uint64_t>(value);
    }
    // Avoid undefined behavior for INT64_MIN by using unsigned modular arithmetic.
    return static_cast<std::uint64_t>(-(value + 1)) + std::uint64_t{1};
}

constexpr unsigned fixed_hex_digits(const unsigned width) {
    require_width(width, 64U);
    return (width + 3U) / 4U;
}

constexpr std::int64_t require_signed_fit(const std::int64_t value, const unsigned width) {
    if (!fits_signed(value, width)) {
        throw contract_error("signed value outside declared width");
    }
    return value;
}

constexpr std::uint64_t require_unsigned_fit(const std::uint64_t value, const unsigned width) {
    if (!fits_unsigned(value, width)) {
        throw contract_error("unsigned value outside declared width");
    }
    return value;
}

}  // namespace trecap::golden
