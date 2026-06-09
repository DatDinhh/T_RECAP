// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <string>
#include <string_view>

#include "trecap_golden/stft_wola_model.hpp"

namespace trecap::golden {

struct SuppressionTotalsStrings final {
    std::string unique_bins{};
    std::string unique_suppressed_bins{};
    std::string eligible_unique_bins{};
    std::string eligible_suppressed_bins{};
};

struct SpectralTotalsStrings final {
    std::string eligible_kept_mag2{};
    std::string eligible_total_mag2{};
};

struct TimeDomainErrorStrings final {
    std::string sum_abs_err{};
    std::string sum_sq_err{};
    std::string max_abs_err{};
    std::string error_sample_count{};
};

struct MetricsStrings final {
    SuppressionTotalsStrings suppression{};
    SpectralTotalsStrings spectral{};
    TimeDomainErrorStrings time{};
};

[[nodiscard]] bool canonical_unsigned_decimal_string(std::string_view text);

[[nodiscard]] MetricsStrings metrics_to_strings(const StftWolaMetrics& metrics);

[[nodiscard]] long double decimal_string_to_long_double(std::string_view text);

[[nodiscard]] long double metric_ratio(const MetricUint& numerator, const MetricUint& denominator);

[[nodiscard]] long double eligible_suppression_ratio(const StftWolaMetrics& metrics);

[[nodiscard]] long double kept_energy_ratio(const StftWolaMetrics& metrics);

[[nodiscard]] long double rmse_from_time_errors(const TimeErrorMetrics& metrics);

[[nodiscard]] bool no_suppression_invariant_holds(const StftWolaMetrics& metrics);

}  // namespace trecap::golden
