// SPDX-License-Identifier: MIT
#include "trecap_golden/hermitian.hpp"

namespace trecap::golden {
namespace {

static_assert(kBaselineWidths.W_can == 28U);
static_assert(kBaselineWidths.W_can_pre == 29U);

}  // namespace

std::vector<ComplexI64> hermitian_canonicalize(std::span<const ComplexI64> spectrum, const CoreConfig& cfg) {
    cfg.validate();
    if (spectrum.size() != cfg.L) {
        throw contract_error("canonicalization input length must equal L");
    }

    const WidthConfig widths = WidthConfig::from_core(cfg);
    std::vector<ComplexI64> out(cfg.L);

    out[0] = ComplexI64{require_signed_fit(spectrum[0].re, widths.W_can), 0};
    const unsigned nyq = cfg.L / 2U;
    out[nyq] = ComplexI64{require_signed_fit(spectrum[nyq].re, widths.W_can), 0};

    for (unsigned k = 1U; k < nyq; ++k) {
        const auto pair = hermitian_canonical_pair(spectrum[k], spectrum[cfg.L - k]);
        out[k] = ComplexI64{require_signed_fit(pair.positive_bin.re, widths.W_can),
                            require_signed_fit(pair.positive_bin.im, widths.W_can)};
        out[cfg.L - k] = ComplexI64{require_signed_fit(pair.negative_bin.re, widths.W_can),
                                    require_signed_fit(pair.negative_bin.im, widths.W_can)};
    }

    return out;
}

bool is_hermitian_symmetric(std::span<const ComplexI64> spectrum, const CoreConfig& cfg) {
    cfg.validate();
    if (spectrum.size() != cfg.L) {
        return false;
    }
    if (spectrum[0].im != 0 || spectrum[cfg.L / 2U].im != 0) {
        return false;
    }
    for (unsigned k = 1U; k < cfg.L / 2U; ++k) {
        const ComplexI64 positive = spectrum[k];
        const ComplexI64 negative = spectrum[cfg.L - k];
        if (positive.re != negative.re || positive.im != -negative.im) {
            return false;
        }
    }
    return true;
}

}  // namespace trecap::golden
