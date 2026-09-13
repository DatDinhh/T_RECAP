// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "trecap_golden/signed_int.hpp"

namespace trecap::golden {

enum class MemhSignedness : std::uint8_t {
    unsigned_binary = 0,
    signed_twos_complement = 1,
};

struct MemhSpec final {
    unsigned width{};
    MemhSignedness signedness{MemhSignedness::signed_twos_complement};
    std::uint64_t expected_lines{};  // 0 means caller did not declare a fixed line count.
    std::string_view logical_name{};

    [[nodiscard]] constexpr bool is_signed() const noexcept {
        return signedness == MemhSignedness::signed_twos_complement;
    }

    constexpr void validate() const {
        require_width(width, 64U);
    }
};

[[nodiscard]] inline constexpr MemhSpec signed_memh_spec(const unsigned width,
                                                         const std::uint64_t expected_lines = 0U,
                                                         const std::string_view name = {}) {
    return MemhSpec{width, MemhSignedness::signed_twos_complement, expected_lines, name};
}

[[nodiscard]] inline constexpr MemhSpec unsigned_memh_spec(const unsigned width,
                                                           const std::uint64_t expected_lines = 0U,
                                                           const std::string_view name = {}) {
    return MemhSpec{width, MemhSignedness::unsigned_binary, expected_lines, name};
}

[[nodiscard]] char hex_digit(std::uint8_t value);

[[nodiscard]] std::string fixed_width_hex(std::uint64_t encoded, unsigned width);

[[nodiscard]] std::string encode_memh_unsigned_line(std::uint64_t value, unsigned width);

[[nodiscard]] std::string encode_memh_signed_line(std::int64_t value, unsigned width);

[[nodiscard]] std::string encode_memh_line(std::int64_t value, const MemhSpec& spec);

[[nodiscard]] std::uint64_t parse_lowercase_hex_line(std::string_view line, unsigned width);

[[nodiscard]] std::int64_t decode_memh_line(std::string_view line, const MemhSpec& spec);

[[nodiscard]] std::string canonical_memh_serialization_signed(std::span<const std::int64_t> values, unsigned width);

[[nodiscard]] std::string canonical_memh_serialization_unsigned(std::span<const std::uint64_t> values, unsigned width);

[[nodiscard]] std::string canonical_memh_serialization(std::span<const std::int64_t> values, const MemhSpec& spec);

void write_text_file(const std::filesystem::path& path, std::string_view bytes);

void write_memh(const std::filesystem::path& path, std::span<const std::int64_t> values, const MemhSpec& spec);

void write_memh_unsigned(const std::filesystem::path& path,
                         std::span<const std::uint64_t> values,
                         const MemhSpec& spec);

[[nodiscard]] std::vector<std::int64_t> read_memh(const std::filesystem::path& path, const MemhSpec& spec);

[[nodiscard]] std::uint64_t count_lf_lines(const std::filesystem::path& path);

}  // namespace trecap::golden
