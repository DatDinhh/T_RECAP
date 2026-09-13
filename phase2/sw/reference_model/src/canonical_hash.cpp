// SPDX-License-Identifier: MIT
#include "trecap_golden/canonical_hash.hpp"

#include <array>
#include <fstream>
#include <vector>

namespace trecap::golden {
namespace detail {

[[nodiscard]] constexpr std::uint32_t rotr32(const std::uint32_t x, const unsigned n) noexcept {
    return (x >> n) | (x << (32U - n));
}

[[nodiscard]] constexpr std::uint32_t sha256_ch(const std::uint32_t x,
                                                const std::uint32_t y,
                                                const std::uint32_t z) noexcept {
    return (x & y) ^ (~x & z);
}

[[nodiscard]] constexpr std::uint32_t sha256_maj(const std::uint32_t x,
                                                 const std::uint32_t y,
                                                 const std::uint32_t z) noexcept {
    return (x & y) ^ (x & z) ^ (y & z);
}

inline constexpr std::array<std::uint32_t, 64> kSha256K{
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U};

class Sha256 final {
public:
    Sha256() = default;

    void update(std::span<const std::uint8_t> bytes) {
        total_bytes_ += static_cast<std::uint64_t>(bytes.size());
        for (const std::uint8_t byte : bytes) {
            buffer_[buffer_size_] = byte;
            ++buffer_size_;
            if (buffer_size_ == buffer_.size()) {
                transform(buffer_);
                buffer_size_ = 0U;
            }
        }
    }

    void update(const std::string_view bytes) {
        const auto* ptr = reinterpret_cast<const std::uint8_t*>(bytes.data());
        update(std::span<const std::uint8_t>(ptr, bytes.size()));
    }

    [[nodiscard]] std::array<std::uint8_t, 32> final() {
        const std::uint64_t bit_len = total_bytes_ * 8U;
        buffer_[buffer_size_] = 0x80U;
        ++buffer_size_;
        if (buffer_size_ > 56U) {
            while (buffer_size_ < 64U) {
                buffer_[buffer_size_] = 0U;
                ++buffer_size_;
            }
            transform(buffer_);
            buffer_size_ = 0U;
        }
        while (buffer_size_ < 56U) {
            buffer_[buffer_size_] = 0U;
            ++buffer_size_;
        }
        for (unsigned i = 0U; i < 8U; ++i) {
            const unsigned shift = 56U - (8U * i);
            buffer_[56U + i] = static_cast<std::uint8_t>((bit_len >> shift) & 0xFFU);
        }
        transform(buffer_);

        std::array<std::uint8_t, 32> digest{};
        for (unsigned i = 0U; i < 8U; ++i) {
            const std::uint32_t word = state_[i];
            digest[4U * i] = static_cast<std::uint8_t>((word >> 24U) & 0xFFU);
            digest[(4U * i) + 1U] = static_cast<std::uint8_t>((word >> 16U) & 0xFFU);
            digest[(4U * i) + 2U] = static_cast<std::uint8_t>((word >> 8U) & 0xFFU);
            digest[(4U * i) + 3U] = static_cast<std::uint8_t>(word & 0xFFU);
        }
        return digest;
    }

private:
    void transform(const std::array<std::uint8_t, 64>& block) {
        std::array<std::uint32_t, 64> w{};
        for (unsigned i = 0U; i < 16U; ++i) {
            const std::size_t j = static_cast<std::size_t>(4U * i);
            w[i] = (static_cast<std::uint32_t>(block[j]) << 24U) |
                   (static_cast<std::uint32_t>(block[j + 1U]) << 16U) |
                   (static_cast<std::uint32_t>(block[j + 2U]) << 8U) | static_cast<std::uint32_t>(block[j + 3U]);
        }
        for (unsigned i = 16U; i < 64U; ++i) {
            const std::uint32_t s0 = rotr32(w[i - 15U], 7U) ^ rotr32(w[i - 15U], 18U) ^ (w[i - 15U] >> 3U);
            const std::uint32_t s1 = rotr32(w[i - 2U], 17U) ^ rotr32(w[i - 2U], 19U) ^ (w[i - 2U] >> 10U);
            w[i] = w[i - 16U] + s0 + w[i - 7U] + s1;
        }

        std::uint32_t a = state_[0];
        std::uint32_t b = state_[1];
        std::uint32_t c = state_[2];
        std::uint32_t d = state_[3];
        std::uint32_t e = state_[4];
        std::uint32_t f = state_[5];
        std::uint32_t g = state_[6];
        std::uint32_t h = state_[7];

        for (unsigned i = 0U; i < 64U; ++i) {
            const std::uint32_t s1 = rotr32(e, 6U) ^ rotr32(e, 11U) ^ rotr32(e, 25U);
            const std::uint32_t temp1 = h + s1 + sha256_ch(e, f, g) + kSha256K[i] + w[i];
            const std::uint32_t s0 = rotr32(a, 2U) ^ rotr32(a, 13U) ^ rotr32(a, 22U);
            const std::uint32_t temp2 = s0 + sha256_maj(a, b, c);
            h = g;
            g = f;
            f = e;
            e = d + temp1;
            d = c;
            c = b;
            b = a;
            a = temp1 + temp2;
        }

        state_[0] += a;
        state_[1] += b;
        state_[2] += c;
        state_[3] += d;
        state_[4] += e;
        state_[5] += f;
        state_[6] += g;
        state_[7] += h;
    }

    std::array<std::uint32_t, 8> state_{0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
                                        0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U};
    std::array<std::uint8_t, 64> buffer_{};
    std::size_t buffer_size_{};
    std::uint64_t total_bytes_{};
};

}  // namespace detail

std::string bytes_to_lower_hex(std::span<const std::uint8_t> bytes) {
    std::string out;
    out.reserve(bytes.size() * 2U);
    for (const std::uint8_t byte : bytes) {
        out.push_back(hex_digit(static_cast<std::uint8_t>((byte >> 4U) & 0x0FU)));
        out.push_back(hex_digit(static_cast<std::uint8_t>(byte & 0x0FU)));
    }
    return out;
}

std::string sha256_bytes(const std::string_view bytes) {
    detail::Sha256 sha;
    sha.update(bytes);
    const auto digest = sha.final();
    return bytes_to_lower_hex(digest);
}

std::string sha256_file_bytes(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw contract_error("failed to open file for sha256: " + path.string());
    }
    detail::Sha256 sha;
    std::array<std::uint8_t, 4096> buffer{};
    while (in) {
        in.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(buffer.size()));
        const std::streamsize got = in.gcount();
        if (got > 0) {
            sha.update(std::span<const std::uint8_t>(buffer.data(), static_cast<std::size_t>(got)));
        }
    }
    const auto digest = sha.final();
    return bytes_to_lower_hex(digest);
}

std::string sha256_memh_signed(std::span<const std::int64_t> values, const unsigned width) {
    return sha256_bytes(canonical_memh_serialization_signed(values, width));
}

std::string sha256_memh_unsigned(std::span<const std::uint64_t> values, const unsigned width) {
    return sha256_bytes(canonical_memh_serialization_unsigned(values, width));
}

std::string sha256_memh_canonical_file(const std::filesystem::path& path, const MemhSpec& spec) {
    const std::vector<std::int64_t> values = read_memh(path, spec);
    return sha256_bytes(canonical_memh_serialization(values, spec));
}

bool is_lowercase_sha256_hex(const std::string_view value) {
    if (value.size() != 64U) {
        return false;
    }
    for (const char ch : value) {
        const bool digit = ch >= '0' && ch <= '9';
        const bool lower = ch >= 'a' && ch <= 'f';
        if (!digit && !lower) {
            return false;
        }
    }
    return true;
}

}  // namespace trecap::golden
