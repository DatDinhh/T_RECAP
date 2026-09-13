// SPDX-License-Identifier: MIT
#include <cstdint>
#include <exception>
#include <iostream>
#include <string>
#include <vector>

#include "trecap_golden/mask.hpp"

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

    std::vector<ComplexI64> canonical(cfg.L, ComplexI64{10, 0});
    canonical[0] = ComplexI64{1, 0};
    canonical[1] = ComplexI64{3, 4};
    canonical[cfg.L - 1U] = ComplexI64{3, -4};
    canonical[nyq] = ComplexI64{2, 0};

    const MaskResult result = compute_mask_decisions(canonical, 26U, 12U, cfg);
    expect(result.bins.size() == static_cast<std::size_t>(cfg.unique_bins()), "mask decision count", failures);
    expect(result.frame_stats.frame_idx == 12U, "mask frame index", failures);
    expect(result.frame_stats.unique_bins == cfg.unique_bins(), "unique bin denominator", failures);
    expect(result.frame_stats.unique_suppressed_bins == 2U, "post-protection unique suppressed count", failures);
    expect(result.frame_stats.eligible_unique_bins == cfg.unique_bins() - 1U, "DC protection removes one eligible bin", failures);
    expect(result.frame_stats.eligible_suppressed_bins == 2U, "eligible suppressed count", failures);
    expect(metric_to_decimal_string(result.frame_stats.eligible_total_mag2) == "25254", "weighted eligible total mag2", failures);
    expect(metric_to_decimal_string(result.frame_stats.eligible_kept_mag2) == "25200", "weighted eligible kept mag2", failures);

    expect(result.bins[0].bin_idx == 0U, "DC bin index", failures);
    expect(!result.bins[0].eligible, "DC bin protected from eligibility", failures);
    expect(result.bins[0].pre_mask, "DC pre-mask retained for debug", failures);
    expect(!result.bins[0].mask, "DC protection forces final keep", failures);
    expect(result.bins[1].eligible && result.bins[1].pre_mask && result.bins[1].mask, "bin 1 suppressed", failures);
    expect(result.bins[nyq].eligible && result.bins[nyq].pre_mask && result.bins[nyq].mask, "Nyquist suppressed when not protected", failures);

    const std::vector<ComplexI64> masked = apply_unique_bin_mask(canonical, result.bins, cfg);
    expect(is_hermitian_symmetric(masked, cfg), "masked spectrum remains Hermitian symmetric", failures);
    expect_complex_eq(masked[0], ComplexI64{1, 0}, "protected DC bin is kept", failures);
    expect_complex_eq(masked[1], ComplexI64{0, 0}, "suppressed bin 1 is zeroed", failures);
    expect_complex_eq(masked[cfg.L - 1U], ComplexI64{0, 0}, "suppressed mirror bin is zeroed", failures);
    expect_complex_eq(masked[2], ComplexI64{10, 0}, "kept interior bin is preserved", failures);
    expect_complex_eq(masked[nyq], ComplexI64{0, 0}, "suppressed Nyquist bin is zeroed", failures);

    const MaskResult no_suppression = compute_mask_decisions(canonical, 0U, 0U, cfg);
    expect(no_suppression.frame_stats.unique_suppressed_bins == 0U, "THR2=0 suppresses no bins", failures);
    expect(no_suppression.frame_stats.eligible_suppressed_bins == 0U, "THR2=0 suppresses no eligible bins", failures);

    expect(threshold_is_legal((std::uint64_t{1} << 56U) - 1U, WidthConfig::from_core(cfg).W_mag2),
           "largest 56-bit THR2 is legal", failures);
    expect(!threshold_is_legal(std::uint64_t{1} << 56U, WidthConfig::from_core(cfg).W_mag2),
           "2^56 THR2 is illegal", failures);
    expect_throws([&canonical, &cfg] { static_cast<void>(compute_mask_decisions(canonical, std::uint64_t{1} << 56U, 0U, cfg)); },
                  "mask rejects out-of-range THR2", failures);
    expect_throws([&cfg] { static_cast<void>(compute_mask_decisions(std::vector<ComplexI64>{ComplexI64{0, 0}}, 0U, 0U, cfg)); },
                  "mask rejects wrong spectrum length", failures);

    std::vector<BinMaskDecision> bad_order = result.bins;
    bad_order[1].bin_idx = 2U;
    expect_throws([&canonical, &bad_order, &cfg] { static_cast<void>(apply_unique_bin_mask(canonical, bad_order, cfg)); },
                  "mask application rejects out-of-order bin decisions", failures);

    return failures == 0 ? 0 : 1;
}
