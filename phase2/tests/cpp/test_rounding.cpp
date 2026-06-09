// SPDX-License-Identifier: MIT
#include <cstdint>
#include <iostream>
#include <string>

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

    expect_throws([] { static_cast<void>(require_width(0U)); }, "zero width rejected", failures);
    expect_throws([] { static_cast<void>(require_width(65U)); }, "too-wide integer width rejected", failures);

    return failures == 0 ? 0 : 1;
}
