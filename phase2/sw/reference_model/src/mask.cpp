// SPDX-License-Identifier: MIT
#include "trecap_golden/mask.hpp"

#include <algorithm>
#include <iomanip>
#include <limits>
#include <sstream>
#include <utility>

namespace trecap::golden {
namespace {

static_assert(threshold_is_legal(0U, kBaselineWidths.W_mag2));
static_assert(threshold_is_legal((std::uint64_t{1} << kBaselineWidths.W_mag2) - 1U, kBaselineWidths.W_mag2));
static_assert(!threshold_is_legal(std::uint64_t{1} << kBaselineWidths.W_mag2, kBaselineWidths.W_mag2));
static_assert(!unique_bin_is_eligible(0U, CoreConfig::baseline()));
static_assert(unique_bin_weight(1U, CoreConfig::baseline()) == 2U);

}  // namespace

MetricUint::MetricUint(std::uint64_t value) {
    while (value != 0U) {
        limbs_.push_back(static_cast<std::uint32_t>(value % kBase));
        value /= kBase;
    }
}

bool MetricUint::is_zero() const noexcept {
    return limbs_.empty();
}

void MetricUint::add(const MetricUint& other) {
    const std::size_t n = std::max(limbs_.size(), other.limbs_.size());
    limbs_.resize(n, 0U);
    std::uint64_t carry = 0U;
    for (std::size_t i = 0U; i < n; ++i) {
        const std::uint64_t rhs = i < other.limbs_.size() ? other.limbs_[i] : 0U;
        const std::uint64_t sum = static_cast<std::uint64_t>(limbs_[i]) + rhs + carry;
        limbs_[i] = static_cast<std::uint32_t>(sum % kBase);
        carry = sum / kBase;
    }
    if (carry != 0U) {
        limbs_.push_back(static_cast<std::uint32_t>(carry));
    }
}

std::string MetricUint::to_decimal_string() const {
    if (limbs_.empty()) {
        return "0";
    }
    std::ostringstream oss;
    oss << limbs_.back();
    for (auto it = limbs_.rbegin() + 1; it != limbs_.rend(); ++it) {
        oss << std::setw(9) << std::setfill('0') << *it;
    }
    return oss.str();
}

MetricUint metric_from_u64(const std::uint64_t value) {
    return MetricUint(value);
}

MetricUint metric_add(MetricUint lhs, const MetricUint& rhs) {
    lhs.add(rhs);
    return lhs;
}

MetricUint metric_mul_u64(const std::uint64_t lhs, std::uint64_t rhs) {
    MetricUint result{};
    MetricUint addend(lhs);
    while (rhs != 0U) {
        if ((rhs & 1U) != 0U) {
            result.add(addend);
        }
        rhs >>= 1U;
        if (rhs != 0U) {
            addend.add(addend);
        }
    }
    return result;
}

std::string metric_to_decimal_string(const MetricUint& value) {
    return value.to_decimal_string();
}

MaskResult compute_mask_decisions(std::span<const ComplexI64> canonical_spectrum,
                                  const std::uint64_t thr2,
                                  const std::uint64_t frame_idx,
                                  const CoreConfig& cfg) {
    cfg.validate();
    const WidthConfig widths = WidthConfig::from_core(cfg);
    if (!threshold_is_legal(thr2, widths.W_mag2)) {
        throw contract_error("THR2 is outside the W_mag2 domain");
    }
    if (canonical_spectrum.size() != cfg.L) {
        throw contract_error("mask input length must equal L");
    }

    MaskResult result{};
    result.frame_stats.frame_idx = frame_idx;
    result.frame_stats.unique_bins = cfg.unique_bins();
    result.bins.reserve(cfg.unique_bins());

    for (unsigned k = 0U; k <= cfg.L / 2U; ++k) {
        const ComplexI64 value = canonical_spectrum[k];
        require_signed_fit(value.re, widths.W_can);
        require_signed_fit(value.im, widths.W_can);
        const std::uint64_t mag2 = magnitude_squared_u64(value);
        const bool eligible = unique_bin_is_eligible(k, cfg);
        const bool pre_mask = mag2 < thr2;
        bool final_mask = pre_mask;
        if (!eligible) {
            final_mask = false;
        }

        const std::uint64_t weight = unique_bin_weight(k, cfg);
        if (final_mask) {
            ++result.frame_stats.unique_suppressed_bins;
        }
        if (eligible) {
            ++result.frame_stats.eligible_unique_bins;
            const MetricUint weighted = metric_mul_u64(weight, mag2);
            result.frame_stats.eligible_total_mag2 = metric_add(result.frame_stats.eligible_total_mag2, weighted);
            if (final_mask) {
                ++result.frame_stats.eligible_suppressed_bins;
            } else {
                result.frame_stats.eligible_kept_mag2 = metric_add(result.frame_stats.eligible_kept_mag2, weighted);
            }
        }

        result.bins.push_back(BinMaskDecision{k, value.re, value.im, mag2, eligible, pre_mask, final_mask});
    }

    return result;
}

std::vector<ComplexI64> apply_unique_bin_mask(std::span<const ComplexI64> canonical_spectrum,
                                              std::span<const BinMaskDecision> decisions,
                                              const CoreConfig& cfg) {
    cfg.validate();
    if (canonical_spectrum.size() != cfg.L) {
        throw contract_error("masked-spectrum input length must equal L");
    }
    if (decisions.size() != cfg.unique_bins()) {
        throw contract_error("mask decision count must equal L/2+1");
    }

    std::vector<ComplexI64> out(cfg.L, ComplexI64{0, 0});
    for (unsigned k = 1U; k < cfg.L / 2U; ++k) {
        if (decisions[k].bin_idx != k) {
            throw contract_error("mask decision bin index is not in canonical order");
        }
        const bool suppressed = decisions[k].mask;
        if (!suppressed) {
            out[k] = canonical_spectrum[k];
            out[cfg.L - k] = canonical_spectrum[cfg.L - k];
        }
    }

    if (decisions[0].bin_idx != 0U || decisions[cfg.L / 2U].bin_idx != cfg.L / 2U) {
        throw contract_error("self-conjugate mask decision indices are invalid");
    }
    out[0] = decisions[0].mask ? ComplexI64{0, 0} : canonical_spectrum[0];
    out[cfg.L / 2U] = decisions[cfg.L / 2U].mask ? ComplexI64{0, 0} : canonical_spectrum[cfg.L / 2U];

    if (!is_hermitian_symmetric(out, cfg)) {
        throw contract_error("masked spectrum is not Hermitian symmetric");
    }
    return out;
}

}  // namespace trecap::golden
