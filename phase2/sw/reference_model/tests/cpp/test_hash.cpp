// SPDX-License-Identifier: MIT
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

#include "trecap_golden/canonical_hash.hpp"
#include "trecap_golden/memh.hpp"

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

    expect(bytes_to_lower_hex(std::vector<std::uint8_t>{0x00U, 0x0fU, 0xa5U, 0xffU}) == "000fa5ff",
           "bytes to lowercase hex", failures);
    expect(sha256_bytes("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
           "SHA-256 empty string", failures);
    expect(sha256_bytes("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
           "SHA-256 abc", failures);
    expect(is_lowercase_sha256_hex(sha256_bytes("abc")), "sha256 hex validator accepts digest", failures);
    expect(!is_lowercase_sha256_hex("BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"),
           "sha256 validator rejects uppercase", failures);
    expect(!is_lowercase_sha256_hex("abc"), "sha256 validator rejects short value", failures);
    expect(!is_lowercase_sha256_hex("gggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggg"),
           "sha256 validator rejects non-hex", failures);

    const std::vector<std::int64_t> signed_values{-1, 0, 1};
    const std::string signed_serialized = canonical_memh_serialization_signed(signed_values, 12U);
    expect(signed_serialized == "fff\n000\n001\n", "signed canonical serialization used for hash", failures);
    expect(sha256_memh_signed(signed_values, 12U) == sha256_bytes(signed_serialized),
           "signed memh hash equals canonical byte hash", failures);

    const std::vector<std::uint64_t> unsigned_values{0U, 1U, 32768U};
    const std::string unsigned_serialized = canonical_memh_serialization_unsigned(unsigned_values, 16U);
    expect(unsigned_serialized == "0000\n0001\n8000\n", "unsigned canonical serialization used for hash", failures);
    expect(sha256_memh_unsigned(unsigned_values, 16U) == sha256_bytes(unsigned_serialized),
           "unsigned memh hash equals canonical byte hash", failures);

    const std::filesystem::path root = std::filesystem::temp_directory_path() / "trecap_test_hash_cpp";
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);

    const std::filesystem::path raw_path = root / "raw.txt";
    write_text_file(raw_path, "abc");
    expect(sha256_file_bytes(raw_path) == sha256_bytes("abc"), "file byte SHA-256", failures);

    const std::filesystem::path signed_path = root / "x_in.memh";
    const MemhSpec sample_spec = signed_memh_spec(12U, 3U, "x_in.memh");
    write_memh(signed_path, signed_values, sample_spec);
    expect(sha256_memh_canonical_file(signed_path, sample_spec) == sha256_memh_signed(signed_values, 12U),
           "canonical signed memh file hash", failures);
    expect(sha256_file_bytes(signed_path) == sha256_memh_signed(signed_values, 12U),
           "raw file hash equals canonical hash for canonical memh", failures);

    const std::filesystem::path unsigned_path = root / "window_qw.memh";
    const MemhSpec window_spec = unsigned_memh_spec(16U, 3U, "window_qw.memh");
    write_memh_unsigned(unsigned_path, unsigned_values, window_spec);
    expect(sha256_memh_canonical_file(unsigned_path, window_spec) == sha256_memh_unsigned(unsigned_values, 16U),
           "canonical unsigned memh file hash", failures);

    write_text_file(root / "uppercase.memh", "FFF\n000\n001\n");
    expect_throws([&root, &sample_spec] { static_cast<void>(sha256_memh_canonical_file(root / "uppercase.memh", sample_spec)); },
                  "canonical hash rejects uppercase memh", failures);

    write_text_file(root / "crlf.memh", "fff\r\n000\r\n001\r\n");
    expect_throws([&root, &sample_spec] { static_cast<void>(sha256_memh_canonical_file(root / "crlf.memh", sample_spec)); },
                  "canonical hash rejects CRLF memh", failures);

    std::filesystem::remove_all(root);

    return failures == 0 ? 0 : 1;
}
