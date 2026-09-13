// SPDX-License-Identifier: MIT
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "trecap_golden/q_format.hpp"
#include "trecap_golden/rounding.hpp"
#include "trecap_golden/signed_int.hpp"

namespace {

void expect(bool condition, const std::string& message, int& failures) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

template <typename Fn>
void expect_throws(Fn&& fn, const std::string& message, int& failures) {
    try {
        fn();
    } catch (const trecap::golden::contract_error&) {
        return;
    }
    std::cerr << "FAIL: expected throw: " << message << '\n';
    ++failures;
}

}  // namespace

int main() {
    using namespace trecap::golden;

    int failures = 0;

    expect(qcoef(0.0L, 0U) == 0, "qcoef zero", failures);
    expect(qcoef(0.499L, 0U) == 0, "qcoef below positive half", failures);
    expect(qcoef(-0.499L, 0U) == 0, "qcoef above negative half", failures);
    expect(qcoef(0.5L, 0U) == 1, "qcoef positive tie away", failures);
    expect(qcoef(-0.5L, 0U) == -1, "qcoef negative tie away", failures);
    expect(qcoef(1.5L, 0U) == 2, "qcoef positive 1.5", failures);
    expect(qcoef(-1.5L, 0U) == -2, "qcoef negative 1.5", failures);
    expect(qcoef(1.0L, 15U) == 32768, "qcoef +1.0 Q15", failures);
    expect(qcoef(-1.0L, 15U) == -32768, "qcoef -1.0 Q15", failures);
    expect(qcoef(0.25L, 15U) == 8192, "qcoef +0.25 Q15", failures);
    expect(qcoef(-0.25L, 15U) == -8192, "qcoef -0.25 Q15", failures);

    expect(q_window(15U).width == 16U && !q_window(15U).is_signed, "window Q format width/signedness", failures);
    expect(q_twiddle(15U).width == 17U && q_twiddle(15U).is_signed, "twiddle Q format width/signedness", failures);
    expect(q_external_sample(12U).width == 12U && q_external_sample(12U).frac == 0U, "sample Q format", failures);

    expect(mulF(32768, 32768, 15U, 15U, 15U) == 32768, "mulF +1.0 * +1.0", failures);
    expect(mulF(-32768, 32768, 15U, 15U, 15U) == -32768, "mulF -1.0 * +1.0", failures);
    expect(mulF(16384, 16384, 15U, 15U, 15U) == 8192, "mulF 0.5 * 0.5", failures);
    expect(exact_product(-7, 11) == -77, "exact product signed", failures);
    expect(multiplication_fits_i64(32768, 32768), "normal coefficient product fits int64", failures);
    expect(!multiplication_fits_i64(std::numeric_limits<std::int64_t>::max(), 2), "oversized product rejected by predicate", failures);

    expect_throws([] { static_cast<void>(qcoef(std::numeric_limits<long double>::infinity(), 15U)); }, "qcoef +inf", failures);
    expect_throws([] { static_cast<void>(qcoef(std::numeric_limits<long double>::quiet_NaN(), 15U)); }, "qcoef NaN", failures);
    expect_throws([] { static_cast<void>(qcoef(1.0L, 62U)); }, "qcoef excessive fractional width", failures);
    expect_throws([] { static_cast<void>(mul_to_fraction(1, 0U, 1, 0U, 1U)); }, "mul_to_fraction left-shift policy rejected", failures);
    expect_throws([] { static_cast<void>(checked_mul_i64(std::numeric_limits<std::int64_t>::max(), 2)); }, "checked_mul_i64 overflow", failures);

    return failures == 0 ? 0 : 1;
}
