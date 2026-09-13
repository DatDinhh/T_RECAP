// SPDX-License-Identifier: MIT
#pragma once

#include <span>
#include <vector>

#include "trecap_golden/complex_int.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

[[nodiscard]] std::vector<ComplexI64> hermitian_canonicalize(std::span<const ComplexI64> spectrum,
                                                             const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] bool is_hermitian_symmetric(std::span<const ComplexI64> spectrum,
                                          const CoreConfig& cfg = CoreConfig::baseline());

}  // namespace trecap::golden
