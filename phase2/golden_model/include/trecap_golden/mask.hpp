// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <span>
#include <string>
#include <vector>

#include "trecap_golden/complex_int.hpp"
#include "trecap_golden/hermitian.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

class MetricUint final {
public:
    MetricUint() = default;

    explicit MetricUint(std::uint64_t value);

    [[nodiscard]] bool is_zero() const noexcept;

    void add(const MetricUint& other);

    [[nodiscard]] std::string to_decimal_string() const;

    [[nodiscard]] friend bool operator==(const MetricUint& lhs, const MetricUint& rhs) noexcept = default;

private:
    static constexpr std::uint32_t kBase = 1000000000U;
    std::vector<std::uint32_t> limbs_{};
};

[[nodiscard]] MetricUint metric_from_u64(std::uint64_t value);

[[nodiscard]] MetricUint metric_add(MetricUint lhs, const MetricUint& rhs);

[[nodiscard]] MetricUint metric_mul_u64(std::uint64_t lhs, std::uint64_t rhs);

[[nodiscard]] std::string metric_to_decimal_string(const MetricUint& value);

struct BinMaskDecision final {
    unsigned bin_idx{};
    std::int64_t real{};
    std::int64_t imag{};
    std::uint64_t mag2{};
    bool eligible{};
    bool pre_mask{};
    bool mask{};
};

struct FrameStats final {
    std::uint64_t frame_idx{};
    std::uint64_t unique_bins{};
    std::uint64_t unique_suppressed_bins{};
    std::uint64_t eligible_unique_bins{};
    std::uint64_t eligible_suppressed_bins{};
    MetricUint eligible_kept_mag2{};
    MetricUint eligible_total_mag2{};
};

struct MaskResult final {
    std::vector<BinMaskDecision> bins{};
    FrameStats frame_stats{};
};

[[nodiscard]] constexpr bool threshold_is_legal(const std::uint64_t thr2, const unsigned width) {
    require_width(width, 64U);
    if (width == 64U) {
        return true;
    }
    return thr2 < (std::uint64_t{1} << width);
}

[[nodiscard]] constexpr bool unique_bin_is_eligible(const unsigned k, const CoreConfig& cfg) {
    if (k == 0U && cfg.protect_dc) {
        return false;
    }
    if (k == cfg.L / 2U && cfg.protect_nyq) {
        return false;
    }
    return true;
}

[[nodiscard]] constexpr std::uint64_t unique_bin_weight(const unsigned k, const CoreConfig& cfg) {
    return (k == 0U || k == cfg.L / 2U) ? 1U : 2U;
}

[[nodiscard]] MaskResult compute_mask_decisions(std::span<const ComplexI64> canonical_spectrum,
                                                std::uint64_t thr2,
                                                std::uint64_t frame_idx,
                                                const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<ComplexI64> apply_unique_bin_mask(std::span<const ComplexI64> canonical_spectrum,
                                                            std::span<const BinMaskDecision> decisions,
                                                            const CoreConfig& cfg = CoreConfig::baseline());

}  // namespace trecap::golden
