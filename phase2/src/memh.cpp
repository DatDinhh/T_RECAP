// SPDX-License-Identifier: MIT
#include "trecap_golden/memh.hpp"

#include <fstream>
#include <ios>
#include <sstream>

namespace trecap::golden {
namespace {

static_assert(signed_memh_spec(12U).is_signed());
static_assert(!unsigned_memh_spec(16U).is_signed());

}  // namespace

char hex_digit(const std::uint8_t value) {
    if (value < 10U) {
        return static_cast<char>('0' + value);
    }
    if (value < 16U) {
        return static_cast<char>('a' + (value - 10U));
    }
    throw contract_error("hex digit value outside 0..15");
}

std::string fixed_width_hex(const std::uint64_t encoded, const unsigned width) {
    const unsigned digits = fixed_hex_digits(width);
    std::string out(static_cast<std::size_t>(digits), '0');
    for (unsigned pos = 0U; pos < digits; ++pos) {
        const unsigned shift = 4U * (digits - 1U - pos);
        const auto nibble = static_cast<std::uint8_t>((encoded >> shift) & 0xFU);
        out[static_cast<std::size_t>(pos)] = hex_digit(nibble);
    }
    return out;
}

std::string encode_memh_unsigned_line(const std::uint64_t value, const unsigned width) {
    return fixed_width_hex(encode_unsigned(value, width), width);
}

std::string encode_memh_signed_line(const std::int64_t value, const unsigned width) {
    return fixed_width_hex(encode_signed_twos_complement(value, width), width);
}

std::string encode_memh_line(const std::int64_t value, const MemhSpec& spec) {
    spec.validate();
    if (spec.is_signed()) {
        return encode_memh_signed_line(value, spec.width);
    }
    if (value < 0) {
        throw contract_error("negative value supplied for unsigned memh file");
    }
    return encode_memh_unsigned_line(static_cast<std::uint64_t>(value), spec.width);
}

std::uint64_t parse_lowercase_hex_line(const std::string_view line, const unsigned width) {
    require_width(width, 64U);
    const std::size_t expected_digits = static_cast<std::size_t>(fixed_hex_digits(width));
    if (line.size() != expected_digits) {
        throw contract_error("memh line has incorrect fixed-width hex digit count");
    }
    std::uint64_t value = 0U;
    for (const char ch : line) {
        std::uint8_t nibble{};
        if (ch >= '0' && ch <= '9') {
            nibble = static_cast<std::uint8_t>(ch - '0');
        } else if (ch >= 'a' && ch <= 'f') {
            nibble = static_cast<std::uint8_t>(10 + (ch - 'a'));
        } else {
            throw contract_error("memh line contains non-lowercase-hex character");
        }
        value = (value << 4U) | static_cast<std::uint64_t>(nibble);
    }
    const std::uint64_t masked = value & bit_mask(width);
    if (masked != value) {
        throw contract_error("memh encoded value exceeds declared width");
    }
    return masked;
}

std::int64_t decode_memh_line(const std::string_view line, const MemhSpec& spec) {
    spec.validate();
    const std::uint64_t encoded = parse_lowercase_hex_line(line, spec.width);
    if (spec.is_signed()) {
        return sign_extend_twos_complement(encoded, spec.width);
    }
    return static_cast<std::int64_t>(require_unsigned_fit(encoded, spec.width));
}

std::string canonical_memh_serialization_signed(std::span<const std::int64_t> values, const unsigned width) {
    std::string out;
    const std::size_t digits = static_cast<std::size_t>(fixed_hex_digits(width));
    out.reserve(values.size() * (digits + 1U));
    for (const std::int64_t value : values) {
        out += encode_memh_signed_line(value, width);
        out.push_back('\n');
    }
    return out;
}

std::string canonical_memh_serialization_unsigned(std::span<const std::uint64_t> values, const unsigned width) {
    std::string out;
    const std::size_t digits = static_cast<std::size_t>(fixed_hex_digits(width));
    out.reserve(values.size() * (digits + 1U));
    for (const std::uint64_t value : values) {
        out += encode_memh_unsigned_line(value, width);
        out.push_back('\n');
    }
    return out;
}

std::string canonical_memh_serialization(std::span<const std::int64_t> values, const MemhSpec& spec) {
    spec.validate();
    std::string out;
    const std::size_t digits = static_cast<std::size_t>(fixed_hex_digits(spec.width));
    out.reserve(values.size() * (digits + 1U));
    for (const std::int64_t value : values) {
        out += encode_memh_line(value, spec);
        out.push_back('\n');
    }
    return out;
}

void write_text_file(const std::filesystem::path& path, const std::string_view bytes) {
    if (path.has_parent_path()) {
        std::filesystem::create_directories(path.parent_path());
    }
    std::ofstream out(path, std::ios::binary);
    if (!out) {
        throw contract_error("failed to open output file: " + path.string());
    }
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!out) {
        throw contract_error("failed while writing output file: " + path.string());
    }
}

void write_memh(const std::filesystem::path& path, std::span<const std::int64_t> values, const MemhSpec& spec) {
    if (spec.expected_lines != 0U && static_cast<std::uint64_t>(values.size()) != spec.expected_lines) {
        throw contract_error("memh value count does not match expected line count");
    }
    write_text_file(path, canonical_memh_serialization(values, spec));
}

void write_memh_unsigned(const std::filesystem::path& path,
                         std::span<const std::uint64_t> values,
                         const MemhSpec& spec) {
    if (spec.is_signed()) {
        throw contract_error("write_memh_unsigned requires an unsigned memh spec");
    }
    if (spec.expected_lines != 0U && static_cast<std::uint64_t>(values.size()) != spec.expected_lines) {
        throw contract_error("unsigned memh value count does not match expected line count");
    }
    write_text_file(path, canonical_memh_serialization_unsigned(values, spec.width));
}

std::vector<std::int64_t> read_memh(const std::filesystem::path& path, const MemhSpec& spec) {
    spec.validate();
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw contract_error("failed to open memh file: " + path.string());
    }
    std::vector<std::int64_t> values;
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') {
            throw contract_error("memh file uses CRLF; canonical form requires LF only");
        }
        if (line.empty()) {
            throw contract_error("memh file contains a blank line");
        }
        values.push_back(decode_memh_line(line, spec));
    }
    if (spec.expected_lines != 0U && static_cast<std::uint64_t>(values.size()) != spec.expected_lines) {
        throw contract_error("memh line count does not match expected value");
    }
    return values;
}

std::uint64_t count_lf_lines(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw contract_error("failed to open file for line count: " + path.string());
    }
    std::uint64_t count = 0U;
    char ch{};
    while (in.get(ch)) {
        if (ch == '\n') {
            ++count;
        }
    }
    return count;
}

}  // namespace trecap::golden
