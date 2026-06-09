// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <string_view>

#include "trecap_golden/mask.hpp"
#include "trecap_golden/memh.hpp"

namespace trecap::golden {

inline constexpr std::string_view kFrameStatsCsvHeader =
    "frame_idx,unique_bins,unique_suppressed_bins,eligible_unique_bins,eligible_suppressed_bins,eligible_kept_mag2,eligible_total_mag2";

inline constexpr std::string_view kBinStatsCsvHeader = "frame_idx,bin_idx,real,imag,mag2,eligible,pre_mask,mask";

[[nodiscard]] std::string frame_stats_row_csv(const FrameStats& row);

void write_frame_stats_csv(const std::filesystem::path& path, std::span<const FrameStats> rows);

[[nodiscard]] std::string bin_stats_row_csv(std::uint64_t frame_idx, const BinMaskDecision& row);

void write_bin_stats_csv(const std::filesystem::path& path,
                         std::span<const BinMaskDecision> rows,
                         const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::uint64_t csv_data_row_count(const std::filesystem::path& path, std::string_view expected_header);

}  // namespace trecap::golden
