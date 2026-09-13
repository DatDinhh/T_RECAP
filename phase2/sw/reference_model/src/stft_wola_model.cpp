// SPDX-License-Identifier: MIT
#include "trecap_golden/stft_wola_model.hpp"

#include <utility>

namespace trecap::golden {
namespace {

static_assert(kBaselineWidths.W_mag2 == 56U);
static_assert(kBaselineWidths.W_ola == 37U);

}  // namespace

FrameAnalysisResult process_frame_analysis_mask(std::span<const std::int64_t> frame_oldest_to_newest,
                                                const std::uint64_t frame_idx,
                                                const std::uint64_t thr2,
                                                const WindowTable& window,
                                                const TwiddleTables& twiddles) {
    window.validate();
    twiddles.validate();
    const CoreConfig cfg = window.cfg;
    if (twiddles.cfg.L != cfg.L || twiddles.cfg.F != cfg.F || twiddles.cfg.P != cfg.P) {
        throw contract_error("window and twiddle core configs are incompatible");
    }

    const std::vector<std::int64_t> u = analysis_window_frame(frame_oldest_to_newest, window);
    FrameAnalysisResult result{};
    result.frame_idx = frame_idx;
    result.raw_fft = fft_norm_radix2_int(u, twiddles);
    result.canonical = hermitian_canonicalize(result.raw_fft, cfg);
    MaskResult mask = compute_mask_decisions(result.canonical, thr2, frame_idx, cfg);
    result.bins = std::move(mask.bins);
    result.frame_stats = mask.frame_stats;
    result.masked = apply_unique_bin_mask(result.canonical, result.bins, cfg);
    return result;
}

void process_frame_synthesis_wola(std::span<const ComplexI64> masked_spectrum,
                                  OlaRing& ola,
                                  const WindowTable& window,
                                  const TwiddleTables& twiddles) {
    window.validate();
    twiddles.validate();
    const CoreConfig cfg = window.cfg;
    if (masked_spectrum.size() != cfg.L) {
        throw contract_error("synthesis masked spectrum length must equal L");
    }

    const std::vector<ComplexI64> time = ifft_unscaled_radix2_int(masked_spectrum, twiddles);
    const std::vector<std::int64_t> z = synthesis_window_frame(time, window);
    for (unsigned i = 0U; i < cfg.L; ++i) {
        ola.add_relative(cfg.G + i, z[i]);
    }
}

void accumulate_frame_metrics(StftWolaMetrics& metrics, const FrameStats& frame) {
    metrics.unique_bins = metric_add(metrics.unique_bins, metric_from_u64(frame.unique_bins));
    metrics.unique_suppressed_bins = metric_add(metrics.unique_suppressed_bins,
                                                metric_from_u64(frame.unique_suppressed_bins));
    metrics.eligible_unique_bins = metric_add(metrics.eligible_unique_bins, metric_from_u64(frame.eligible_unique_bins));
    metrics.eligible_suppressed_bins = metric_add(metrics.eligible_suppressed_bins,
                                                  metric_from_u64(frame.eligible_suppressed_bins));
    metrics.eligible_kept_mag2 = metric_add(metrics.eligible_kept_mag2, frame.eligible_kept_mag2);
    metrics.eligible_total_mag2 = metric_add(metrics.eligible_total_mag2, frame.eligible_total_mag2);
}

StftWolaResult run_stft_wola_model(std::span<const std::int64_t> x,
                                   const StftWolaRunConfig& run_cfg,
                                   const WindowTable& window,
                                   const TwiddleTables& twiddles) {
    const CoreConfig cfg = run_cfg.core;
    cfg.validate();
    if (x.empty()) {
        throw contract_error("Revision J signoff vectors require Ns > 0");
    }
    if (window.cfg.L != cfg.L || window.cfg.F != cfg.F || window.cfg.N != cfg.N) {
        throw contract_error("window table does not match run core config");
    }
    if (twiddles.cfg.L != cfg.L || twiddles.cfg.F != cfg.F || twiddles.cfg.P != cfg.P) {
        throw contract_error("twiddle tables do not match run core config");
    }
    if (!threshold_is_legal(run_cfg.thr2, WidthConfig::from_core(cfg).W_mag2)) {
        throw contract_error("run THR2 is outside the W_mag2 domain");
    }
    for (const auto sample : x) {
        require_signed_fit(sample, cfg.N);
    }

    StftWolaResult result{};
    result.geometry = full_tail_geometry(static_cast<std::uint64_t>(x.size()), cfg);
    result.y.reserve(static_cast<std::size_t>(result.geometry.Ny));
    result.frame_stats.reserve(static_cast<std::size_t>(result.geometry.Nframes));
    if (run_cfg.collect_bin_stats) {
        result.bin_stats.reserve(static_cast<std::size_t>(result.geometry.Nframes * cfg.unique_bins()));
    }

    SampleRing xring(cfg);
    OlaRing ola(cfg);

    for (std::uint64_t n = 0U; n < result.geometry.Ny; ++n) {
        const std::int64_t xin = zero_extended_sample(x, static_cast<std::int64_t>(n));
        const std::int64_t xref = zero_extended_sample(x, static_cast<std::int64_t>(n) - static_cast<std::int64_t>(cfg.D));

        xring.push(xin);
        const std::int64_t y = ola.emit_current_and_advance();
        result.y.push_back(y);
        update_time_error_metrics(result.metrics.time_domain_errors, xref, y);

        const std::uint64_t sample_count = n + 1U;
        if ((sample_count % cfg.H) == 0U && sample_count <= result.geometry.tau_last) {
            const std::uint64_t frame_idx = static_cast<std::uint64_t>(result.frame_stats.size());
            const std::vector<std::int64_t> frame = xring.frame_oldest_to_newest();
            const FrameAnalysisResult analysis = process_frame_analysis_mask(frame,
                                                                             frame_idx,
                                                                             run_cfg.thr2,
                                                                             window,
                                                                             twiddles);
            process_frame_synthesis_wola(analysis.masked, ola, window, twiddles);
            result.frame_stats.push_back(analysis.frame_stats);
            accumulate_frame_metrics(result.metrics, analysis.frame_stats);
            if (run_cfg.collect_bin_stats) {
                result.bin_stats.insert(result.bin_stats.end(), analysis.bins.begin(), analysis.bins.end());
            }
        }
    }

    if (result.frame_stats.size() != result.geometry.Nframes) {
        throw contract_error("executed frame count does not match full-tail geometry");
    }
    return result;
}

}  // namespace trecap::golden
