// SPDX-License-Identifier: MIT
#include "trecap_golden/finite_stream.hpp"

#include <limits>

namespace trecap::golden {
namespace {

static_assert(kCoreDelayD == 384U);
static_assert(full_tail_frame_count(4096U) == 33U);
static_assert(full_tail_geometry(4096U).Ny == 4608U);

}  // namespace

std::int64_t zero_extended_sample(std::span<const std::int64_t> x, const std::int64_t index) {
    if (index < 0) {
        return 0;
    }
    const auto uindex = static_cast<std::uint64_t>(index);
    if (uindex >= x.size()) {
        return 0;
    }
    return x[static_cast<std::size_t>(uindex)];
}

SampleRing::SampleRing(const CoreConfig& core) : cfg_(core), data_(core.L, 0) {
    cfg_.validate();
}

void SampleRing::push(const std::int64_t sample) {
    require_signed_fit(sample, cfg_.N);
    data_[wr_] = sample;
    wr_ = (wr_ + 1U) % cfg_.L;
}

std::vector<std::int64_t> SampleRing::frame_oldest_to_newest() const {
    std::vector<std::int64_t> frame;
    frame.reserve(cfg_.L);
    for (unsigned i = 0U; i < cfg_.L; ++i) {
        frame.push_back(data_[(wr_ + i) % cfg_.L]);
    }
    return frame;
}

unsigned SampleRing::write_pointer() const noexcept {
    return wr_;
}

OlaRing::OlaRing(const CoreConfig& core) : cfg_(core), data_(core.D, 0) {
    cfg_.validate();
    if (cfg_.D < cfg_.L) {
        throw contract_error("OLA ring length D must cover at least one frame contribution");
    }
}

std::int64_t OlaRing::emit_current_and_advance() {
    const std::int64_t sample = sat_signed(rnd_shr(data_[rd_], cfg_.F), cfg_.N);
    data_[rd_] = 0;
    rd_ = (rd_ + 1U) % cfg_.D;
    return sample;
}

void OlaRing::add_relative(const unsigned offset, const std::int64_t value) {
    const unsigned idx = (rd_ + offset) % cfg_.D;
    const std::int64_t before = data_[idx];
    const std::int64_t after = checked_add_i64(before, value);
    data_[idx] = require_signed_fit(after, WidthConfig::from_core(cfg_).W_ola);
}

unsigned OlaRing::read_pointer() const noexcept {
    return rd_;
}

std::span<const std::int64_t> OlaRing::raw() const noexcept {
    return data_;
}

std::int64_t OlaRing::checked_add_i64(const std::int64_t lhs, const std::int64_t rhs) {
    if ((rhs > 0 && lhs > std::numeric_limits<std::int64_t>::max() - rhs) ||
        (rhs < 0 && lhs < std::numeric_limits<std::int64_t>::min() - rhs)) {
        throw contract_error("OLA accumulator overflowed int64");
    }
    return lhs + rhs;
}

void update_time_error_metrics(TimeErrorMetrics& metrics, const std::int64_t xref, const std::int64_t y) {
    const std::int64_t err = xref - y;
    const std::uint64_t abs_err = abs_u64(err);
    metrics.sum_abs_err = metric_add(metrics.sum_abs_err, metric_from_u64(abs_err));
    metrics.sum_sq_err = metric_add(metrics.sum_sq_err, metric_mul_u64(abs_err, abs_err));
    if (abs_err > metrics.max_abs_err) {
        metrics.max_abs_err = abs_err;
    }
    ++metrics.error_sample_count;
}

}  // namespace trecap::golden
