// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <string>
#include <string_view>

#include "trecap_golden/widths.hpp"

#ifndef TRECAP_GOLDEN_VERSION_MAJOR
#define TRECAP_GOLDEN_VERSION_MAJOR 0
#endif
#ifndef TRECAP_GOLDEN_VERSION_MINOR
#define TRECAP_GOLDEN_VERSION_MINOR 1
#endif
#ifndef TRECAP_GOLDEN_VERSION_PATCH
#define TRECAP_GOLDEN_VERSION_PATCH 0
#endif

namespace trecap::golden {

inline constexpr std::uint32_t kGoldenVersionMajor = TRECAP_GOLDEN_VERSION_MAJOR;
inline constexpr std::uint32_t kGoldenVersionMinor = TRECAP_GOLDEN_VERSION_MINOR;
inline constexpr std::uint32_t kGoldenVersionPatch = TRECAP_GOLDEN_VERSION_PATCH;

inline constexpr std::string_view kSpecRevision = reference_config::SPEC_REVISION;
inline constexpr std::string_view kTelemetryRevision = reference_config::TELEMETRY_REVISION;
inline constexpr std::string_view kCoeffManifestSchema = "trecap_phase2_coeff_manifest_v1";
inline constexpr std::string_view kVectorConfigSchema = "trecap_phase2_vector_config_v1";
inline constexpr std::string_view kMetricsSchema = "trecap_phase2_metrics_v1";
inline constexpr std::string_view kTestVectorsSchema = "trecap_phase2_test_vectors_v1";
inline constexpr std::string_view kArtifactIndexSchema = "trecap_phase2_artifact_index_v1";
inline constexpr std::string_view kQualityBoundsSchema = "trecap_phase2_quality_bounds_v1";
inline constexpr std::string_view kFrozenReleaseSchema = "trecap_phase2_frozen_release_manifest_v1";

inline constexpr std::string_view kMemhEncoding = reference_config::MEMH_ENCODING;
inline constexpr std::string_view kHashRule = reference_config::HASH_RULE;
inline constexpr std::string_view kQcoefRule = "round_nearest_ties_away_from_zero";
inline constexpr std::string_view kGeneratorVersion = "phase2_generators_revision_j";
inline constexpr std::string_view kGoldenModelName = "trecap-golden";

[[nodiscard]] std::string golden_version_string();

[[nodiscard]] std::string golden_model_version_tag();

}  // namespace trecap::golden
