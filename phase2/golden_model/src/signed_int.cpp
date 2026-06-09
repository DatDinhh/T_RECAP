// SPDX-License-Identifier: MIT
#include "trecap_golden/signed_int.hpp"

namespace trecap::golden {
namespace {

static_assert(signed_min(12U) == -2048);
static_assert(signed_max(12U) == 2047);
static_assert(fits_signed(-2048, 12U));
static_assert(fits_signed(2047, 12U));
static_assert(!fits_signed(2048, 12U));
static_assert(fits_unsigned(0x0fffU, 12U));
static_assert(!fits_unsigned(0x1000U, 12U));
static_assert(encode_signed_twos_complement(-1, 12U) == 0x0fffU);
static_assert(sign_extend_twos_complement(0x0800U, 12U) == -2048);
static_assert(sign_extend_twos_complement(0x07ffU, 12U) == 2047);
static_assert(fixed_hex_digits(17U) == 5U);

}  // namespace
}  // namespace trecap::golden
