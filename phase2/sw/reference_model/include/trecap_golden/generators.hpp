// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "trecap_golden/rounding.hpp"
#include "trecap_golden/saturation.hpp"
#include "trecap_golden/widths.hpp"

namespace trecap::golden {

inline constexpr long double kPi = 3.141592653589793238462643383279502884L;

enum class GeneratorKind : std::uint8_t {
    constant,
    impulse,
    step,
    sine,
    cosine,
    multitone_sine_sum,
    uniform_noise_xorshift32,
};

struct RationalFrequency final {
    std::uint64_t f_num{};
    std::uint64_t f_den{1U};

    constexpr void validate() const {
        if (f_den == 0U) {
            throw contract_error("frequency denominator must be nonzero");
        }
    }

    [[nodiscard]] constexpr long double as_long_double() const {
        validate();
        return static_cast<long double>(f_num) / static_cast<long double>(f_den);
    }
};

struct Tone final {
    std::int64_t amplitude{};
    RationalFrequency frequency{};
    std::string phase_rad{"0"};
};

[[nodiscard]] long double parse_decimal_phase_rad(std::string_view text);

[[nodiscard]] std::int64_t generator_sample_quantize(long double value, const CoreConfig& cfg);

[[nodiscard]] std::vector<std::int64_t> generate_constant(std::uint64_t ns,
                                                          std::int64_t value,
                                                          const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_impulse(std::uint64_t ns,
                                                         std::uint64_t index,
                                                         std::int64_t amplitude,
                                                         const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_step(std::uint64_t ns,
                                                      std::uint64_t index,
                                                      std::int64_t amplitude,
                                                      const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_sine(std::uint64_t ns,
                                                      std::int64_t amplitude,
                                                      RationalFrequency frequency,
                                                      std::string_view phase_rad = "0",
                                                      const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_cosine(std::uint64_t ns,
                                                        std::int64_t amplitude,
                                                        RationalFrequency frequency,
                                                        std::string_view phase_rad = "0",
                                                        const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::vector<std::int64_t> generate_multitone_sine_sum(std::uint64_t ns,
                                                                    std::span<const Tone> tones,
                                                                    const CoreConfig& cfg = CoreConfig::baseline());

[[nodiscard]] std::uint32_t xorshift32_next(std::uint32_t state);

[[nodiscard]] std::vector<std::int64_t> generate_uniform_noise_xorshift32(std::uint64_t ns,
                                                                          std::uint32_t seed,
                                                                          unsigned bit_width_b,
                                                                          const CoreConfig& cfg = CoreConfig::baseline());

}  // namespace trecap::golden
