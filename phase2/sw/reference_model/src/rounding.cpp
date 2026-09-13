// SPDX-License-Identifier: MIT
#include "trecap_golden/rounding.hpp"

#include <cmath>
#include <limits>

namespace trecap::golden {
namespace {

static_assert(sgn(-5) == -1);
static_assert(sgn(0) == 0);
static_assert(sgn(5) == 1);
static_assert(asr(-3, 1U) == -2);
static_assert(asr(3, 1U) == 1);
static_assert(rnd_shr(-3, 1U) == -2);
static_assert(rnd_shr(3, 1U) == 2);
static_assert(rnd2(0) == 0);

}  // namespace

std::int64_t qcoef(const long double value, const unsigned fractional_bits) {
    if (!std::isfinite(value)) {
        throw contract_error("qcoef input is not finite");
    }
    if (fractional_bits >= 62U) {
        throw contract_error("qcoef fractional width is too large for int64 output");
    }
    const long double scale = static_cast<long double>(std::uint64_t{1} << fractional_bits);
    const long double magnitude = std::floor(std::fabs(value) * scale + 0.5L);
    if (magnitude > static_cast<long double>(std::numeric_limits<std::int64_t>::max())) {
        throw contract_error("qcoef output does not fit int64");
    }
    const auto quantized = static_cast<std::int64_t>(magnitude);
    if (value < 0.0L) {
        return -quantized;
    }
    if (value > 0.0L) {
        return quantized;
    }
    return 0;
}

}  // namespace trecap::golden
