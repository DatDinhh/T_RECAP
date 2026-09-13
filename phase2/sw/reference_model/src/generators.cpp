// SPDX-License-Identifier: MIT
#include "trecap_golden/generators.hpp"

#include <cmath>
#include <limits>

namespace trecap::golden {
namespace {

static_assert(CoreConfig::baseline().N == 12U);
static_assert(CoreConfig::baseline().L == 256U);

void require_positive_ns(const std::uint64_t ns) {
    if (ns == 0U) {
        throw contract_error("generator Ns must be positive");
    }
}

}  // namespace

long double parse_decimal_phase_rad(const std::string_view text) {
    if (text.empty()) {
        throw contract_error("phase_rad cannot be empty");
    }
    std::size_t parsed = 0U;
    const long double value = std::stold(std::string{text}, &parsed);
    if (parsed != text.size()) {
        throw contract_error("phase_rad contains trailing characters");
    }
    if (!std::isfinite(value)) {
        throw contract_error("phase_rad is not finite");
    }
    return value;
}

std::int64_t generator_sample_quantize(const long double value, const CoreConfig& cfg) {
    return sat_sample(qcoef(value, 0U), cfg.N);
}

std::vector<std::int64_t> generate_constant(const std::uint64_t ns,
                                            const std::int64_t value,
                                            const CoreConfig& cfg) {
    cfg.validate();
    require_positive_ns(ns);
    return std::vector<std::int64_t>(static_cast<std::size_t>(ns), sat_sample(value, cfg.N));
}

std::vector<std::int64_t> generate_impulse(const std::uint64_t ns,
                                           const std::uint64_t index,
                                           const std::int64_t amplitude,
                                           const CoreConfig& cfg) {
    std::vector<std::int64_t> out = generate_constant(ns, 0, cfg);
    if (index >= ns) {
        throw contract_error("impulse index outside vector length");
    }
    out[static_cast<std::size_t>(index)] = sat_sample(amplitude, cfg.N);
    return out;
}

std::vector<std::int64_t> generate_step(const std::uint64_t ns,
                                        const std::uint64_t index,
                                        const std::int64_t amplitude,
                                        const CoreConfig& cfg) {
    std::vector<std::int64_t> out = generate_constant(ns, 0, cfg);
    if (index > ns) {
        throw contract_error("step index outside vector length");
    }
    const std::int64_t clipped = sat_sample(amplitude, cfg.N);
    for (std::uint64_t n = index; n < ns; ++n) {
        out[static_cast<std::size_t>(n)] = clipped;
    }
    return out;
}

std::vector<std::int64_t> generate_sine(const std::uint64_t ns,
                                        const std::int64_t amplitude,
                                        const RationalFrequency frequency,
                                        const std::string_view phase_rad,
                                        const CoreConfig& cfg) {
    cfg.validate();
    frequency.validate();
    require_positive_ns(ns);
    const long double freq = frequency.as_long_double();
    const long double phase = parse_decimal_phase_rad(phase_rad);
    std::vector<std::int64_t> out;
    out.reserve(static_cast<std::size_t>(ns));
    for (std::uint64_t n = 0U; n < ns; ++n) {
        const long double angle = (2.0L * kPi * freq * static_cast<long double>(n)) + phase;
        out.push_back(generator_sample_quantize(static_cast<long double>(amplitude) * std::sin(angle), cfg));
    }
    return out;
}

std::vector<std::int64_t> generate_cosine(const std::uint64_t ns,
                                          const std::int64_t amplitude,
                                          const RationalFrequency frequency,
                                          const std::string_view phase_rad,
                                          const CoreConfig& cfg) {
    cfg.validate();
    frequency.validate();
    require_positive_ns(ns);
    const long double freq = frequency.as_long_double();
    const long double phase = parse_decimal_phase_rad(phase_rad);
    std::vector<std::int64_t> out;
    out.reserve(static_cast<std::size_t>(ns));
    for (std::uint64_t n = 0U; n < ns; ++n) {
        const long double angle = (2.0L * kPi * freq * static_cast<long double>(n)) + phase;
        out.push_back(generator_sample_quantize(static_cast<long double>(amplitude) * std::cos(angle), cfg));
    }
    return out;
}

std::vector<std::int64_t> generate_multitone_sine_sum(const std::uint64_t ns,
                                                      std::span<const Tone> tones,
                                                      const CoreConfig& cfg) {
    cfg.validate();
    require_positive_ns(ns);
    if (tones.empty()) {
        throw contract_error("multitone generator requires at least one tone");
    }
    std::vector<long double> phase;
    phase.reserve(tones.size());
    for (const Tone& tone : tones) {
        tone.frequency.validate();
        phase.push_back(parse_decimal_phase_rad(tone.phase_rad));
    }
    std::vector<std::int64_t> out;
    out.reserve(static_cast<std::size_t>(ns));
    for (std::uint64_t n = 0U; n < ns; ++n) {
        long double sum = 0.0L;
        for (std::size_t q = 0U; q < tones.size(); ++q) {
            const Tone& tone = tones[q];
            const long double angle = (2.0L * kPi * tone.frequency.as_long_double() * static_cast<long double>(n)) +
                                      phase[q];
            sum += static_cast<long double>(tone.amplitude) * std::sin(angle);
        }
        out.push_back(generator_sample_quantize(sum, cfg));
    }
    return out;
}

std::uint32_t xorshift32_next(std::uint32_t state) {
    if (state == 0U) {
        throw contract_error("xorshift32 seed/state must be nonzero");
    }
    state ^= state << 13U;
    state ^= state >> 17U;
    state ^= state << 5U;
    return state;
}

std::vector<std::int64_t> generate_uniform_noise_xorshift32(const std::uint64_t ns,
                                                            const std::uint32_t seed,
                                                            const unsigned bit_width_b,
                                                            const CoreConfig& cfg) {
    cfg.validate();
    require_positive_ns(ns);
    if (seed == 0U) {
        throw contract_error("xorshift32 seed must be nonzero");
    }
    if (bit_width_b == 0U || bit_width_b > 32U) {
        throw contract_error("noise bit width B must satisfy 1 <= B <= 32");
    }
    std::uint32_t state = seed;
    const std::uint64_t mask = bit_width_b == 32U ? 0xffffffffULL : ((std::uint64_t{1} << bit_width_b) - 1U);
    const std::int64_t offset = static_cast<std::int64_t>(std::uint64_t{1} << (bit_width_b - 1U));
    std::vector<std::int64_t> out;
    out.reserve(static_cast<std::size_t>(ns));
    for (std::uint64_t n = 0U; n < ns; ++n) {
        state = xorshift32_next(state);
        const std::uint64_t u = static_cast<std::uint64_t>(state) & mask;
        const std::int64_t centered = static_cast<std::int64_t>(u) - offset;
        out.push_back(sat_sample(centered, cfg.N));
    }
    return out;
}

}  // namespace trecap::golden
