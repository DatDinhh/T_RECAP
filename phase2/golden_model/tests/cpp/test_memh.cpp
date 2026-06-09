// SPDX-License-Identifier: MIT
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

#include "trecap_golden/memh.hpp"
#include "trecap_golden/signed_int.hpp"

namespace {

void expect(bool condition, const std::string& message, int& failures) {
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

    const MemhSpec sample_spec = signed_memh_spec(12U, 4U, "x_in.memh");
    const MemhSpec window_spec = unsigned_memh_spec(16U, 3U, "window_qw.memh");
    const MemhSpec twiddle_spec = signed_memh_spec(17U, 3U, "twiddle_re.memh");

    expect(hex_digit(0U) == '0', "hex digit 0", failures);
    expect(hex_digit(10U) == 'a', "hex digit a", failures);
    expect(hex_digit(15U) == 'f', "hex digit f", failures);
    expect(fixed_width_hex(0x7ffU, 12U) == "7ff", "fixed width 12-bit max", failures);
    expect(encode_memh_signed_line(-2048, 12U) == "800", "encode signed min sample", failures);
    expect(encode_memh_signed_line(-1, 12U) == "fff", "encode signed -1 sample", failures);
    expect(encode_memh_unsigned_line(32768U, 16U) == "8000", "encode unsigned window +1.0", failures);
    expect(encode_memh_signed_line(32768, 17U) == "08000", "encode signed 17-bit +32768", failures);
    expect(encode_memh_signed_line(-32768, 17U) == "18000", "encode signed 17-bit -32768", failures);
    expect(encode_memh_signed_line(-1, 17U) == "1ffff", "encode signed 17-bit -1", failures);

    expect(decode_memh_line("800", signed_memh_spec(12U)) == -2048, "decode signed min sample", failures);
    expect(decode_memh_line("fff", signed_memh_spec(12U)) == -1, "decode signed -1 sample", failures);
    expect(decode_memh_line("8000", unsigned_memh_spec(16U)) == 32768, "decode unsigned window", failures);
    expect(decode_memh_line("08000", signed_memh_spec(17U)) == 32768, "decode signed 17-bit positive", failures);
    expect(decode_memh_line("18000", signed_memh_spec(17U)) == -32768, "decode signed 17-bit negative", failures);

    expect(canonical_memh_serialization_signed(std::vector<std::int64_t>{-1, 0, 1}, 12U) == "fff\n000\n001\n",
           "canonical signed serialization", failures);
    expect(canonical_memh_serialization_unsigned(std::vector<std::uint64_t>{0U, 32768U}, 16U) == "0000\n8000\n",
           "canonical unsigned serialization", failures);

    expect_throws([] { static_cast<void>(hex_digit(16U)); }, "hex digit out of range", failures);
    expect_throws([] { static_cast<void>(parse_lowercase_hex_line("FFF", 12U)); }, "uppercase hex rejected", failures);
    expect_throws([] { static_cast<void>(parse_lowercase_hex_line("0x0", 12U)); }, "0x prefix rejected", failures);
    expect_throws([] { static_cast<void>(parse_lowercase_hex_line("00", 12U)); }, "short fixed-width line rejected", failures);
    expect_throws([] { static_cast<void>(parse_lowercase_hex_line("1000", 12U)); }, "encoded value above width rejected", failures);
    expect_throws([&window_spec] { static_cast<void>(encode_memh_line(-1, window_spec)); }, "negative unsigned memh rejected", failures);

    const std::filesystem::path root = std::filesystem::temp_directory_path() / "trecap_test_memh_cpp";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);

    const std::filesystem::path sample_path = root / "x_in.memh";
    const std::vector<std::int64_t> sample_values{-2048, -1, 0, 2047};
    write_memh(sample_path, sample_values, sample_spec);
    const std::vector<std::int64_t> round_trip = read_memh(sample_path, sample_spec);
    expect(round_trip == sample_values, "signed memh round-trip", failures);
    expect(count_lf_lines(sample_path) == 4U, "signed memh LF count", failures);

    const std::filesystem::path window_path = root / "window_qw.memh";
    const std::vector<std::uint64_t> window_values{0U, 1U, 32768U};
    write_memh_unsigned(window_path, window_values, window_spec);
    const std::vector<std::int64_t> window_read = read_memh(window_path, window_spec);
    expect(window_read == std::vector<std::int64_t>({0, 1, 32768}), "unsigned memh round-trip", failures);

    const std::filesystem::path twiddle_path = root / "twiddle_re.memh";
    const std::vector<std::int64_t> twiddle_values{32768, -32768, -1};
    write_memh(twiddle_path, twiddle_values, twiddle_spec);
    expect(read_memh(twiddle_path, twiddle_spec) == twiddle_values, "signed 17-bit twiddle round-trip", failures);

    expect_throws([&root, &sample_values] { write_memh(root / "bad_count.memh", sample_values, signed_memh_spec(12U, 3U)); },
                  "write_memh expected line mismatch", failures);
    write_text_file(root / "blank.memh", "000\n\n001\n");
    expect_throws([&root] { static_cast<void>(read_memh(root / "blank.memh", signed_memh_spec(12U))); }, "blank line rejected", failures);
    write_text_file(root / "crlf.memh", "000\r\n001\r\n");
    expect_throws([&root] { static_cast<void>(read_memh(root / "crlf.memh", signed_memh_spec(12U))); }, "CRLF rejected", failures);

    std::filesystem::remove_all(root);

    return failures == 0 ? 0 : 1;
}
