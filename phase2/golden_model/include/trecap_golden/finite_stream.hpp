// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "trecap_golden/mask.hpp"
#include "trecap_golden/rounding.hpp"
#include "trecap_golden/saturation.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

[[nodiscard]] std::int64_t zero_extended_sample(std::span<const std::int64_t> x, std::int64_t index);

class SampleRing final {
public:
    explicit SampleRing(const CoreConfig& core = CoreConfig::baseline());

    void push(std::int64_t sample);

    [[nodiscard]] std::vector<std::int64_t> frame_oldest_to_newest() const;

    [[nodiscard]] unsigned write_pointer() const noexcept;

private:
    CoreConfig cfg_{};
    std::vector<std::int64_t> data_{};
    unsigned wr_{};
};

class OlaRing final {
public:
    explicit OlaRing(const CoreConfig& core = CoreConfig::baseline());

    [[nodiscard]] std::int64_t emit_current_and_advance();

    void add_relative(unsigned offset, std::int64_t value);

    [[nodiscard]] unsigned read_pointer() const noexcept;

    [[nodiscard]] std::span<const std::int64_t> raw() const noexcept;

private:
    [[nodiscard]] static std::int64_t checked_add_i64(std::int64_t lhs, std::int64_t rhs);

    CoreConfig cfg_{};
    std::vector<std::int64_t> data_{};
    unsigned rd_{};
};

struct TimeErrorMetrics final {
    MetricUint sum_abs_err{};
    MetricUint sum_sq_err{};
    std::uint64_t max_abs_err{};
    std::uint64_t error_sample_count{};
};

void update_time_error_metrics(TimeErrorMetrics& metrics, std::int64_t xref, std::int64_t y);

}  // namespace trecap::golden
