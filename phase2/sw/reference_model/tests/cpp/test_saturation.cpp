// SPDX-License-Identifier: MIT
#include <cstdint>
#include <iostream>
#include <string>

#include "trecap_golden/saturation.hpp"
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

    expect(signed_min(12U) == -2048, "signed_min 12", failures);
    expect(signed_max(12U) == 2047, "signed_max 12", failures);
    expect(signed_min(1U) == -1, "signed_min 1", failures);
    expect(signed_max(1U) == 0, "signed_max 1", failures);

    const SaturationResult lo = saturate_signed_result(-2049, 12U);
    const SaturationResult exact_lo = saturate_signed_result(-2048, 12U);
    const SaturationResult mid = saturate_signed_result(17, 12U);
    const SaturationResult exact_hi = saturate_signed_result(2047, 12U);
    const SaturationResult hi = saturate_signed_result(2048, 12U);

    expect(lo.value == -2048 && lo.kind == SaturationKind::low && lo.saturated(), "low saturation result", failures);
    expect(exact_lo.value == -2048 && exact_lo.kind == SaturationKind::none, "exact low is not saturated", failures);
    expect(mid.value == 17 && mid.kind == SaturationKind::none && !mid.saturated(), "mid value not saturated", failures);
    expect(exact_hi.value == 2047 && exact_hi.kind == SaturationKind::none, "exact high is not saturated", failures);
    expect(hi.value == 2047 && hi.kind == SaturationKind::high && hi.saturated(), "high saturation result", failures);

    expect(sat_signed(-9999, 12U) == -2048, "sat_signed low", failures);
    expect(sat_signed(9999, 12U) == 2047, "sat_signed high", failures);
    expect(sat_sample(-4096) == -2048, "sat_sample default low", failures);
    expect(sat_sample(4095) == 2047, "sat_sample default high", failures);

    expect(checked_signed_assignment(-2048, 12U) == -2048, "checked signed min assignment", failures);
    expect(checked_signed_assignment(2047, 12U) == 2047, "checked signed max assignment", failures);
    expect(checked_unsigned_assignment(4095U, 12U) == 4095U, "checked unsigned max assignment", failures);

    expect_throws([] { static_cast<void>(checked_signed_assignment(-2049, 12U)); }, "checked signed below range", failures);
    expect_throws([] { static_cast<void>(checked_signed_assignment(2048, 12U)); }, "checked signed above range", failures);
    expect_throws([] { static_cast<void>(checked_unsigned_assignment(4096U, 12U)); }, "checked unsigned above range", failures);
    expect_throws([] { static_cast<void>(encode_signed_twos_complement(2048, 12U)); }, "signed encode refuses overflow", failures);
    expect_throws([] { static_cast<void>(encode_unsigned(16U, 4U)); }, "unsigned encode refuses overflow", failures);

    expect(sign_extend_twos_complement(0x800U, 12U) == -2048, "sign extend 12-bit min", failures);
    expect(sign_extend_twos_complement(0x7ffU, 12U) == 2047, "sign extend 12-bit max", failures);
    expect(sign_extend_twos_complement(0xfffU, 12U) == -1, "sign extend 12-bit -1", failures);

    return failures == 0 ? 0 : 1;
}
