// SPDX-License-Identifier: MIT
#include "trecap_golden/fft_radix2_int.hpp"

namespace trecap::golden {
namespace {

static_assert(kBaselineWidths.W_u == 27U);
static_assert(kBaselineWidths.W_fft == 28U);
static_assert(kBaselineWidths.W_fft_pre == 29U);

}  // namespace

std::vector<ComplexI64> fft_norm_radix2_int(std::span<const std::int64_t> u, const TwiddleTables& twiddles) {
    twiddles.validate();
    const CoreConfig cfg = twiddles.cfg;
    const WidthConfig widths = WidthConfig::from_core(cfg);
    if (u.size() != cfg.L) {
        throw contract_error("FFT input length must equal L");
    }

    std::vector<ComplexI64> a(cfg.L);
    for (unsigned k = 0U; k < cfg.L; ++k) {
        const auto src = static_cast<unsigned>(bit_reverse(k, cfg.P));
        require_signed_fit(u[src], widths.W_u);
        a[k] = ComplexI64{u[src], 0};
    }

    for (unsigned s = 1U; s <= cfg.P; ++s) {
        const unsigned span = 1U << s;
        const unsigned half = span >> 1U;
        for (unsigned base = 0U; base < cfg.L; base += span) {
            for (unsigned j = 0U; j < half; ++j) {
                const unsigned exponent = twiddle_exponent(j, span, cfg);
                const ComplexI64 t = cmul_to_fraction(a[base + j + half], twiddles.fwd(exponent), cfg.F);
                const ComplexI64 old = a[base + j];
                const ComplexI64 sum = cadd(old, t);
                const ComplexI64 diff = csub(old, t);
                a[base + j] = rnd2_complex(sum);
                a[base + j + half] = rnd2_complex(diff);
                require_signed_fit(a[base + j].re, widths.W_fft);
                require_signed_fit(a[base + j].im, widths.W_fft);
                require_signed_fit(a[base + j + half].re, widths.W_fft);
                require_signed_fit(a[base + j + half].im, widths.W_fft);
            }
        }
    }

    return a;
}

std::vector<ComplexI64> fft_norm_radix2_int(std::span<const std::int64_t> u, const CoreConfig& cfg) {
    return fft_norm_radix2_int(u, TwiddleTables::generated(cfg));
}

}  // namespace trecap::golden
