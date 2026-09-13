// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <string_view>

#include "trecap_golden/signed_int.hpp"

namespace trecap::golden {

inline constexpr std::string_view kContractRevision = "phase2_core_revision_j";
inline constexpr std::string_view kFftMode = "custom_radix2_dit_bitrev_in_natural_out";
inline constexpr std::string_view kRoundingMode = "round_nearest_ties_away_from_zero";
inline constexpr std::string_view kTailPolicyFullTail = "full_tail";
inline constexpr std::string_view kThresholdMappingRawThr2 = "raw_thr2";

inline constexpr unsigned kSampleWidthN = 12U;
inline constexpr unsigned kFftLengthL = 256U;
inline constexpr unsigned kRadixStagesP = 8U;
inline constexpr unsigned kHopSizeH = 128U;
inline constexpr unsigned kFractionalBitsF = 15U;
inline constexpr unsigned kSchedulingCushionG = 128U;
inline constexpr unsigned kCoreDelayD = kFftLengthL + kSchedulingCushionG;
inline constexpr bool kProtectDcDefault = true;
inline constexpr bool kProtectNyquistDefault = false;
inline constexpr unsigned kUniqueBinCount = (kFftLengthL / 2U) + 1U;

struct CoreConfig final {
    unsigned N{kSampleWidthN};
    unsigned L{kFftLengthL};
    unsigned P{kRadixStagesP};
    unsigned H{kHopSizeH};
    unsigned F{kFractionalBitsF};
    unsigned G{kSchedulingCushionG};
    unsigned D{kCoreDelayD};
    bool protect_dc{kProtectDcDefault};
    bool protect_nyq{kProtectNyquistDefault};

    [[nodiscard]] static constexpr CoreConfig baseline() noexcept {
        return CoreConfig{};
    }

    [[nodiscard]] constexpr unsigned unique_bins() const noexcept {
        return (L / 2U) + 1U;
    }

    [[nodiscard]] constexpr bool is_baseline() const noexcept {
        return N == kSampleWidthN && L == kFftLengthL && P == kRadixStagesP && H == kHopSizeH &&
               F == kFractionalBitsF && G == kSchedulingCushionG && D == kCoreDelayD &&
               protect_dc == kProtectDcDefault && protect_nyq == kProtectNyquistDefault;
    }

    constexpr void validate() const {
        if (N == 0U || N > 62U) {
            throw contract_error("invalid sample width N");
        }
        if (L == 0U || (L & (L - 1U)) != 0U) {
            throw contract_error("FFT length L must be a power of two");
        }
        if ((1U << P) != L) {
            throw contract_error("P must satisfy L = 2^P");
        }
        if (H != L / 2U) {
            throw contract_error("Revision J baseline requires H = L/2");
        }
        if (D != L + G) {
            throw contract_error("delay D must equal L + G");
        }
        if (F == 0U || F > 30U) {
            throw contract_error("fractional width F is outside supported golden-model range");
        }
    }
};

struct WidthConfig final {
    unsigned W_x{};
    unsigned W_Qw{};
    unsigned W_tw{};
    unsigned W_u{};
    unsigned W_fft{};
    unsigned W_fft_pre{};
    unsigned W_can_pre{};
    unsigned W_can{};
    unsigned W_mag2{};
    unsigned W_ifft{};
    unsigned W_z{};
    unsigned W_ola{};

    [[nodiscard]] static constexpr WidthConfig from_core(const CoreConfig& cfg = CoreConfig::baseline()) {
        return WidthConfig{
            cfg.N,
            cfg.F + 1U,
            cfg.F + 2U,
            cfg.N + cfg.F,
            cfg.N + cfg.F + 1U,
            cfg.N + cfg.F + 2U,
            cfg.N + cfg.F + 2U,
            cfg.N + cfg.F + 1U,
            2U * (cfg.N + cfg.F + 1U),
            cfg.N + cfg.F + 1U + cfg.P,
            cfg.N + cfg.F + 1U + cfg.P,
            cfg.N + cfg.F + 1U + cfg.P + 1U,
        };
    }

    [[nodiscard]] static constexpr WidthConfig baseline() {
        return from_core(CoreConfig::baseline());
    }

    constexpr void validate_for(const CoreConfig& cfg) const {
        const WidthConfig expected = WidthConfig::from_core(cfg);
        if (W_x != expected.W_x || W_Qw != expected.W_Qw || W_tw != expected.W_tw || W_u != expected.W_u ||
            W_fft != expected.W_fft || W_fft_pre != expected.W_fft_pre || W_can_pre != expected.W_can_pre ||
            W_can != expected.W_can || W_mag2 != expected.W_mag2 || W_ifft != expected.W_ifft ||
            W_z != expected.W_z || W_ola != expected.W_ola) {
            throw contract_error("width schedule does not match Revision J formulas");
        }
    }
};

inline constexpr WidthConfig kBaselineWidths = WidthConfig::baseline();

static_assert(kBaselineWidths.W_x == 12U);
static_assert(kBaselineWidths.W_Qw == 16U);
static_assert(kBaselineWidths.W_tw == 17U);
static_assert(kBaselineWidths.W_u == 27U);
static_assert(kBaselineWidths.W_fft == 28U);
static_assert(kBaselineWidths.W_fft_pre == 29U);
static_assert(kBaselineWidths.W_can_pre == 29U);
static_assert(kBaselineWidths.W_can == 28U);
static_assert(kBaselineWidths.W_mag2 == 56U);
static_assert(kBaselineWidths.W_ifft == 36U);
static_assert(kBaselineWidths.W_z == 36U);
static_assert(kBaselineWidths.W_ola == 37U);

struct StreamGeometry final {
    std::uint64_t Ns{};
    std::uint64_t Nframes{};
    std::uint64_t tau_last{};
    std::uint64_t Ny{};
};

[[nodiscard]] constexpr std::uint64_t full_tail_frame_count(const std::uint64_t ns, const CoreConfig& cfg = CoreConfig::baseline()) {
    if (ns == 0U) {
        throw contract_error("Revision J signoff vectors require Ns > 0");
    }
    return (ns + static_cast<std::uint64_t>(cfg.L) - 2U) / static_cast<std::uint64_t>(cfg.H);
}

[[nodiscard]] constexpr StreamGeometry full_tail_geometry(const std::uint64_t ns,
                                                          const CoreConfig& cfg = CoreConfig::baseline()) {
    cfg.validate();
    const std::uint64_t frames = full_tail_frame_count(ns, cfg);
    const std::uint64_t tau_last = frames * static_cast<std::uint64_t>(cfg.H);
    const std::uint64_t ny = tau_last + static_cast<std::uint64_t>(cfg.G) + static_cast<std::uint64_t>(cfg.L);
    return StreamGeometry{ns, frames, tau_last, ny};
}

}  // namespace trecap::golden
