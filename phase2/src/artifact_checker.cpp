// SPDX-License-Identifier: MIT
#include "trecap_golden/artifact_checker.hpp"

#include <exception>
#include <utility>

namespace trecap::golden {
namespace {

static_assert(CoreConfig::baseline().L == 256U);

}  // namespace

void ArtifactCheckResult::fail(std::string message) {
    ok = false;
    errors.push_back(std::move(message));
}

void check_memh_artifact(ArtifactCheckResult& result,
                         const std::filesystem::path& path,
                         const MemhSpec& spec,
                         const std::string_view expected_sha256) {
    try {
        const std::vector<std::int64_t> values = read_memh(path, spec);
        if (!expected_sha256.empty()) {
            const std::string actual = sha256_bytes(canonical_memh_serialization(values, spec));
            if (actual != expected_sha256) {
                result.fail("sha256 mismatch for " + path.string());
            }
        }
    } catch (const std::exception& e) {
        result.fail(path.string() + ": " + e.what());
    }
}

void check_csv_artifact(ArtifactCheckResult& result,
                        const std::filesystem::path& path,
                        const std::string_view expected_header,
                        const std::uint64_t expected_data_rows) {
    try {
        const std::uint64_t rows = csv_data_row_count(path, expected_header);
        if (rows != expected_data_rows) {
            result.fail("CSV row-count mismatch for " + path.string());
        }
    } catch (const std::exception& e) {
        result.fail(path.string() + ": " + e.what());
    }
}

ArtifactCheckResult check_coefficient_artifacts(const std::filesystem::path& directory,
                                                const CoefficientHashes& expected_hashes,
                                                const CoreConfig& cfg) {
    const WidthConfig widths = WidthConfig::from_core(cfg);
    ArtifactCheckResult result{};
    check_memh_artifact(result, directory / "window_qw.memh", unsigned_memh_spec(widths.W_Qw, cfg.L, "window_qw"),
                        expected_hashes.window_qw_sha256);
    check_memh_artifact(result, directory / "twiddle_re.memh", signed_memh_spec(widths.W_tw, cfg.L, "twiddle_re"),
                        expected_hashes.twiddle_re_sha256);
    check_memh_artifact(result, directory / "twiddle_im.memh", signed_memh_spec(widths.W_tw, cfg.L, "twiddle_im"),
                        expected_hashes.twiddle_im_sha256);
    check_memh_artifact(result, directory / "twiddle_inv_re.memh",
                        signed_memh_spec(widths.W_tw, cfg.L, "twiddle_inv_re"), expected_hashes.twiddle_inv_re_sha256);
    check_memh_artifact(result, directory / "twiddle_inv_im.memh",
                        signed_memh_spec(widths.W_tw, cfg.L, "twiddle_inv_im"), expected_hashes.twiddle_inv_im_sha256);
    return result;
}

ArtifactCheckResult check_vector_artifact_rows(const std::filesystem::path& test_vector_dir,
                                               const std::filesystem::path& golden_dir,
                                               const StreamGeometry& geometry,
                                               const bool expect_bin_stats,
                                               const CoreConfig& cfg) {
    ArtifactCheckResult result{};
    check_memh_artifact(result, test_vector_dir / "x_in.memh", signed_memh_spec(cfg.N, geometry.Ns, "x_in"));
    check_memh_artifact(result, golden_dir / "y_out.memh", signed_memh_spec(cfg.N, geometry.Ny, "y_out"));
    check_csv_artifact(result, golden_dir / "frame_stats.csv", kFrameStatsCsvHeader, geometry.Nframes);
    if (expect_bin_stats) {
        check_csv_artifact(result, golden_dir / "bin_stats.csv", kBinStatsCsvHeader, geometry.Nframes * cfg.unique_bins());
    }
    return result;
}

void throw_if_failed(const ArtifactCheckResult& result) {
    if (result.ok) {
        return;
    }
    std::string message = "artifact check failed";
    for (const std::string& error : result.errors) {
        message += "\n  - " + error;
    }
    throw contract_error(message);
}

}  // namespace trecap::golden
