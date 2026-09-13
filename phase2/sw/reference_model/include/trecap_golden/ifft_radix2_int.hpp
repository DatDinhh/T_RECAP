// SPDX-License-Identifier: MIT
#pragma once

#include <span>
#include <vector>

#include "trecap_golden/complex_int.hpp"
#include "trecap_golden/twiddles.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

[[nodiscard]] std::vector<ComplexI64> ifft_unscaled_radix2_int(std::span<const ComplexI64> spectrum,
                                                               const TwiddleTables& twiddles);

[[nodiscard]] std::vector<ComplexI64> ifft_unscaled_radix2_int(std::span<const ComplexI64> spectrum,
                                                               const CoreConfig& cfg = CoreConfig::baseline());

}  // namespace trecap::golden
