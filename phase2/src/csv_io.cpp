// SPDX-License-Identifier: MIT
#include "trecap_golden/csv_io.hpp"

#include <fstream>

namespace trecap::golden {
namespace {

static_assert(kFrameStatsCsvHeader.size() > 0U);
static_assert(kBinStatsCsvHeader.size() > 0U);

}  // namespace

std::string frame_stats_row_csv(const FrameStats& row) {
    return std::to_string(row.frame_idx) + "," + std::to_string(row.unique_bins) + "," +
           std::to_string(row.unique_suppressed_bins) + "," + std::to_string(row.eligible_unique_bins) + "," +
           std::to_string(row.eligible_suppressed_bins) + "," + metric_to_decimal_string(row.eligible_kept_mag2) +
           "," + metric_to_decimal_string(row.eligible_total_mag2);
}

void write_frame_stats_csv(const std::filesystem::path& path, std::span<const FrameStats> rows) {
    std::string out;
    out += kFrameStatsCsvHeader;
    out.push_back('\n');
    for (std::size_t i = 0U; i < rows.size(); ++i) {
        if (rows[i].frame_idx != static_cast<std::uint64_t>(i)) {
            throw contract_error("frame_stats rows must be ordered by zero-based frame_idx");
        }
        out += frame_stats_row_csv(rows[i]);
        out.push_back('\n');
    }
    write_text_file(path, out);
}

std::string bin_stats_row_csv(const std::uint64_t frame_idx, const BinMaskDecision& row) {
    return std::to_string(frame_idx) + "," + std::to_string(row.bin_idx) + "," + std::to_string(row.real) + "," +
           std::to_string(row.imag) + "," + std::to_string(row.mag2) + "," + (row.eligible ? "1" : "0") + "," +
           (row.pre_mask ? "1" : "0") + "," + (row.mask ? "1" : "0");
}

void write_bin_stats_csv(const std::filesystem::path& path,
                         std::span<const BinMaskDecision> rows,
                         const CoreConfig& cfg) {
    cfg.validate();
    const std::uint64_t unique = cfg.unique_bins();
    if (unique == 0U || (static_cast<std::uint64_t>(rows.size()) % unique) != 0U) {
        throw contract_error("bin_stats row count must be Nframes*(L/2+1)");
    }
    std::string out;
    out += kBinStatsCsvHeader;
    out.push_back('\n');
    for (std::size_t i = 0U; i < rows.size(); ++i) {
        const std::uint64_t idx = static_cast<std::uint64_t>(i);
        const std::uint64_t frame_idx = idx / unique;
        const std::uint64_t expected_bin = idx % unique;
        if (rows[i].bin_idx != expected_bin) {
            throw contract_error("bin_stats rows must be ordered by frame_idx then bin_idx");
        }
        out += bin_stats_row_csv(frame_idx, rows[i]);
        out.push_back('\n');
    }
    write_text_file(path, out);
}

std::uint64_t csv_data_row_count(const std::filesystem::path& path, const std::string_view expected_header) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw contract_error("failed to open CSV file: " + path.string());
    }
    std::string line;
    if (!std::getline(in, line)) {
        throw contract_error("CSV file is empty: " + path.string());
    }
    if (!line.empty() && line.back() == '\r') {
        throw contract_error("CSV file uses CRLF; canonical form requires LF only");
    }
    if (line != expected_header) {
        throw contract_error("CSV header does not match contract");
    }
    std::uint64_t rows = 0U;
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') {
            throw contract_error("CSV file uses CRLF; canonical form requires LF only");
        }
        if (line.empty()) {
            throw contract_error("CSV file contains blank line");
        }
        ++rows;
    }
    return rows;
}

}  // namespace trecap::golden
