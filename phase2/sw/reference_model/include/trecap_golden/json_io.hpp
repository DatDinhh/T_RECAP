// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <string_view>

#include "trecap_golden/metrics.hpp"
#include "trecap_golden/version.hpp"

namespace trecap::golden {

[[nodiscard]] std::string json_escape(std::string_view text);

[[nodiscard]] std::string json_quote(std::string_view text);

[[nodiscard]] std::string json_bool(bool value);

[[nodiscard]] std::string indent(unsigned level);

[[nodiscard]] std::string core_configuration_json(const CoreConfig& cfg,
                                                  const StreamGeometry* geometry,
                                                  std::string_view thr2);

[[nodiscard]] std::string widths_json(const WidthConfig& widths);

[[nodiscard]] std::string contract_json(bool include_memh_hash = true);

[[nodiscard]] std::string coefficient_hashes_json(std::string_view window_qw_sha256,
                                                  std::string_view twiddle_re_sha256,
                                                  std::string_view twiddle_im_sha256,
                                                  std::string_view twiddle_inv_re_sha256,
                                                  std::string_view twiddle_inv_im_sha256);

[[nodiscard]] std::string stream_hashes_json(std::string_view x_in_sha256, std::string_view y_out_sha256);

void write_json_file(const std::filesystem::path& path, std::string_view json_text);

}  // namespace trecap::golden
