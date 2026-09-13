// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <string_view>
#include <vector>

#include "trecap_golden/rounding.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

enum class CoefficientFileKind : std::uint8_t {
    window_qw,
    twiddle_re,
    twiddle_im,
    twiddle_inv_re,
    twiddle_inv_im,
};

struct CoefficientFileSpec final {
    CoefficientFileKind kind{};
    std::string_view filename{};
    bool is_signed{};
    unsigned width{};
    unsigned line_count{};
    unsigned fractional_bits{};
};

[[nodiscard]] std::vector<CoefficientFileSpec> coefficient_file_specs(const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] long double periodic_hann(unsigned i, unsigned L);

[[nodiscard]] long double periodic_sqrt_hann(unsigned i, unsigned L);

[[nodiscard]] std::uint64_t qwindow_value(unsigned i, const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::int64_t qtwiddle_forward_re(unsigned e, const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::int64_t qtwiddle_forward_im(unsigned e, const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::int64_t qtwiddle_inverse_re(unsigned e, const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::int64_t qtwiddle_inverse_im(unsigned e, const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::uint64_t> generate_window_qw(const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_twiddle_re(const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_twiddle_im(const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_twiddle_inv_re(const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_twiddle_inv_im(const CoreConfig& cfg = CoreConfig::baseline());

}  // namespace trecap::golden
