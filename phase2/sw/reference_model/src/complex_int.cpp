// SPDX-License-Identifier: MIT
#include "trecap_golden/complex_int.hpp"

#include <limits>

namespace trecap::golden {
namespace {

static_assert(make_complex(1, -2) == ComplexI64{1, -2});
static_assert(conj(ComplexI64{1, -2}) == ComplexI64{1, 2});
static_assert(cadd(ComplexI64{1, 2}, ComplexI64{3, 4}) == ComplexI64{4, 6});
static_assert(csub(ComplexI64{1, 2}, ComplexI64{3, 4}) == ComplexI64{-2, -2});

}  // namespace

ComplexI64 rnd_shr_complex(const ComplexI64 value, const unsigned shift) {
    return ComplexI64{rnd_shr(value.re, shift), rnd_shr(value.im, shift)};
}

ComplexI64 rnd2_complex(const ComplexI64 value) {
    return rnd_shr_complex(value, 1U);
}

ComplexI64 cmul_to_fraction(const ComplexI64 data, const ComplexI64 twiddle, const unsigned F) {
    const std::int64_t rr = checked_mul_i64(data.re, twiddle.re);
    const std::int64_t ii = checked_mul_i64(data.im, twiddle.im);
    const std::int64_t ri = checked_mul_i64(data.re, twiddle.im);
    const std::int64_t ir = checked_mul_i64(data.im, twiddle.re);
    return ComplexI64{rnd_shr(rr - ii, F), rnd_shr(ri + ir, F)};
}

std::uint64_t magnitude_squared_u64(const ComplexI64 value) {
    const std::int64_t re2 = checked_mul_i64(value.re, value.re);
    const std::int64_t im2 = checked_mul_i64(value.im, value.im);
    if (re2 < 0 || im2 < 0) {
        throw contract_error("magnitude square overflowed signed accumulator");
    }
    const auto ure2 = static_cast<std::uint64_t>(re2);
    const auto uim2 = static_cast<std::uint64_t>(im2);
    if (ure2 > std::numeric_limits<std::uint64_t>::max() - uim2) {
        throw contract_error("magnitude square does not fit uint64");
    }
    return ure2 + uim2;
}

CanonicalPair hermitian_canonical_pair(const ComplexI64 xk, const ComplexI64 x_l_minus_k) {
    const std::int64_t real = rnd2(xk.re + x_l_minus_k.re);
    const std::int64_t imag = rnd2(xk.im - x_l_minus_k.im);
    return CanonicalPair{ComplexI64{real, imag}, ComplexI64{real, -imag}};
}

}  // namespace trecap::golden
