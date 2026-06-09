// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <type_traits>

#include "trecap_golden/q_format.hpp"
#include "trecap_golden/rounding.hpp"

namespace trecap::golden {

template <typename T = std::int64_t>
struct ComplexInt final {
    static_assert(std::is_integral_v<T>, "ComplexInt requires an integral component type");

    T re{};
    T im{};

    [[nodiscard]] constexpr bool operator==(const ComplexInt&) const = default;
};

using ComplexI64 = ComplexInt<std::int64_t>;

[[nodiscard]] constexpr ComplexI64 make_complex(const std::int64_t re, const std::int64_t im = 0) noexcept {
    return ComplexI64{re, im};
}

[[nodiscard]] constexpr ComplexI64 conj(const ComplexI64 z) noexcept {
    return ComplexI64{z.re, -z.im};
}

[[nodiscard]] constexpr ComplexI64 cadd(const ComplexI64 a, const ComplexI64 b) noexcept {
    return ComplexI64{a.re + b.re, a.im + b.im};
}

[[nodiscard]] constexpr ComplexI64 csub(const ComplexI64 a, const ComplexI64 b) noexcept {
    return ComplexI64{a.re - b.re, a.im - b.im};
}

[[nodiscard]] ComplexI64 rnd_shr_complex(ComplexI64 value, unsigned shift);

[[nodiscard]] ComplexI64 rnd2_complex(ComplexI64 value);

[[nodiscard]] ComplexI64 cmul_to_fraction(ComplexI64 data, ComplexI64 twiddle, unsigned F);

[[nodiscard]] std::uint64_t magnitude_squared_u64(ComplexI64 value);

struct CanonicalPair final {
    ComplexI64 positive_bin{};
    ComplexI64 negative_bin{};
};

[[nodiscard]] CanonicalPair hermitian_canonical_pair(ComplexI64 xk, ComplexI64 x_l_minus_k);

}  // namespace trecap::golden
