// SPDX-License-Identifier: MIT
#include <cstdint>
#include <exception>
#include <iostream>
#include <string>
#include <vector>

#include "trecap_golden/stft_wola_model.hpp"

namespace {

void expect(const bool condition, const std::string& message, int& failures) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

template <typename Fn>
void expect_throws(Fn&& fn, const std::string& message, int& failures) {
    try {
        fn();
    } catch (const trecap::golden::contract_error&) {
        return;
    }
    std::cerr << "FAIL: expected throw: " << message << '\n';
    ++failures;
}

}  // namespace

int main() {
    using namespace trecap::golden;

    int failures = 0;
    const CoreConfig cfg = CoreConfig::baseline();
    const WindowTable window = WindowTable::generated(cfg);
    const TwiddleTables twiddles = TwiddleTables::generated(cfg);

    SampleRing ring(cfg);
    for (unsigned i = 0U; i < cfg.L; ++i) {
        ring.push(static_cast<std::int64_t>(i % 17U) - 8);
    }
    const std::vector<std::int64_t> frame = ring.frame_oldest_to_newest();
    expect(frame.size() == static_cast<std::size_t>(cfg.L), "sample ring emits exactly L samples", failures);
    expect(frame[0] == -8, "sample ring first sample after one full frame", failures);
    expect(frame[16] == 8, "sample ring preserves oldest-to-newest order", failures);

    OlaRing ola(cfg);
    ola.add_relative(0U, 32768);
    ola.add_relative(1U, -32768);
    expect(ola.emit_current_and_advance() == 1, "OLA emits rounded positive QF value", failures);
    expect(ola.emit_current_and_advance() == -1, "OLA emits rounded negative QF value", failures);
    expect(ola.emit_current_and_advance() == 0, "OLA clears slot after emission", failures);

    std::vector<ComplexI64> dc_spectrum(cfg.L, ComplexI64{0, 0});
    dc_spectrum[0] = ComplexI64{32768, 0};
    OlaRing dc_ola(cfg);
    process_frame_synthesis_wola(dc_spectrum, dc_ola, window, twiddles);
    const std::span<const std::int64_t> raw = dc_ola.raw();
    expect(raw[cfg.G] == 0, "periodic sqrt-Hann window starts at zero", failures);
    expect(raw[cfg.G + cfg.H] == 32768, "DC synthesis contribution reaches unity at midpoint", failures);

    const std::vector<std::int64_t> zero_input(1U, 0);
    const StftWolaRunConfig zero_cfg{cfg, 0U, true};
    const StftWolaResult zero_result = run_stft_wola_model(zero_input, zero_cfg, window, twiddles);
    expect(zero_result.geometry.Ns == 1U, "single-sample Ns", failures);
    expect(zero_result.geometry.Nframes == 1U, "single-sample full-tail frame count", failures);
    expect(zero_result.geometry.Ny == 512U, "single-sample full-tail Ny", failures);
    expect(zero_result.frame_stats.size() == 1U, "single-sample frame_stats rows", failures);
    expect(zero_result.bin_stats.size() == static_cast<std::size_t>(cfg.unique_bins()), "single-sample bin_stats rows", failures);
    for (const std::int64_t y : zero_result.y) {
        expect(y == 0, "zero one-sample input emits only zeros", failures);
    }
    expect(metric_to_decimal_string(zero_result.metrics.time_domain_errors.sum_abs_err) == "0", "zero input sum_abs_err", failures);
    expect(metric_to_decimal_string(zero_result.metrics.time_domain_errors.sum_sq_err) == "0", "zero input sum_sq_err", failures);
    expect(zero_result.metrics.time_domain_errors.error_sample_count == zero_result.geometry.Ny, "zero input error count", failures);
    expect(zero_result.frame_stats[0].unique_suppressed_bins == 0U, "THR2=0 frame has no suppressed bins", failures);

    const std::vector<std::int64_t> impulse_input(1U, 1024);
    const StftWolaResult impulse_result = run_stft_wola_model(impulse_input, zero_cfg, window, twiddles);
    bool saw_nonzero = false;
    for (const std::int64_t y : impulse_result.y) {
        saw_nonzero = saw_nonzero || (y != 0);
    }
    expect(saw_nonzero, "single impulse produces a nonzero delayed reconstruction", failures);
    for (std::size_t n = 0U; n < static_cast<std::size_t>(cfg.D); ++n) {
        expect(impulse_result.y[n] == 0, "impulse reconstruction is delayed by D", failures);
    }

    expect_throws([&zero_cfg, &window, &twiddles] {
        static_cast<void>(run_stft_wola_model(std::vector<std::int64_t>{}, zero_cfg, window, twiddles));
    }, "empty finite stream is not a Revision J signoff vector", failures);

    return failures == 0 ? 0 : 1;
}
