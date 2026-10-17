#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>

namespace trecap {
constexpr std::size_t bins = 129, bands = 16, max_packet = 1080;
constexpr std::uint64_t mag_mask = (std::uint64_t{1} << 56) - 1;
using Dense = std::array<std::uint64_t, bins>;
using Features = std::array<std::uint64_t, bands>;
struct Sparse {
    std::array<std::uint64_t, bins> entries{};
    std::size_t count = 0;
};
struct Packet {
    std::array<std::uint8_t, max_packet> bytes{};
    std::size_t size = 0;
    std::span<const std::uint8_t> view() const { return {bytes.data(), size}; }
};
enum class Encoding : std::uint16_t { dense = 0, sparse = 1 };
struct Expected { std::uint64_t frame, threshold; };
std::uint64_t checksum(std::span<const std::uint8_t> packet);
std::uint64_t byte_hash(std::span<const std::uint8_t> bytes);
// Encoder numeric/mask inputs are trusted after fixture admission validation.
// Decoders are the untrusted-record boundary and fully validate incoming bytes.
void encode_dense(const Dense&, Expected, Packet&);
void encode_sparse(const Sparse&, Expected, Packet&);
void decode_dense(std::span<const std::uint8_t>, Expected, Dense&);
void decode_sparse(std::span<const std::uint8_t>, Expected, Sparse&);
Sparse make_sparse(const Dense& original, const std::array<bool, bins>& masked);
void prepare_sparse(const Dense& original, const std::array<bool, bins>& masked, Sparse&);
void consume_dense(const Dense&, Features&);
void consume_sparse(const Sparse&, Features&);
// Separate translation unit, no LTO: output memory must be materialized at every call.
void observe(const void* memory, std::size_t bytes);
std::uint64_t observer_value();
}
