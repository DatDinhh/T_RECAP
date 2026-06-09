// SPDX-License-Identifier: MIT
#include "trecap_golden/window.hpp"

namespace trecap::golden {
namespace {

static_assert(kBaselineWidths.W_Qw == 16U);
static_assert(kBaselineWidths.W_u == 27U);
static_assert(kBaselineWidths.W_z == 36U);

}  // namespace

WindowTable WindowTable::generated(const CoreConfig& core) {
    core.validate();
    WindowTable table{};
    table.cfg = core;
    table.q = generate_window_qw(core);
    table.validate();
    return table;
}

void WindowTable::validate() const {
    cfg.validate();
    if (q.size() != cfg.L) {
        throw contract_error("window table must contain exactly L entries");
    }
    const WidthConfig widths = WidthConfig::from_core(cfg);
    for (const auto value : q) {
        require_unsigned_fit(value, widths.W_Qw);
    }
}

std::uint64_t WindowTable::at(const unsigned index) const {
    if (index >= q.size()) {
        throw contract_error("window index outside table");
    }
    return q[index];
}

std::vector<std::int64_t> analysis_window_frame(std::span<const std::int64_t> frame,
                                                const WindowTable& window) {
    window.validate();
    if (frame.size() != window.cfg.L) {
        throw contract_error("analysis frame length must equal L");
    }

    const WidthConfig widths = WidthConfig::from_core(window.cfg);
    std::vector<std::int64_t> out;
    out.reserve(window.cfg.L);
    for (unsigned i = 0U; i < window.cfg.L; ++i) {
        require_signed_fit(frame[i], window.cfg.N);
        const std::int64_t coeff = static_cast<std::int64_t>(window.at(i));
        const std::int64_t product = exact_product(frame[i], coeff);
        out.push_back(require_signed_fit(product, widths.W_u));
    }
    return out;
}

std::int64_t synthesis_window_sample(const std::int64_t ifft_real,
                                     const std::uint64_t qwindow,
                                     const CoreConfig& cfg) {
    cfg.validate();
    const WidthConfig widths = WidthConfig::from_core(cfg);
    require_signed_fit(ifft_real, widths.W_ifft);
    require_unsigned_fit(qwindow, widths.W_Qw);
    const std::int64_t product = exact_product(ifft_real, static_cast<std::int64_t>(qwindow));
    const std::int64_t rounded = rnd_shr(product, cfg.F);
    return require_signed_fit(rounded, widths.W_z);
}

std::vector<std::int64_t> synthesis_window_frame(std::span<const ComplexI64> ifft_time, const WindowTable& window) {
    window.validate();
    if (ifft_time.size() != window.cfg.L) {
        throw contract_error("synthesis frame length must equal L");
    }

    std::vector<std::int64_t> out;
    out.reserve(window.cfg.L);
    for (unsigned i = 0U; i < window.cfg.L; ++i) {
        out.push_back(synthesis_window_sample(ifft_time[i].re, window.at(i), window.cfg));
    }
    return out;
}

}  // namespace trecap::golden
