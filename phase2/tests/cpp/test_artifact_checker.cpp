// SPDX-License-Identifier: MIT
#include <cstdint>
#include <exception>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

#include "trecap_golden/artifact_checker.hpp"
#include "trecap_golden/artifact_writer.hpp"
#include "trecap_golden/memh.hpp"

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
    const std::filesystem::path root = std::filesystem::temp_directory_path() / "trecap_test_artifact_checker_cpp";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);

    const std::filesystem::path coeff_dir = root / "coefficients";
    write_coefficient_artifacts(coeff_dir, window, twiddles);
    const CoefficientHashes hashes = compute_coefficient_hashes(window, twiddles);
    const ArtifactCheckResult coeff_ok = check_coefficient_artifacts(coeff_dir, hashes, cfg);
    expect(coeff_ok.ok, "fresh coefficient artifacts pass checker", failures);
    expect(coeff_ok.errors.empty(), "fresh coefficient artifacts have no checker errors", failures);
    try {
        throw_if_failed(coeff_ok);
    } catch (const contract_error& e) {
        std::cerr << "FAIL: throw_if_failed threw for ok result: " << e.what() << '\n';
        ++failures;
    }

    CoefficientHashes wrong_hashes = hashes;
    wrong_hashes.twiddle_re_sha256 = std::string(64U, '0');
    const ArtifactCheckResult coeff_bad_hash = check_coefficient_artifacts(coeff_dir, wrong_hashes, cfg);
    expect(!coeff_bad_hash.ok, "coefficient checker detects wrong hash", failures);
    expect(!coeff_bad_hash.errors.empty(), "coefficient hash mismatch reports an error", failures);
    expect_throws([&coeff_bad_hash] { throw_if_failed(coeff_bad_hash); }, "throw_if_failed reports bad coefficient artifacts", failures);

    write_text_file(coeff_dir / "twiddle_im.memh", "00000\n");
    const ArtifactCheckResult coeff_bad_rows = check_coefficient_artifacts(coeff_dir, hashes, cfg);
    expect(!coeff_bad_rows.ok, "coefficient checker detects wrong twiddle row count", failures);

    const StreamGeometry geometry = full_tail_geometry(1U, cfg);
    const std::filesystem::path vector_dir = root / "test_vectors" / "unit_vector";
    const std::filesystem::path golden_dir = root / "golden" / "unit_vector";
    std::filesystem::create_directories(vector_dir);
    std::filesystem::create_directories(golden_dir);

    write_memh(vector_dir / "x_in.memh", std::vector<std::int64_t>{0}, signed_memh_spec(cfg.N, 1U, "x_in"));
    write_memh(golden_dir / "y_out.memh", std::vector<std::int64_t>(static_cast<std::size_t>(geometry.Ny), 0),
               signed_memh_spec(cfg.N, geometry.Ny, "y_out"));

    FrameStats frame0{};
    frame0.frame_idx = 0U;
    frame0.unique_bins = cfg.unique_bins();
    frame0.eligible_unique_bins = cfg.unique_bins() - 1U;
    write_frame_stats_csv(golden_dir / "frame_stats.csv", std::vector<FrameStats>{frame0});

    std::vector<BinMaskDecision> bins;
    bins.reserve(static_cast<std::size_t>(cfg.unique_bins()));
    for (unsigned k = 0U; k < cfg.unique_bins(); ++k) {
        bins.push_back(BinMaskDecision{k, 0, 0, 0U, unique_bin_is_eligible(k, cfg), false, false});
    }
    write_bin_stats_csv(golden_dir / "bin_stats.csv", bins, cfg);

    const ArtifactCheckResult vector_ok = check_vector_artifact_rows(vector_dir, golden_dir, geometry, true, cfg);
    expect(vector_ok.ok, "vector artifacts with expected rows pass checker", failures);
    expect(vector_ok.errors.empty(), "vector artifact checker ok result has no errors", failures);

    const ArtifactCheckResult missing_bin_stats_ok = check_vector_artifact_rows(vector_dir, golden_dir, geometry, false, cfg);
    expect(missing_bin_stats_ok.ok, "bin_stats is conditional when not expected", failures);

    write_text_file(golden_dir / "frame_stats.csv", std::string{kFrameStatsCsvHeader} + "\n0,129,0,128,0,0,0\n1,129,0,128,0,0,0\n");
    const ArtifactCheckResult vector_bad_rows = check_vector_artifact_rows(vector_dir, golden_dir, geometry, true, cfg);
    expect(!vector_bad_rows.ok, "vector checker detects frame_stats row-count mismatch", failures);

    write_text_file(golden_dir / "frame_stats.csv", std::string{kFrameStatsCsvHeader} + "\r\n0,129,0,128,0,0,0\r\n");
    const ArtifactCheckResult vector_bad_crlf = check_vector_artifact_rows(vector_dir, golden_dir, geometry, false, cfg);
    expect(!vector_bad_crlf.ok, "vector checker rejects CRLF CSV", failures);

    std::filesystem::remove_all(root);
    return failures == 0 ? 0 : 1;
}
