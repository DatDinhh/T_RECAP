// SPDX-License-Identifier: MIT
#include "trecap_golden/metrics.hpp"

#include <cmath>
#include <limits>

namespace trecap::golden {
namespace {

static_assert(kBaselineWidths.W_mag2 == 56U);

}  // namespace

bool canonical_unsigned_decimal_string(const std::string_view text) {
    if (text.empty()) {
        return false;
    }
    if (text == "0") {
        return true;
    }
    if (text.front() == '0') {
        return false;
    }
    for (const char ch : text) {
        if (ch < '0' || ch > '9') {
            return false;
        }
    }
    return true;
}

MetricsStrings metrics_to_strings(const StftWolaMetrics& metrics) {
    return MetricsStrings{
        SuppressionTotalsStrings{metric_to_decimal_string(metrics.unique_bins),
                                 metric_to_decimal_string(metrics.unique_suppressed_bins),
                                 metric_to_decimal_string(metrics.eligible_unique_bins),
                                 metric_to_decimal_string(metrics.eligible_suppressed_bins)},
        SpectralTotalsStrings{metric_to_decimal_string(metrics.eligible_kept_mag2),
                              metric_to_decimal_string(metrics.eligible_total_mag2)},
        TimeDomainErrorStrings{metric_to_decimal_string(metrics.time_domain_errors.sum_abs_err),
                               metric_to_decimal_string(metrics.time_domain_errors.sum_sq_err),
                               std::to_string(metrics.time_domain_errors.max_abs_err),
                               std::to_string(metrics.time_domain_errors.error_sample_count)}};
}

long double decimal_string_to_long_double(const std::string_view text) {
    if (!canonical_unsigned_decimal_string(text)) {
        throw contract_error("metric field is not a canonical unsigned decimal string");
    }
    long double value = 0.0L;
    for (const char ch : text) {
        value = (value * 10.0L) + static_cast<long double>(ch - '0');
    }
    return value;
}

long double metric_ratio(const MetricUint& numerator, const MetricUint& denominator) {
    const std::string den = metric_to_decimal_string(denominator);
    if (den == "0") {
        return std::numeric_limits<long double>::quiet_NaN();
    }
    return decimal_string_to_long_double(metric_to_decimal_string(numerator)) / decimal_string_to_long_double(den);
}

long double eligible_suppression_ratio(const StftWolaMetrics& metrics) {
    return metric_ratio(metrics.eligible_suppressed_bins, metrics.eligible_unique_bins);
}

long double kept_energy_ratio(const StftWolaMetrics& metrics) {
    return metric_ratio(metrics.eligible_kept_mag2, metrics.eligible_total_mag2);
}

long double rmse_from_time_errors(const TimeErrorMetrics& metrics) {
    if (metrics.error_sample_count == 0U) {
        return std::numeric_limits<long double>::quiet_NaN();
    }
    const long double sum_sq = decimal_string_to_long_double(metric_to_decimal_string(metrics.sum_sq_err));
    return std::sqrt(sum_sq / static_cast<long double>(metrics.error_sample_count));
}

bool no_suppression_invariant_holds(const StftWolaMetrics& metrics) {
    return metric_to_decimal_string(metrics.eligible_suppressed_bins) == "0";
}

}  // namespace trecap::golden
