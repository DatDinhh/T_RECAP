// SPDX-License-Identifier: MIT
#include "trecap_golden/ifft_radix2_int.hpp"

namespace trecap::golden {
namespace {

static_assert(kBaselineWidths.W_can == 28U);
static_assert(kBaselineWidths.W_ifft == 36U);

}  // namespace

std::vector<ComplexI64> ifft_unscaled_radix2_int(std::span<const ComplexI64> spectrum,
                                                 const TwiddleTables& twiddles) {
    twiddles.validate();
    const CoreConfig cfg = twiddles.cfg;
    const WidthConfig widths = WidthConfig::from_core(cfg);
    if (spectrum.size() != cfg.L) {
        throw contract_error("IFFT input length must equal L");
    }

    std::vector<ComplexI64> b(cfg.L);
    for (unsigned k = 0U; k < cfg.L; ++k) {
        const auto src = static_cast<unsigned>(bit_reverse(k, cfg.P));
        require_signed_fit(spectrum[src].re, widths.W_can);
        require_signed_fit(spectrum[src].im, widths.W_can);
        b[k] = spectrum[src];
    }

    for (unsigned s = 1U; s <= cfg.P; ++s) {
        const unsigned span = 1U << s;
        const unsigned half = span >> 1U;
        for (unsigned base = 0U; base < cfg.L; base += span) {
            for (unsigned j = 0U; j < half; ++j) {
                const unsigned exponent = twiddle_exponent(j, span, cfg);
                const ComplexI64 t = cmul_to_fraction(b[base + j + half], twiddles.inv(exponent), cfg.F);
                const ComplexI64 old = b[base + j];
                b[base + j] = cadd(old, t);
                b[base + j + half] = csub(old, t);
                require_signed_fit(b[base + j].re, widths.W_ifft);
                require_signed_fit(b[base + j].im, widths.W_ifft);
                require_signed_fit(b[base + j + half].re, widths.W_ifft);
                require_signed_fit(b[base + j + half].im, widths.W_ifft);
            }
        }
    }

    return b;
}

std::vector<ComplexI64> ifft_unscaled_radix2_int(std::span<const ComplexI64> spectrum, const CoreConfig& cfg) {
    return ifft_unscaled_radix2_int(spectrum, TwiddleTables::generated(cfg));
}

}  // namespace trecap::golden
