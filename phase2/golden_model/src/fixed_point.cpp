// SPDX-License-Identifier: MIT
#include "trecap_golden/fixed_point.hpp"

namespace trecap::golden {
namespace {

static_assert(sample_value(0).format.width == kSampleWidthN);
static_assert(sample_value(0).format.frac == 0U);
static_assert(sample_value(-1).encoded() == 0x0fffU);
static_assert(twiddle_value(32768, kFractionalBitsF).format.width == kBaselineWidths.W_tw);

}  // namespace
}  // namespace trecap::golden
