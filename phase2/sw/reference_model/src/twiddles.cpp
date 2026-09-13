// SPDX-License-Identifier: MIT
#include "trecap_golden/twiddles.hpp"

namespace trecap::golden {
namespace {

static_assert(bit_reverse(0b00000101U, 8U) == 0b10100000U);
static_assert(twiddle_exponent(1U, 2U, CoreConfig::baseline()) == 128U);
static_assert(twiddle_exponent(3U, 8U, CoreConfig::baseline()) == 96U);

}  // namespace

TwiddleTables TwiddleTables::generated(const CoreConfig& core) {
    core.validate();
    const auto fwd_re = generate_twiddle_re(core);
    const auto fwd_im = generate_twiddle_im(core);
    const auto inv_re = generate_twiddle_inv_re(core);
    const auto inv_im = generate_twiddle_inv_im(core);

    TwiddleTables tables{};
    tables.cfg = core;
    tables.forward.reserve(core.L);
    tables.inverse.reserve(core.L);
    for (unsigned e = 0U; e < core.L; ++e) {
        tables.forward.push_back(ComplexI64{fwd_re.at(e), fwd_im.at(e)});
        tables.inverse.push_back(ComplexI64{inv_re.at(e), inv_im.at(e)});
    }
    tables.validate();
    return tables;
}

void TwiddleTables::validate() const {
    cfg.validate();
    if (forward.size() != cfg.L || inverse.size() != cfg.L) {
        throw contract_error("twiddle tables must contain exactly L entries");
    }
    const WidthConfig widths = WidthConfig::from_core(cfg);
    for (const auto& tw : forward) {
        require_signed_fit(tw.re, widths.W_tw);
        require_signed_fit(tw.im, widths.W_tw);
    }
    for (const auto& tw : inverse) {
        require_signed_fit(tw.re, widths.W_tw);
        require_signed_fit(tw.im, widths.W_tw);
    }
}

ComplexI64 TwiddleTables::fwd(const unsigned exponent) const {
    if (exponent >= forward.size()) {
        throw contract_error("forward twiddle exponent outside table");
    }
    return forward[exponent];
}

ComplexI64 TwiddleTables::inv(const unsigned exponent) const {
    if (exponent >= inverse.size()) {
        throw contract_error("inverse twiddle exponent outside table");
    }
    return inverse[exponent];
}

std::vector<ComplexI64> make_forward_twiddle_table(const CoreConfig& cfg) {
    return TwiddleTables::generated(cfg).forward;
}

std::vector<ComplexI64> make_inverse_twiddle_table(const CoreConfig& cfg) {
    return TwiddleTables::generated(cfg).inverse;
}

}  // namespace trecap::golden
