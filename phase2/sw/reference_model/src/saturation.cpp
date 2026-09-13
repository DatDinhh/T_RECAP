// SPDX-License-Identifier: MIT
#include "trecap_golden/saturation.hpp"

namespace trecap::golden {
namespace {

static_assert(!saturate_signed_result(0, 12U).saturated());
static_assert(saturate_signed_result(4096, 12U).saturated());
static_assert(saturate_signed_result(4096, 12U).kind == SaturationKind::high);
static_assert(saturate_signed_result(-4097, 12U).kind == SaturationKind::low);
static_assert(sat_signed(4096, 12U) == 2047);
static_assert(sat_signed(-4097, 12U) == -2048);
static_assert(sat_sample(99) == 99);
static_assert(checked_signed_assignment(-2048, 12U) == -2048);
static_assert(checked_unsigned_assignment(32768U, 16U) == 32768U);

}  // namespace
}  // namespace trecap::golden
