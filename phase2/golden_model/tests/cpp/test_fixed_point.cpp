// SPDX-License-Identifier: MIT
#include <cstdint>
#include <iostream>
#include <string>

#include "trecap_golden/fixed_point.hpp"
#include "trecap_golden/q_format.hpp"
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

    const FixedPointValue min_sample = sample_value(-2048, 12U);
    const FixedPointValue neg_one_sample = sample_value(-1, 12U);
    const FixedPointValue zero_sample = sample_value(0, 12U);
    const FixedPointValue max_sample = sample_value(2047, 12U);

    expect(min_sample.format.width == 12U, "sample width is 12", failures);
    expect(min_sample.format.frac == 0U, "sample frac is 0", failures);
    expect(min_sample.format.is_signed, "sample format is signed", failures);
    expect(min_sample.fits_declared_width(), "minimum sample fits", failures);
    expect(max_sample.fits_declared_width(), "maximum sample fits", failures);
    expect(min_sample.encoded() == 0x800U, "12-bit min encodes as 800", failures);
    expect(neg_one_sample.encoded() == 0xfffU, "12-bit -1 encodes as fff", failures);
    expect(zero_sample.encoded() == 0x000U, "12-bit 0 encodes as 000", failures);
    expect(max_sample.encoded() == 0x7ffU, "12-bit max encodes as 7ff", failures);

    expect_throws([] { static_cast<void>(sample_value(-2049, 12U)); }, "sample below range", failures);
    expect_throws([] { static_cast<void>(sample_value(2048, 12U)); }, "sample above range", failures);

    const FixedPointValue window_mid = window_value(32768U, 15U);
    expect(window_mid.format.width == 16U, "window width is F+1", failures);
    expect(window_mid.format.frac == 15U, "window frac is F", failures);
    expect(!window_mid.format.is_signed, "window format is unsigned", failures);
    expect(window_mid.fits_declared_width(), "window +1.0 coefficient fits", failures);
    expect(window_mid.encoded() == 0x8000U, "window +1.0 encodes as 8000", failures);

    const FixedPointValue bad_unsigned{-1, q_window(15U)};
    expect(!bad_unsigned.fits_declared_width(), "negative unsigned fixed point does not fit", failures);
    expect_throws([&bad_unsigned] { static_cast<void>(bad_unsigned.encoded()); }, "negative unsigned encode", failures);
    expect_throws([] { static_cast<void>(window_value(65536U, 15U)); }, "window width overflow", failures);

    const FixedPointValue twiddle_pos_one = twiddle_value(32768, 15U);
    const FixedPointValue twiddle_neg_one = twiddle_value(-32768, 15U);
    const FixedPointValue twiddle_neg_lsb = twiddle_value(-1, 15U);
    expect(twiddle_pos_one.format.width == 17U, "twiddle width is F+2", failures);
    expect(twiddle_pos_one.format.frac == 15U, "twiddle frac is F", failures);
    expect(twiddle_pos_one.format.is_signed, "twiddle format is signed", failures);
    expect(twiddle_pos_one.encoded() == 0x08000U, "17-bit +32768 encodes as 08000", failures);
    expect(twiddle_neg_one.encoded() == 0x18000U, "17-bit -32768 encodes as 18000", failures);
    expect(twiddle_neg_lsb.encoded() == 0x1ffffU, "17-bit -1 encodes as 1ffff", failures);
    expect_throws([] { static_cast<void>(twiddle_value(65536, 15U)); }, "twiddle signed max overflow", failures);
    expect_throws([] { static_cast<void>(twiddle_value(-65537, 15U)); }, "twiddle signed min overflow", failures);

    expect(fixed_hex_digits(12U) == 3U, "12-bit fixed hex digits", failures);
    expect(fixed_hex_digits(16U) == 4U, "16-bit fixed hex digits", failures);
    expect(fixed_hex_digits(17U) == 5U, "17-bit fixed hex digits", failures);

    return failures == 0 ? 0 : 1;
}
