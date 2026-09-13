// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "trecap_golden/fft_radix2_int.hpp"
#include "trecap_golden/finite_stream.hpp"
#include "trecap_golden/hermitian.hpp"
#include "trecap_golden/ifft_radix2_int.hpp"
#include "trecap_golden/mask.hpp"
#include "trecap_golden/window.hpp"

namespace trecap::golden {

struct FrameAnalysisResult final {
    std::uint64_t frame_idx{};
    std::vector<ComplexI64> raw_fft{};
    std::vector<ComplexI64> canonical{};
    std::vector<ComplexI64> masked{};
    std::vector<BinMaskDecision> bins{};
    FrameStats frame_stats{};
};

struct StftWolaMetrics final {
    MetricUint unique_bins{};
    MetricUint unique_suppressed_bins{};
    MetricUint eligible_unique_bins{};
    MetricUint eligible_suppressed_bins{};
    MetricUint eligible_kept_mag2{};
    MetricUint eligible_total_mag2{};
    TimeErrorMetrics time_domain_errors{};
};

struct StftWolaRunConfig final {
    CoreConfig core{CoreConfig::baseline()};
    std::uint64_t thr2{};
    bool collect_bin_stats{false};
};

struct StftWolaResult final {
    StreamGeometry geometry{};
    std::vector<std::int64_t> y{};
    std::vector<FrameStats> frame_stats{};
    std::vector<BinMaskDecision> bin_stats{};
    StftWolaMetrics metrics{};
};

[[nodiscard]] FrameAnalysisResult process_frame_analysis_mask(std::span<const std::int64_t> frame_oldest_to_newest,
                                                              std::uint64_t frame_idx,
                                                              std::uint64_t thr2,
                                                              const WindowTable& window,
                                                              const TwiddleTables& twiddles);

void process_frame_synthesis_wola(std::span<const ComplexI64> masked_spectrum,
                                  OlaRing& ola,
                                  const WindowTable& window,
                                  const TwiddleTables& twiddles);

void accumulate_frame_metrics(StftWolaMetrics& metrics, const FrameStats& frame);

[[nodiscard]] StftWolaResult run_stft_wola_model(std::span<const std::int64_t> x,
                                                 const StftWolaRunConfig& run_cfg = StftWolaRunConfig{},
                                                 const WindowTable& window = WindowTable::generated(),
                                                 const TwiddleTables& twiddles = TwiddleTables::generated());

}  // namespace trecap::golden
