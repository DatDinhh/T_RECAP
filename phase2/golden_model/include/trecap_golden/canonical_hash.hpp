// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <string_view>

#include "trecap_golden/memh.hpp"

namespace trecap::golden {

[[nodiscard]] std::string bytes_to_lower_hex(std::span<const std::uint8_t> bytes);

[[nodiscard]] std::string sha256_bytes(std::string_view bytes);

[[nodiscard]] std::string sha256_file_bytes(const std::filesystem::path& path);

[[nodiscard]] std::string sha256_memh_signed(std::span<const std::int64_t> values, unsigned width);

[[nodiscard]] std::string sha256_memh_unsigned(std::span<const std::uint64_t> values, unsigned width);

[[nodiscard]] std::string sha256_memh_canonical_file(const std::filesystem::path& path, const MemhSpec& spec);

[[nodiscard]] bool is_lowercase_sha256_hex(std::string_view value);

}  // namespace trecap::golden
