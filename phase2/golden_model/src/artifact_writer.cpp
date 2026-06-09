// SPDX-License-Identifier: MIT
#include "trecap_golden/artifact_writer.hpp"

#include <sstream>

namespace trecap::golden {
namespace {

static_assert(CoreConfig::baseline().L == 256U);
static_assert(CoreConfig::baseline().D == 384U);

}  // namespace

std::vector<std::uint64_t> window_to_u64(const WindowTable& window) {
    std::vector<std::uint64_t> out;
    out.reserve(window.q.size());
    for (const std::uint64_t value : window.q) {
        out.push_back(value);
    }
    return out;
}

std::vector<std::int64_t> twiddle_component(const std::vector<ComplexI64>& table, const bool imag) {
    std::vector<std::int64_t> out;
    out.reserve(table.size());
    for (const ComplexI64 value : table) {
        out.push_back(imag ? value.im : value.re);
    }
    return out;
}

CoefficientHashes compute_coefficient_hashes(const WindowTable& window, const TwiddleTables& twiddles) {
    window.validate();
    twiddles.validate();
    const WidthConfig widths = WidthConfig::from_core(window.cfg);
    const std::vector<std::uint64_t> window_values = window_to_u64(window);
    const std::vector<std::int64_t> tw_re = twiddle_component(twiddles.forward, false);
    const std::vector<std::int64_t> tw_im = twiddle_component(twiddles.forward, true);
    const std::vector<std::int64_t> tw_inv_re = twiddle_component(twiddles.inverse, false);
    const std::vector<std::int64_t> tw_inv_im = twiddle_component(twiddles.inverse, true);
    return CoefficientHashes{sha256_memh_unsigned(window_values, widths.W_Qw),
                             sha256_memh_signed(tw_re, widths.W_tw),
                             sha256_memh_signed(tw_im, widths.W_tw),
                             sha256_memh_signed(tw_inv_re, widths.W_tw),
                             sha256_memh_signed(tw_inv_im, widths.W_tw)};
}

void write_coefficient_memh_files(const std::filesystem::path& directory,
                                  const WindowTable& window,
                                  const TwiddleTables& twiddles) {
    window.validate();
    twiddles.validate();
    if (window.cfg.L != twiddles.cfg.L || window.cfg.F != twiddles.cfg.F) {
        throw contract_error("window and twiddle tables do not share a compatible core config");
    }
    const WidthConfig widths = WidthConfig::from_core(window.cfg);
    const std::vector<std::uint64_t> window_values = window_to_u64(window);
    const std::vector<std::int64_t> tw_re = twiddle_component(twiddles.forward, false);
    const std::vector<std::int64_t> tw_im = twiddle_component(twiddles.forward, true);
    const std::vector<std::int64_t> tw_inv_re = twiddle_component(twiddles.inverse, false);
    const std::vector<std::int64_t> tw_inv_im = twiddle_component(twiddles.inverse, true);

    std::filesystem::create_directories(directory);
    write_memh_unsigned(directory / "window_qw.memh", window_values,
                        unsigned_memh_spec(widths.W_Qw, window.cfg.L, "window_qw"));
    write_memh(directory / "twiddle_re.memh", tw_re, signed_memh_spec(widths.W_tw, window.cfg.L, "twiddle_re"));
    write_memh(directory / "twiddle_im.memh", tw_im, signed_memh_spec(widths.W_tw, window.cfg.L, "twiddle_im"));
    write_memh(directory / "twiddle_inv_re.memh", tw_inv_re,
               signed_memh_spec(widths.W_tw, window.cfg.L, "twiddle_inv_re"));
    write_memh(directory / "twiddle_inv_im.memh", tw_inv_im,
               signed_memh_spec(widths.W_tw, window.cfg.L, "twiddle_inv_im"));
}

std::string coeff_manifest_json(const WindowTable& window,
                                const TwiddleTables& twiddles,
                                const std::string_view generator_version) {
    const CoreConfig cfg = window.cfg;
    const WidthConfig widths = WidthConfig::from_core(cfg);
    const CoefficientHashes hashes = compute_coefficient_hashes(window, twiddles);
    const auto coeff_block = [&cfg](const std::string_view key,
                                                     const std::string_view file,
                                                     const unsigned width_bits,
                                                     const bool is_signed,
                                                     const std::string_view q_format,
                                                     const std::string_view hash) {
        std::ostringstream os;
        os << "    \"" << key << "\": {\n";
        os << "      \"file\": " << json_quote(file) << ",\n";
        os << "      \"rows\": " << cfg.L << ",\n";
        os << "      \"width_bits\": " << width_bits << ",\n";
        os << "      \"signed\": " << json_bool(is_signed) << ",\n";
        os << "      \"q_format\": " << json_quote(q_format) << ",\n";
        os << "      \"sha256\": " << json_quote(hash) << ",\n";
        os << "      \"canonical_sha256\": " << json_quote(hash) << "\n";
        os << "    }";
        return os.str();
    };

    std::ostringstream os;
    os << "{\n";
    os << "  \"schema\": " << json_quote(kCoeffManifestSchema) << ",\n";
    os << "  \"spec_revision\": " << json_quote(kSpecRevision) << ",\n";
    os << "  \"generator_version\": " << json_quote(generator_version) << ",\n";
    os << "  \"configuration\": " << core_configuration_json(cfg, nullptr, "0") << ",\n";
    os << "  \"contract\": {\n";
    os << "    \"qcoef_rule\": " << json_quote(kQcoefRule) << ",\n";
    os << "    \"memh_encoding\": " << json_quote(kMemhEncoding) << ",\n";
    os << "    \"hash_rule\": " << json_quote(kHashRule) << "\n";
    os << "  },\n";
    os << "  \"widths\": " << widths_json(widths) << ",\n";
    os << "  \"coefficients\": {\n";
    os << coeff_block("window_qw", "window_qw.memh", widths.W_Qw, false, "Q0.15_unsigned_endpoint_one",
                      hashes.window_qw_sha256)
       << ",\n";
    os << coeff_block("twiddle_re", "twiddle_re.memh", widths.W_tw, true, "Q1.15_signed_endpoint_one",
                      hashes.twiddle_re_sha256)
       << ",\n";
    os << coeff_block("twiddle_im", "twiddle_im.memh", widths.W_tw, true, "Q1.15_signed_endpoint_one",
                      hashes.twiddle_im_sha256)
       << ",\n";
    os << coeff_block("twiddle_inv_re", "twiddle_inv_re.memh", widths.W_tw, true, "Q1.15_signed_endpoint_one",
                      hashes.twiddle_inv_re_sha256)
       << ",\n";
    os << coeff_block("twiddle_inv_im", "twiddle_inv_im.memh", widths.W_tw, true, "Q1.15_signed_endpoint_one",
                      hashes.twiddle_inv_im_sha256)
       << "\n";
    os << "  },\n";
    os << "  \"hashes\": " << coefficient_hashes_json(hashes.window_qw_sha256, hashes.twiddle_re_sha256,
                                                       hashes.twiddle_im_sha256, hashes.twiddle_inv_re_sha256,
                                                       hashes.twiddle_inv_im_sha256)
       << ",\n";
    os << "  \"artifact_rows\": {\n";
    os << "    \"window_qw\": " << cfg.L << ",\n";
    os << "    \"twiddle_re\": " << cfg.L << ",\n";
    os << "    \"twiddle_im\": " << cfg.L << ",\n";
    os << "    \"twiddle_inv_re\": " << cfg.L << ",\n";
    os << "    \"twiddle_inv_im\": " << cfg.L << "\n";
    os << "  }\n";
    os << "}";
    return os.str();
}

void write_coefficient_artifacts(const std::filesystem::path& directory,
                                 const WindowTable& window,
                                 const TwiddleTables& twiddles) {
    write_coefficient_memh_files(directory, window, twiddles);
    write_json_file(directory / "coeff_manifest.json", coeff_manifest_json(window, twiddles));
}

VectorArtifactHashes compute_stream_hashes(std::span<const std::int64_t> x,
                                           std::span<const std::int64_t> y,
                                           const CoreConfig& cfg) {
    cfg.validate();
    return VectorArtifactHashes{sha256_memh_signed(x, cfg.N), sha256_memh_signed(y, cfg.N)};
}

std::string metrics_json(const std::string_view vector_name,
                         const CoreConfig& cfg,
                         const StreamGeometry& geometry,
                         const std::uint64_t thr2,
                         const StftWolaMetrics& metrics,
                         const CoefficientHashes& coeff_hashes,
                         const VectorArtifactHashes& stream_hashes) {
    const WidthConfig widths = WidthConfig::from_core(cfg);
    const MetricsStrings strings = metrics_to_strings(metrics);
    std::ostringstream os;
    os << "{\n";
    os << "  \"schema\": " << json_quote(kMetricsSchema) << ",\n";
    os << "  \"vector_name\": " << json_quote(vector_name) << ",\n";
    os << "  \"configuration\": " << core_configuration_json(cfg, &geometry, std::to_string(thr2)) << ",\n";
    os << "  \"contract\": " << contract_json(true) << ",\n";
    os << "  \"widths\": " << widths_json(widths) << ",\n";
    os << "  \"hashes\": " << coefficient_hashes_json(coeff_hashes.window_qw_sha256, coeff_hashes.twiddle_re_sha256,
                                                       coeff_hashes.twiddle_im_sha256, coeff_hashes.twiddle_inv_re_sha256,
                                                       coeff_hashes.twiddle_inv_im_sha256)
       << ",\n";
    os << "  \"stream_hashes\": " << stream_hashes_json(stream_hashes.x_in_sha256, stream_hashes.y_out_sha256)
       << ",\n";
    os << "  \"suppression_totals\": {\n";
    os << "    \"unique_bins\": " << json_quote(strings.suppression.unique_bins) << ",\n";
    os << "    \"unique_suppressed_bins\": " << json_quote(strings.suppression.unique_suppressed_bins) << ",\n";
    os << "    \"eligible_unique_bins\": " << json_quote(strings.suppression.eligible_unique_bins) << ",\n";
    os << "    \"eligible_suppressed_bins\": " << json_quote(strings.suppression.eligible_suppressed_bins) << "\n";
    os << "  },\n";
    os << "  \"spectral_totals\": {\n";
    os << "    \"eligible_kept_mag2\": " << json_quote(strings.spectral.eligible_kept_mag2) << ",\n";
    os << "    \"eligible_total_mag2\": " << json_quote(strings.spectral.eligible_total_mag2) << "\n";
    os << "  },\n";
    os << "  \"time_domain_errors\": {\n";
    os << "    \"sum_abs_err\": " << json_quote(strings.time.sum_abs_err) << ",\n";
    os << "    \"sum_sq_err\": " << json_quote(strings.time.sum_sq_err) << ",\n";
    os << "    \"max_abs_err\": " << json_quote(strings.time.max_abs_err) << ",\n";
    os << "    \"error_sample_count\": " << json_quote(strings.time.error_sample_count) << "\n";
    os << "  }\n";
    os << "}";
    return os.str();
}

std::string vector_config_json(const std::string_view vector_name,
                               const CoreConfig& cfg,
                               const StreamGeometry& geometry,
                               const std::uint64_t thr2,
                               const CoefficientHashes& coeff_hashes,
                               const VectorArtifactHashes& stream_hashes,
                               const bool has_bin_stats) {
    const WidthConfig widths = WidthConfig::from_core(cfg);
    std::ostringstream os;
    os << "{\n";
    os << "  \"schema\": " << json_quote(kVectorConfigSchema) << ",\n";
    os << "  \"vector_name\": " << json_quote(vector_name) << ",\n";
    os << "  \"configuration\": " << core_configuration_json(cfg, &geometry, std::to_string(thr2)) << ",\n";
    os << "  \"contract\": " << contract_json(true) << ",\n";
    os << "  \"widths\": " << widths_json(widths) << ",\n";
    os << "  \"hashes\": " << coefficient_hashes_json(coeff_hashes.window_qw_sha256, coeff_hashes.twiddle_re_sha256,
                                                       coeff_hashes.twiddle_im_sha256, coeff_hashes.twiddle_inv_re_sha256,
                                                       coeff_hashes.twiddle_inv_im_sha256)
       << ",\n";
    os << "  \"stream_hashes\": " << stream_hashes_json(stream_hashes.x_in_sha256, stream_hashes.y_out_sha256)
       << ",\n";
    os << "  \"artifact_rows\": {\n";
    os << "    \"window_qw\": " << cfg.L << ",\n";
    os << "    \"twiddle_re\": " << cfg.L << ",\n";
    os << "    \"twiddle_im\": " << cfg.L << ",\n";
    os << "    \"twiddle_inv_re\": " << cfg.L << ",\n";
    os << "    \"twiddle_inv_im\": " << cfg.L << ",\n";
    os << "    \"x_in\": " << geometry.Ns << ",\n";
    os << "    \"y_out\": " << geometry.Ny << ",\n";
    os << "    \"frame_stats_data_rows\": " << geometry.Nframes;
    if (has_bin_stats) {
        os << ",\n    \"bin_stats_data_rows\": " << geometry.Nframes * cfg.unique_bins() << "\n";
    } else {
        os << "\n";
    }
    os << "  }\n";
    os << "}";
    return os.str();
}

void write_vector_artifacts(const std::filesystem::path& test_vector_dir,
                            const std::filesystem::path& golden_dir,
                            const std::string_view vector_name,
                            std::span<const std::int64_t> x,
                            const StftWolaRunConfig& run_cfg,
                            const StftWolaResult& result,
                            const CoefficientHashes& coeff_hashes) {
    const CoreConfig cfg = run_cfg.core;
    if (result.y.size() != static_cast<std::size_t>(result.geometry.Ny)) {
        throw contract_error("golden result y length does not match geometry.Ny");
    }
    if (x.size() != static_cast<std::size_t>(result.geometry.Ns)) {
        throw contract_error("input stream length does not match geometry.Ns");
    }
    std::filesystem::create_directories(test_vector_dir);
    std::filesystem::create_directories(golden_dir);

    write_memh(test_vector_dir / "x_in.memh", x, signed_memh_spec(cfg.N, result.geometry.Ns, "x_in"));
    write_memh(golden_dir / "y_out.memh", result.y, signed_memh_spec(cfg.N, result.geometry.Ny, "y_out"));
    write_frame_stats_csv(golden_dir / "frame_stats.csv", result.frame_stats);
    if (!result.bin_stats.empty()) {
        write_bin_stats_csv(golden_dir / "bin_stats.csv", result.bin_stats, cfg);
    }

    const VectorArtifactHashes stream_hashes = compute_stream_hashes(x, result.y, cfg);
    write_json_file(test_vector_dir / "config.json",
                    vector_config_json(vector_name, cfg, result.geometry, run_cfg.thr2, coeff_hashes, stream_hashes,
                                       !result.bin_stats.empty()));
    write_json_file(golden_dir / "metrics.json",
                    metrics_json(vector_name, cfg, result.geometry, run_cfg.thr2, result.metrics, coeff_hashes,
                                 stream_hashes));
}

}  // namespace trecap::golden
