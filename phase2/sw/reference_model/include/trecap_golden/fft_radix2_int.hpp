// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "trecap_golden/complex_int.hpp"
#include "trecap_golden/twiddles.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

[[nodiscard]] std::vector<ComplexI64> fft_norm_radix2_int(std::span<const std::int64_t> u,
                                                          const TwiddleTables& twiddles);

[[nodiscard]] std::vector<ComplexI64> fft_norm_radix2_int(std::span<const std::int64_t> u,
                                                          const CoreConfig& cfg = CoreConfig::baseline());

}  // namespace trecap::golden
