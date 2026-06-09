// SPDX-License-Identifier: MIT
#include "trecap_golden/q_format.hpp"

namespace trecap::golden {
namespace {

static_assert(q_external_sample().width == 12U);
static_assert(q_external_sample().frac == 0U);
static_assert(q_external_sample().is_signed);
static_assert(q_window().width == 16U);
static_assert(!q_window().is_signed);
static_assert(q_twiddle().width == 17U);
static_assert(q_twiddle().is_signed);
static_assert(multiplication_fits_i64(32768, 32768));
static_assert(!multiplication_fits_i64(std::numeric_limits<std::int64_t>::max(), 2));

}  // namespace

std::int64_t checked_mul_i64(const std::int64_t a, const std::int64_t b) {
    if (!multiplication_fits_i64(a, b)) {
        throw contract_error("integer product does not fit int64");
    }
    return a * b;
}

std::int64_t mul_to_fraction(const std::int64_t a,
                             const unsigned frac_a,
                             const std::int64_t b,
                             const unsigned frac_b,
                             const unsigned frac_out) {
    if (frac_a + frac_b < frac_out) {
        throw contract_error("mul_to_fraction would require a left shift; explicit scale policy required");
    }
    const std::int64_t product = checked_mul_i64(a, b);
    return rnd_shr(product, frac_a + frac_b - frac_out);
}

std::int64_t mulF(const std::int64_t a,
                  const std::int64_t b,
                  const unsigned frac_a,
                  const unsigned frac_b,
                  const unsigned F) {
    return mul_to_fraction(a, frac_a, b, frac_b, F);
}

std::int64_t exact_product(const std::int64_t a, const std::int64_t b) {
    return checked_mul_i64(a, b);
}

}  // namespace trecap::golden
