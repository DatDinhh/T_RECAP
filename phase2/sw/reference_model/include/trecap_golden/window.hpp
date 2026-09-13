// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "trecap_golden/coeffs.hpp"
#include "trecap_golden/complex_int.hpp"
#include "trecap_golden/q_format.hpp"
#include "trecap_golden/signed_int.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

struct WindowTable final {
    CoreConfig cfg{CoreConfig::baseline()};
    std::vector<std::uint64_t> q{};

    [[nodiscard]] static WindowTable generated(const CoreConfig& core = CoreConfig::baseline());

    void validate() const;

    [[nodiscard]] std::uint64_t at(unsigned index) const;
};

[[nodiscard]] std::vector<std::int64_t> analysis_window_frame(std::span<const std::int64_t> frame,
                                                              const WindowTable& window);

[[nodiscard]] std::int64_t synthesis_window_sample(std::int64_t ifft_real,
                                                   std::uint64_t qwindow,
                                                   const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> synthesis_window_frame(std::span<const ComplexI64> ifft_time,
                                                               const WindowTable& window);

}  // namespace trecap::golden
