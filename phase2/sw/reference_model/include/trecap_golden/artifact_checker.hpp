// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "trecap_golden/artifact_writer.hpp"
#include "trecap_golden/canonical_hash.hpp"
#include "trecap_golden/csv_io.hpp"

namespace trecap::golden {

struct ArtifactCheckResult final {
    bool ok{true};
    std::vector<std::string> errors{};

    void fail(std::string message);
};

void check_memh_artifact(ArtifactCheckResult& result,
                         const std::filesystem::path& path,
                         const MemhSpec& spec,
                         std::string_view expected_sha256 = {});

void check_csv_artifact(ArtifactCheckResult& result,
                        const std::filesystem::path& path,
                        std::string_view expected_header,
                        std::uint64_t expected_data_rows);

[[nodiscard]] ArtifactCheckResult check_coefficient_artifacts(const std::filesystem::path& directory,
                                                             const CoefficientHashes& expected_hashes,
                                                             const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] ArtifactCheckResult check_vector_artifact_rows(const std::filesystem::path& test_vector_dir,
                                                             const std::filesystem::path& golden_dir,
                                                             const StreamGeometry& geometry,
                                                             bool expect_bin_stats,
                                                             const CoreConfig& cfg = CoreConfig::baseline());

void throw_if_failed(const ArtifactCheckResult& result);

}  // namespace trecap::golden
