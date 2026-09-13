// SPDX-License-Identifier: MIT
#include "trecap_golden/version.hpp"

namespace trecap::golden {
namespace {

static_assert(kGoldenVersionMajor == TRECAP_GOLDEN_VERSION_MAJOR);
static_assert(kSpecRevision == "core_rev_j");
static_assert(kHashRule == "logical_integer_vector_fixed_width_hex_lf");

}  // namespace

std::string golden_version_string() {
    return std::to_string(kGoldenVersionMajor) + "." + std::to_string(kGoldenVersionMinor) + "." +
           std::to_string(kGoldenVersionPatch);
}

std::string golden_model_version_tag() {
    return std::string{kGoldenModelName} + ":" + golden_version_string() + ":" + std::string{kSpecRevision};
}

}  // namespace trecap::golden
