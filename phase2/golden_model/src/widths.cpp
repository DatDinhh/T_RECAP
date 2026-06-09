// SPDX-License-Identifier: MIT
#include "trecap_golden/widths.hpp"

namespace trecap::golden {
namespace {

static_assert(CoreConfig::baseline().is_baseline());
static_assert(kCoreDelayD == kFftLengthL + kSchedulingCushionG);
static_assert(kUniqueBinCount == 129U);
static_assert(kBaselineWidths.W_Qw == kFractionalBitsF + 1U);
static_assert(kBaselineWidths.W_tw == kFractionalBitsF + 2U);
static_assert(kBaselineWidths.W_u == kSampleWidthN + kFractionalBitsF);
static_assert(kBaselineWidths.W_ola == 37U);
static_assert(full_tail_frame_count(4096U) == 33U);
static_assert(full_tail_geometry(4096U).Ny == 4608U);

}  // namespace
}  // namespace trecap::golden
