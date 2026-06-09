// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "trecap_golden/canonical_hash.hpp"
#include "trecap_golden/csv_io.hpp"
#include "trecap_golden/json_io.hpp"
#include "trecap_golden/stft_wola_model.hpp"
#include "trecap_golden/twiddles.hpp"
#include "trecap_golden/window.hpp"

namespace trecap::golden {

struct CoefficientHashes final {
    std::string window_qw_sha256{};
    std::string twiddle_re_sha256{};
    std::string twiddle_im_sha256{};
    std::string twiddle_inv_re_sha256{};
    std::string twiddle_inv_im_sha256{};
};

[[nodiscard]] std::vector<std::uint64_t> window_to_u64(const WindowTable& window);

[[nodiscard]] std::vector<std::int64_t> twiddle_component(const std::vector<ComplexI64>& table, bool imag);

[[nodiscard]] CoefficientHashes compute_coefficient_hashes(const WindowTable& window, const TwiddleTables& twiddles);

void write_coefficient_memh_files(const std::filesystem::path& directory,
                                  const WindowTable& window,
                                  const TwiddleTables& twiddles);

[[nodiscard]] std::string coeff_manifest_json(const WindowTable& window,
                                              const TwiddleTables& twiddles,
                                              std::string_view generator_version = kGeneratorVersion);

void write_coefficient_artifacts(const std::filesystem::path& directory,
                                 const WindowTable& window = WindowTable::generated(),
                                 const TwiddleTables& twiddles = TwiddleTables::generated());

struct VectorArtifactHashes final {
    std::string x_in_sha256{};
    std::string y_out_sha256{};
};

[[nodiscard]] VectorArtifactHashes compute_stream_hashes(std::span<const std::int64_t> x,
                                                         std::span<const std::int64_t> y,
                                                         const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::string metrics_json(std::string_view vector_name,
                                       const CoreConfig& cfg,
                                       const StreamGeometry& geometry,
                                       std::uint64_t thr2,
                                       const StftWolaMetrics& metrics,
                                       const CoefficientHashes& coeff_hashes,
                                       const VectorArtifactHashes& stream_hashes);

[[nodiscard]] std::string vector_config_json(std::string_view vector_name,
                                             const CoreConfig& cfg,
                                             const StreamGeometry& geometry,
                                             std::uint64_t thr2,
                                             const CoefficientHashes& coeff_hashes,
                                             const VectorArtifactHashes& stream_hashes,
                                             bool has_bin_stats);

void write_vector_artifacts(const std::filesystem::path& test_vector_dir,
                            const std::filesystem::path& golden_dir,
                            std::string_view vector_name,
                            std::span<const std::int64_t> x,
                            const StftWolaRunConfig& run_cfg,
                            const StftWolaResult& result,
                            const CoefficientHashes& coeff_hashes);

}  // namespace trecap::golden
