// SPDX-License-Identifier: MIT
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "trecap_golden/rounding.hpp"
#include "trecap_golden/signed_int.hpp"

namespace {

constexpr auto kMin = std::numeric_limits<std::int64_t>::min();
constexpr auto kMax = std::numeric_limits<std::int64_t>::max();
constexpr auto kHalf63 = std::int64_t{1} << 62U;
static_assert(trecap::golden::rnd_shr(kMin, 63U) == -1);
static_assert(trecap::golden::rnd_shr(kHalf63, 63U) == 1);
static_assert(trecap::golden::rnd_shr(kMax, 63U) == 1);
static_assert(trecap::golden::rnd_shr(kMin, 64U) == -1);
static_assert(trecap::golden::rnd_shr(kMin, 65U) == 0);
static_assert(trecap::golden::rnd_shr(kMin, std::numeric_limits<unsigned>::max()) == 0);

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

    expect(sgn(-9) == -1, "sgn negative", failures);
    expect(sgn(0) == 0, "sgn zero", failures);
    expect(sgn(9) == 1, "sgn positive", failures);

    expect(asr(0, 0U) == 0, "asr zero shift zero", failures);
    expect(asr(7, 0U) == 7, "asr positive zero shift", failures);
    expect(asr(-7, 0U) == -7, "asr negative zero shift", failures);
    expect(asr(7, 1U) == 3, "asr +7 by 1", failures);
    expect(asr(7, 2U) == 1, "asr +7 by 2", failures);
    expect(asr(-1, 1U) == -1, "asr -1 by 1", failures);
    expect(asr(-3, 1U) == -2, "asr -3 by 1", failures);
    expect(asr(-5, 2U) == -2, "asr -5 by 2", failures);
    expect(asr(123, 63U) == 0, "asr positive large shift", failures);
    expect(asr(-123, 63U) == -1, "asr negative large shift", failures);

    expect(rnd_shr(0, 0U) == 0, "rnd_shr zero zero shift", failures);
    expect(rnd_shr(19, 0U) == 19, "rnd_shr positive zero shift", failures);
    expect(rnd_shr(-19, 0U) == -19, "rnd_shr negative zero shift", failures);
    expect(rnd_shr(1, 1U) == 1, "rnd_shr +0.5 ties away", failures);
    expect(rnd_shr(-1, 1U) == -1, "rnd_shr -0.5 ties away", failures);
    expect(rnd_shr(2, 1U) == 1, "rnd_shr +2 / 2", failures);
    expect(rnd_shr(-2, 1U) == -1, "rnd_shr -2 / 2", failures);
    expect(rnd_shr(3, 1U) == 2, "rnd_shr +1.5", failures);
    expect(rnd_shr(-3, 1U) == -2, "rnd_shr -1.5", failures);
    expect(rnd_shr(2, 2U) == 1, "rnd_shr +0.5 with shift 2", failures);
    expect(rnd_shr(-2, 2U) == -1, "rnd_shr -0.5 with shift 2", failures);
    expect(rnd_shr(6, 2U) == 2, "rnd_shr +1.5 with shift 2", failures);
    expect(rnd_shr(-6, 2U) == -2, "rnd_shr -1.5 with shift 2", failures);
    expect(rnd2(5) == 3, "rnd2 +5", failures);
    expect(rnd2(-5) == -3, "rnd2 -5", failures);

    expect(rnd_shr(123, 63U) == 0, "rnd_shr positive large shift", failures);
    expect(rnd_shr(-123, 63U) == 0, "rnd_shr negative large shift", failures);

    expect(rnd_shr(kMin, 0U) == kMin, "INT64_MIN zero shift", failures);
    expect(rnd_shr(kMin, 1U) == kMin / 2, "INT64_MIN half", failures);
    expect(rnd_shr(kMin, 62U) == -2, "INT64_MIN shift 62", failures);
    expect(rnd_shr(kMin, 63U) == -1, "INT64_MIN shift 63", failures);
    expect(rnd_shr(kMax, 63U) == 1, "INT64_MAX shift 63", failures);
    expect(rnd_shr(kMin, 64U) == -1, "INT64_MIN shift 64 tie", failures);
    expect(rnd_shr(kMin + 1, 64U) == 0, "next to INT64_MIN is below shift 64 tie", failures);
    expect(rnd_shr(kMax, 64U) == 0, "INT64_MAX below shift 64 tie", failures);
    for (const unsigned shift : {65U, 127U, 255U, std::numeric_limits<unsigned>::max()}) {
        expect(rnd_shr(kMin, shift) == 0, "INT64_MIN very large shift", failures);
        expect(rnd_shr(kMax, shift) == 0, "INT64_MAX very large shift", failures);
        expect(asr(kMin, shift) == -1, "negative arithmetic very large shift", failures);
        expect(asr(kMax, shift) == 0, "positive arithmetic very large shift", failures);
    }
    // Each representable power-of-two half boundary, on both sides of zero.
    for (unsigned shift = 1U; shift <= 63U; ++shift) {
        const std::int64_t half = std::int64_t{1} << (shift - 1U);
        expect(rnd_shr(half - 1, shift) == 0, "positive below half", failures);
        expect(rnd_shr(half, shift) == 1, "positive exact half", failures);
        expect(rnd_shr(half + 1, shift) == 1, "positive above half", failures);
        expect(rnd_shr(-(half - 1), shift) == 0, "negative below half magnitude", failures);
        expect(rnd_shr(-half, shift) == -1, "negative exact half", failures);
        expect(rnd_shr(-(half + 1), shift) == -1, "negative above half magnitude", failures);
    }
    expect(asr(kMin, 0U) == kMin, "asr INT64_MIN unchanged", failures);
    expect(asr(kMin, 1U) == kMin / 2, "asr INT64_MIN half", failures);
    expect(asr(kMin, 62U) == -2, "asr INT64_MIN shift 62", failures);
    expect(asr(kMin, 63U) == -1, "asr INT64_MIN shift 63", failures);
    expect(asr(kMin, 64U) == -1, "asr INT64_MIN shift 64", failures);

    expect_throws([] { static_cast<void>(require_width(0U)); }, "zero width rejected", failures);
    expect_throws([] { static_cast<void>(require_width(65U)); }, "too-wide integer width rejected", failures);

    return failures == 0 ? 0 : 1;
}
