// SPDX-License-Identifier: MIT
// Test-only observer of public reference APIs. Expected arithmetic lives outside
// this executable. Coefficients are always loaded from the supplied frozen files.
#include <charconv>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include "trecap_golden/memh.hpp"
#include "trecap_golden/stft_wola_model.hpp"
#include "trecap_golden/fixed_point.hpp"

namespace tg = trecap::golden;

template <typename T> T number(const std::string& text) {
    T result{};
    const auto parsed = std::from_chars(text.data(), text.data() + text.size(), result);
    if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size())
        throw std::runtime_error("invalid decimal integer");
    return result;
}

auto load_tables(const std::filesystem::path& dir) {
    tg::WindowTable window;
    for (const auto v : tg::read_memh(dir / "window_qw.memh", tg::unsigned_memh_spec(16, 256)))
        window.q.push_back(static_cast<std::uint64_t>(v));
    tg::TwiddleTables twiddles;
    for (bool inv : {false, true}) {
        const std::string prefix = inv ? "twiddle_inv_" : "twiddle_";
        const auto re = tg::read_memh(dir / (prefix + "re.memh"), tg::signed_memh_spec(17, 256));
        const auto im = tg::read_memh(dir / (prefix + "im.memh"), tg::signed_memh_spec(17, 256));
        auto& table = inv ? twiddles.inverse : twiddles.forward;
        for (std::size_t k = 0; k < re.size(); ++k) table.push_back({re[k], im[k]});
    }
    window.validate();
    twiddles.validate();
    return std::pair{window, twiddles};
}

void emit_frame(const tg::FrameStats& f) {
    std::cout << "F\t" << f.frame_idx << '\t' << f.unique_bins << '\t'
              << f.unique_suppressed_bins << '\t' << f.eligible_unique_bins << '\t'
              << f.eligible_suppressed_bins << '\t' << f.eligible_kept_mag2.to_decimal_string()
              << '\t' << f.eligible_total_mag2.to_decimal_string() << '\n';
}
void emit_bins(std::uint64_t frame, const std::vector<tg::BinMaskDecision>& bins) {
    for (const auto& b : bins)
        std::cout << "B\t" << frame << '\t' << b.bin_idx << '\t' << b.real << '\t'
                  << b.imag << '\t' << b.mag2 << '\t' << b.eligible << '\t'
                  << b.pre_mask << '\t' << b.mask << '\n';
}
void emit_stage(std::uint64_t frame, const std::string& name,
                const std::vector<tg::ComplexI64>& values) {
    for (std::size_t k = 0; k < values.size(); ++k)
        std::cout << "S\t" << frame << '\t' << name << '\t' << k << '\t'
                  << values[k].re << '\t' << values[k].im << '\n';
}
void emit_metric(const std::string& name, const tg::MetricUint& value) {
    std::cout << "M\t" << name << '\t' << value.to_decimal_string() << '\n';
}

int main(int argc, char** argv) {
    try {
        if (argc < 3) throw std::runtime_error("expected MODE COEFF_DIR [INPUT THR2]");
        const auto [window, twiddles] = load_tables(argv[2]);
        const auto cfg = window.cfg;
        const std::string mode = argv[1];
        if (mode == "primitives" && argc == 3) {
            std::string line;
            std::uint64_t id = 0;
            while (std::getline(std::cin, line)) {
                std::istringstream row(line);
                std::string op, value_text, shift_text, extra;
                if (!(row >> op >> value_text >> shift_text) || row >> extra)
                    throw std::runtime_error("malformed primitive record");
                const auto value = number<std::int64_t>(value_text);
                const auto parameter = number<unsigned>(shift_text);
                if (op == "round")
                    std::cout << "R\t" << id << '\t' << tg::rnd_shr(value, parameter) << '\n';
                else if (op == "sat")
                    std::cout << "R\t" << id << '\t' << tg::sat_signed(value, parameter) << '\n';
                else throw std::runtime_error("unknown primitive operation");
                ++id;
            }
            if (!std::cin.eof()) throw std::runtime_error("primitive input error");
        } else if ((mode == "fft" || mode == "ifft" || mode == "canonical" || mode == "mask") &&
                   ((mode != "mask" && argc == 3) || (mode == "mask" && argc == 4))) {
            std::vector<tg::ComplexI64> data;
            std::string line;
            while (std::getline(std::cin, line)) {
                std::istringstream row(line);
                std::string re, im, extra;
                if (!(row >> re >> im) || row >> extra) throw std::runtime_error("bad complex row");
                data.push_back({number<std::int64_t>(re), number<std::int64_t>(im)});
            }
            if (!std::cin.eof() || data.size() != cfg.L) throw std::runtime_error("complex input length");
            if (mode == "mask") {
                const auto result = tg::compute_mask_decisions(data, number<std::uint64_t>(argv[3]), 0, cfg);
                emit_bins(0, result.bins);
                emit_frame(result.frame_stats);
            } else {
                std::vector<tg::ComplexI64> result;
                if (mode == "fft") {
                    std::vector<std::int64_t> real;
                    for (const auto v : data) {
                        if (v.im != 0) throw std::runtime_error("FFT API accepts real input only");
                        real.push_back(v.re);
                    }
                    result = tg::fft_norm_radix2_int(real, twiddles);
                } else if (mode == "ifft") result = tg::ifft_unscaled_radix2_int(data, twiddles);
                else result = tg::hermitian_canonicalize(data, cfg);
                emit_stage(0, mode, result);
            }
        } else if (mode == "run" && argc == 5) {
            const auto x = tg::read_memh(argv[3], tg::signed_memh_spec(12));
            tg::StftWolaRunConfig run_cfg;
            run_cfg.thr2 = number<std::uint64_t>(argv[4]);
            run_cfg.collect_bin_stats = true;
            const auto result = tg::run_stft_wola_model(x, run_cfg, window, twiddles);
            const auto g = result.geometry;
            std::cout << "G\t" << g.Ns << '\t' << g.Nframes << '\t' << g.tau_last << '\t' << g.Ny << '\n';
            for (std::size_t n = 0; n < result.y.size(); ++n)
                std::cout << "Y\t" << n << '\t' << result.y[n] << '\n';
            for (const auto& f : result.frame_stats) emit_frame(f);
            for (std::uint64_t f = 0; f < g.Nframes; ++f) {
                std::vector<tg::BinMaskDecision> bins;
                for (unsigned k = 0; k < cfg.unique_bins(); ++k)
                    bins.push_back(result.bin_stats.at(static_cast<std::size_t>(f * cfg.unique_bins() + k)));
                emit_bins(f, bins);
                std::vector<std::int64_t> frame;
                const auto start = static_cast<std::int64_t>((f + 1) * cfg.H) - cfg.L;
                for (unsigned i = 0; i < cfg.L; ++i)
                    frame.push_back(tg::zero_extended_sample(x, start + i));
                const auto a = tg::process_frame_analysis_mask(frame, f, run_cfg.thr2, window, twiddles);
                std::vector<tg::ComplexI64> analysis;
                for (auto v : tg::analysis_window_frame(frame, window)) analysis.push_back({v, 0});
                emit_stage(f, "analysis", analysis);
                emit_stage(f, "fft", a.raw_fft);
                emit_stage(f, "canonical", a.canonical);
                emit_stage(f, "masked", a.masked);
                const auto time = tg::ifft_unscaled_radix2_int(a.masked, twiddles);
                emit_stage(f, "ifft", time);
                std::vector<tg::ComplexI64> z;
                for (auto v : tg::synthesis_window_frame(time, window)) z.push_back({v, 0});
                emit_stage(f, "z", z);
            }
            const auto& m = result.metrics;
            emit_metric("unique_bins", m.unique_bins);
            emit_metric("unique_suppressed_bins", m.unique_suppressed_bins);
            emit_metric("eligible_unique_bins", m.eligible_unique_bins);
            emit_metric("eligible_suppressed_bins", m.eligible_suppressed_bins);
            emit_metric("eligible_kept_mag2", m.eligible_kept_mag2);
            emit_metric("eligible_total_mag2", m.eligible_total_mag2);
            emit_metric("sum_abs_err", m.time_domain_errors.sum_abs_err);
            emit_metric("sum_sq_err", m.time_domain_errors.sum_sq_err);
            std::cout << "M\tmax_abs_err\t" << m.time_domain_errors.max_abs_err << '\n';
            std::cout << "M\terror_sample_count\t" << m.time_domain_errors.error_sample_count << '\n';
        } else throw std::runtime_error("unsupported adapter arguments");
        std::cout.flush();
        if (!std::cout) throw std::runtime_error("output error");
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "reference API adapter: " << e.what() << '\n';
        return 1;
    }
}