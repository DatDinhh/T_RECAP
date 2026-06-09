// SPDX-License-Identifier: MIT
#include "trecap_golden/coeffs.hpp"

#include <cmath>
#include <numbers>

namespace trecap::golden {

std::vector<CoefficientFileSpec> coefficient_file_specs(const CoreConfig& cfg) {
    cfg.validate();
    const WidthConfig widths = WidthConfig::from_core(cfg);
    return {
        {CoefficientFileKind::window_qw, "window_qw.memh", false, widths.W_Qw, cfg.L, cfg.F},
        {CoefficientFileKind::twiddle_re, "twiddle_re.memh", true, widths.W_tw, cfg.L, cfg.F},
        {CoefficientFileKind::twiddle_im, "twiddle_im.memh", true, widths.W_tw, cfg.L, cfg.F},
        {CoefficientFileKind::twiddle_inv_re, "twiddle_inv_re.memh", true, widths.W_tw, cfg.L, cfg.F},
        {CoefficientFileKind::twiddle_inv_im, "twiddle_inv_im.memh", true, widths.W_tw, cfg.L, cfg.F},
    };
}

long double periodic_hann(const unsigned i, const unsigned L) {
    if (L == 0U) {
        throw contract_error("periodic_hann requires nonzero L");
    }
    const long double theta = (2.0L * std::numbers::pi_v<long double> * static_cast<long double>(i)) /
                              static_cast<long double>(L);
    return 0.5L - 0.5L * std::cos(theta);
}

long double periodic_sqrt_hann(const unsigned i, const unsigned L) {
    const long double value = periodic_hann(i, L);
    return std::sqrt(value < 0.0L ? 0.0L : value);
}

std::uint64_t qwindow_value(const unsigned i, const CoreConfig& cfg) {
    cfg.validate();
    const std::int64_t q = qcoef(periodic_sqrt_hann(i, cfg.L), cfg.F);
    if (q < 0) {
        throw contract_error("window coefficient must be nonnegative");
    }
    return require_unsigned_fit(static_cast<std::uint64_t>(q), WidthConfig::from_core(cfg).W_Qw);
}

std::int64_t qtwiddle_forward_re(const unsigned e, const CoreConfig& cfg) {
    cfg.validate();
    const long double theta = (2.0L * std::numbers::pi_v<long double> * static_cast<long double>(e)) /
                              static_cast<long double>(cfg.L);
    return require_signed_fit(qcoef(std::cos(theta), cfg.F), WidthConfig::from_core(cfg).W_tw);
}

std::int64_t qtwiddle_forward_im(const unsigned e, const CoreConfig& cfg) {
    cfg.validate();
    const long double theta = (2.0L * std::numbers::pi_v<long double> * static_cast<long double>(e)) /
                              static_cast<long double>(cfg.L);
    return require_signed_fit(qcoef(-std::sin(theta), cfg.F), WidthConfig::from_core(cfg).W_tw);
}

std::int64_t qtwiddle_inverse_re(const unsigned e, const CoreConfig& cfg) {
    return qtwiddle_forward_re(e, cfg);
}

std::int64_t qtwiddle_inverse_im(const unsigned e, const CoreConfig& cfg) {
    cfg.validate();
    const long double theta = (2.0L * std::numbers::pi_v<long double> * static_cast<long double>(e)) /
                              static_cast<long double>(cfg.L);
    return require_signed_fit(qcoef(std::sin(theta), cfg.F), WidthConfig::from_core(cfg).W_tw);
}

std::vector<std::uint64_t> generate_window_qw(const CoreConfig& cfg) {
    cfg.validate();
    std::vector<std::uint64_t> values;
    values.reserve(cfg.L);
    for (unsigned i = 0U; i < cfg.L; ++i) {
        values.push_back(qwindow_value(i, cfg));
    }
    return values;
}

std::vector<std::int64_t> generate_twiddle_re(const CoreConfig& cfg) {
    cfg.validate();
    std::vector<std::int64_t> values;
    values.reserve(cfg.L);
    for (unsigned e = 0U; e < cfg.L; ++e) {
        values.push_back(qtwiddle_forward_re(e, cfg));
    }
    return values;
}

std::vector<std::int64_t> generate_twiddle_im(const CoreConfig& cfg) {
    cfg.validate();
    std::vector<std::int64_t> values;
    values.reserve(cfg.L);
    for (unsigned e = 0U; e < cfg.L; ++e) {
        values.push_back(qtwiddle_forward_im(e, cfg));
    }
    return values;
}

std::vector<std::int64_t> generate_twiddle_inv_re(const CoreConfig& cfg) {
    cfg.validate();
    std::vector<std::int64_t> values;
    values.reserve(cfg.L);
    for (unsigned e = 0U; e < cfg.L; ++e) {
        values.push_back(qtwiddle_inverse_re(e, cfg));
    }
    return values;
}

std::vector<std::int64_t> generate_twiddle_inv_im(const CoreConfig& cfg) {
    cfg.validate();
    std::vector<std::int64_t> values;
    values.reserve(cfg.L);
    for (unsigned e = 0U; e < cfg.L; ++e) {
        values.push_back(qtwiddle_inverse_im(e, cfg));
    }
    return values;
}

}  // namespace trecap::golden
