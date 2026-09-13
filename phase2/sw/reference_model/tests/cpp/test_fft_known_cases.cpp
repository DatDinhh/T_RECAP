// SPDX-License-Identifier: MIT
#include <cstdint>
#include <exception>
#include <iostream>
#include <string>
#include <vector>

#include "trecap_golden/fft_radix2_int.hpp"
#include "trecap_golden/ifft_radix2_int.hpp"

namespace {

void expect(const bool condition, const std::string& message, int& failures) {
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

void expect_complex_eq(const trecap::golden::ComplexI64 actual,
                       const trecap::golden::ComplexI64 expected,
                       const std::string& message,
                       int& failures) {
    if (actual != expected) {
        std::cerr << "FAIL: " << message << " got (" << actual.re << "," << actual.im << ") expected ("
                  << expected.re << "," << expected.im << ")\n";
        ++failures;
    }
}

}  // namespace

int main() {
    using namespace trecap::golden;

    int failures = 0;
    const CoreConfig cfg = CoreConfig::baseline();
    const TwiddleTables twiddles = TwiddleTables::generated(cfg);

    expect(bit_reverse(0b0000'0101U, cfg.P) == 0b1010'0000U, "8-bit bit reversal", failures);
    expect(twiddle_exponent(1U, 2U, cfg) == 128U, "stage-1 twiddle exponent", failures);
    expect(twiddle_exponent(3U, 16U, cfg) == 48U, "stage-4 twiddle exponent", failures);
    expect_throws([&cfg] { static_cast<void>(twiddle_exponent(0U, 0U, cfg)); }, "zero FFT span", failures);

    const std::vector<std::int64_t> zero_frame(cfg.L, 0);
    const std::vector<ComplexI64> zero_fft = fft_norm_radix2_int(zero_frame, twiddles);
    expect(zero_fft.size() == static_cast<std::size_t>(cfg.L), "zero FFT length", failures);
    for (const ComplexI64 bin : zero_fft) {
        expect_complex_eq(bin, ComplexI64{0, 0}, "zero input has all-zero FFT", failures);
    }
    const std::vector<ComplexI64> zero_ifft = ifft_unscaled_radix2_int(zero_fft, twiddles);
    for (const ComplexI64 sample : zero_ifft) {
        expect_complex_eq(sample, ComplexI64{0, 0}, "zero spectrum has all-zero IFFT", failures);
    }

    std::vector<std::int64_t> delta_frame(cfg.L, 0);
    delta_frame[0] = 32768;
    const std::vector<ComplexI64> delta_fft = fft_norm_radix2_int(delta_frame, twiddles);
    for (const ComplexI64 bin : delta_fft) {
        expect_complex_eq(bin, ComplexI64{128, 0}, "normalized FFT of QF delta", failures);
    }
    const std::vector<ComplexI64> delta_ifft = ifft_unscaled_radix2_int(delta_fft, twiddles);
    expect_complex_eq(delta_ifft[0], ComplexI64{32768, 0}, "IFFT(FFT(delta))[0]", failures);
    for (std::size_t i = 1U; i < delta_ifft.size(); ++i) {
        expect_complex_eq(delta_ifft[i], ComplexI64{0, 0}, "IFFT(FFT(delta))[i>0]", failures);
    }

    std::vector<std::int64_t> constant_frame(cfg.L, 32768);
    const std::vector<ComplexI64> constant_fft = fft_norm_radix2_int(constant_frame, twiddles);
    expect_complex_eq(constant_fft[0], ComplexI64{32768, 0}, "constant frame DC bin", failures);
    for (std::size_t k = 1U; k < constant_fft.size(); ++k) {
        expect_complex_eq(constant_fft[k], ComplexI64{0, 0}, "constant frame non-DC bin", failures);
    }
    const std::vector<ComplexI64> constant_ifft = ifft_unscaled_radix2_int(constant_fft, twiddles);
    for (const ComplexI64 sample : constant_ifft) {
        expect_complex_eq(sample, ComplexI64{32768, 0}, "IFFT(DC-only spectrum) reconstructs constant frame", failures);
    }

    std::vector<std::int64_t> alternating_frame(cfg.L, 0);
    for (std::size_t i = 0U; i < alternating_frame.size(); ++i) {
        alternating_frame[i] = ((i % 2U) == 0U) ? 32768 : -32768;
    }
    const std::vector<ComplexI64> alternating_fft = fft_norm_radix2_int(alternating_frame, twiddles);
    for (std::size_t k = 0U; k < alternating_fft.size(); ++k) {
        const ComplexI64 expected = (k == static_cast<std::size_t>(cfg.L / 2U)) ? ComplexI64{32768, 0}
                                                                                  : ComplexI64{0, 0};
        expect_complex_eq(alternating_fft[k], expected, "alternating frame Nyquist-only spectrum", failures);
    }
    const std::vector<ComplexI64> alternating_ifft = ifft_unscaled_radix2_int(alternating_fft, twiddles);
    for (std::size_t i = 0U; i < alternating_ifft.size(); ++i) {
        const ComplexI64 expected = ((i % 2U) == 0U) ? ComplexI64{32768, 0} : ComplexI64{-32768, 0};
        expect_complex_eq(alternating_ifft[i], expected, "IFFT(Nyquist-only spectrum) reconstructs alternating frame", failures);
    }

    expect_throws([&twiddles] { static_cast<void>(fft_norm_radix2_int(std::vector<std::int64_t>{0}, twiddles)); },
                  "FFT rejects wrong input length", failures);
    expect_throws([&twiddles] { static_cast<void>(ifft_unscaled_radix2_int(std::vector<ComplexI64>{ComplexI64{0, 0}}, twiddles)); },
                  "IFFT rejects wrong input length", failures);

    return failures == 0 ? 0 : 1;
}
