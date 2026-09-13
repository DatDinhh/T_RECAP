// SPDX-License-Identifier: MIT
#include <cstdint>
#include <exception>
#include <iostream>
#include <string>
#include <vector>

#include "trecap_golden/hermitian.hpp"

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
    const unsigned nyq = cfg.L / 2U;

    std::vector<ComplexI64> raw(cfg.L, ComplexI64{0, 0});
    raw[0] = ComplexI64{17, 99};
    raw[nyq] = ComplexI64{-11, -77};
    raw[5] = ComplexI64{10, 3};
    raw[cfg.L - 5U] = ComplexI64{8, -5};
    raw[7] = ComplexI64{1, -1};
    raw[cfg.L - 7U] = ComplexI64{0, 0};

    const std::vector<ComplexI64> can = hermitian_canonicalize(raw, cfg);
    expect(can.size() == static_cast<std::size_t>(cfg.L), "canonical spectrum length", failures);
    expect_complex_eq(can[0], ComplexI64{17, 0}, "DC bin imaginary component forced to zero", failures);
    expect_complex_eq(can[nyq], ComplexI64{-11, 0}, "Nyquist bin imaginary component forced to zero", failures);
    expect_complex_eq(can[5], ComplexI64{9, 4}, "canonical mirrored bin positive side", failures);
    expect_complex_eq(can[cfg.L - 5U], ComplexI64{9, -4}, "canonical mirrored bin negative side", failures);
    expect_complex_eq(can[7], ComplexI64{1, -1}, "canonical odd/tie rounding positive real and negative imag", failures);
    expect_complex_eq(can[cfg.L - 7U], ComplexI64{1, 1}, "canonical odd/tie rounding conjugate side", failures);
    expect(is_hermitian_symmetric(can, cfg), "canonicalized spectrum is Hermitian symmetric", failures);

    std::vector<ComplexI64> broken = can;
    broken[0].im = 1;
    expect(!is_hermitian_symmetric(broken, cfg), "DC imaginary component breaks Hermitian symmetry", failures);
    broken = can;
    broken[3].re += 1;
    expect(!is_hermitian_symmetric(broken, cfg), "mirrored real mismatch breaks Hermitian symmetry", failures);
    broken = can;
    broken[4].im += 1;
    expect(!is_hermitian_symmetric(broken, cfg), "mirrored imaginary mismatch breaks Hermitian symmetry", failures);
    expect(!is_hermitian_symmetric(std::vector<ComplexI64>{ComplexI64{0, 0}}, cfg), "wrong spectrum length is not symmetric", failures);

    expect_throws([&cfg] { static_cast<void>(hermitian_canonicalize(std::vector<ComplexI64>{ComplexI64{0, 0}}, cfg)); },
                  "canonicalization rejects wrong input length", failures);

    std::vector<ComplexI64> out_of_width(cfg.L, ComplexI64{0, 0});
    out_of_width[0].re = (std::int64_t{1} << 27U);
    expect_throws([&out_of_width, &cfg] { static_cast<void>(hermitian_canonicalize(out_of_width, cfg)); },
                  "canonicalization range-checks W_can", failures);

    return failures == 0 ? 0 : 1;
}
