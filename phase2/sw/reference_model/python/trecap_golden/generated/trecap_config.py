# SPDX-License-Identifier: MIT
# AUTO-GENERATED - DO NOT EDIT.
# Source contract: T-RECAP Phase 2 Core Revision J golden-model baseline.
# This checked-in generated module mirrors spec/generated/core_config.json for the
# golden-model-only repository. Regenerate it from the schema/config source once the
# spec/generated generator layer is populated.

"""Generated T-RECAP Phase 2 golden-model contract constants.

This module is intentionally dependency-free. It is imported by Python tooling,
schema validation helpers, and tests that need the frozen golden-model baseline
without parsing C++ headers or artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

SCHEMA: Final[str] = "trecap_phase2_core_config_v1"
SPEC_REVISION: Final[str] = "core_rev_j"
TELEMETRY_REVISION: Final[str] = "telemetry_rev_g"
GENERATOR_VERSION: Final[str] = "phase2_generators_revision_j"
GOLDEN_MODEL_VERSION: Final[str] = "0.1.0"

# Core constants.
N: Final[int] = 12
L: Final[int] = 256
P: Final[int] = 8
H: Final[int] = 128
F: Final[int] = 15
G: Final[int] = 128
D: Final[int] = 384

# Baseline controls.
THR2_DEFAULT: Final[str] = "0"
PROTECT_DC_DEFAULT: Final[int] = 1
PROTECT_NYQ_DEFAULT: Final[int] = 0
TAIL_POLICY: Final[str] = "full_tail"
FFT_MODE: Final[str] = "custom_radix2_dit_bitrev_in_natural_out"
ROUNDING_MODE: Final[str] = "round_nearest_ties_away_from_zero"
THRESHOLD_MAPPING: Final[str] = "raw_thr2"
MEMH_ENCODING: Final[str] = "fixed_width_lowercase_hex_lf"
HASH_RULE: Final[str] = "logical_integer_vector_fixed_width_hex_lf"

# Revision J minimum widths.
W_Qw: Final[int] = 16
W_tw: Final[int] = 17
W_u: Final[int] = 27
W_fft: Final[int] = 28
W_fft_pre: Final[int] = 29
W_can_pre: Final[int] = 29
W_can: Final[int] = 28
W_mag2: Final[int] = 56
W_ifft: Final[int] = 36
W_z: Final[int] = 36
W_ola: Final[int] = 37

UNIQUE_BINS: Final[int] = (L // 2) + 1
ELIGIBLE_UNIQUE_BINS: Final[int] = UNIQUE_BINS - PROTECT_DC_DEFAULT - PROTECT_NYQ_DEFAULT

COEFFICIENT_ROWS: Final[dict[str, int]] = {
    "window_qw": L,
    "twiddle_re": L,
    "twiddle_im": L,
    "twiddle_inv_re": L,
    "twiddle_inv_im": L,
}

COEFFICIENT_MEMH: Final[dict[str, dict[str, int | bool | str]]] = {
    "window_qw": {
        "file": "window_qw.memh",
        "rows": L,
        "width_bits": W_Qw,
        "signed": False,
        "q_format": "Q0.15_unsigned_endpoint_one",
    },
    "twiddle_re": {
        "file": "twiddle_re.memh",
        "rows": L,
        "width_bits": W_tw,
        "signed": True,
        "q_format": "Q1.15_signed_endpoint_one",
    },
    "twiddle_im": {
        "file": "twiddle_im.memh",
        "rows": L,
        "width_bits": W_tw,
        "signed": True,
        "q_format": "Q1.15_signed_endpoint_one",
    },
    "twiddle_inv_re": {
        "file": "twiddle_inv_re.memh",
        "rows": L,
        "width_bits": W_tw,
        "signed": True,
        "q_format": "Q1.15_signed_endpoint_one",
    },
    "twiddle_inv_im": {
        "file": "twiddle_inv_im.memh",
        "rows": L,
        "width_bits": W_tw,
        "signed": True,
        "q_format": "Q1.15_signed_endpoint_one",
    },
}

ARTIFACT_DIRECTORIES: Final[dict[str, str]] = {
    "coefficients": "artifacts/coefficients",
    "test_vectors": "artifacts/test_vectors",
    "golden": "artifacts/golden",
    "manifests": "artifacts/manifests",
}

REQUIRED_FRAME_STATS_HEADER: Final[tuple[str, ...]] = (
    "frame_idx",
    "unique_bins",
    "unique_suppressed_bins",
    "eligible_unique_bins",
    "eligible_suppressed_bins",
    "eligible_kept_mag2",
    "eligible_total_mag2",
)

REQUIRED_BIN_STATS_HEADER: Final[tuple[str, ...]] = (
    "frame_idx",
    "bin_idx",
    "real",
    "imag",
    "mag2",
    "eligible",
    "pre_mask",
    "mask",
)

CONFIGURATION_BASE: Final = MappingProxyType(
    {
        "N": N,
        "L": L,
        "P": P,
        "H": H,
        "F": F,
        "G": G,
        "D": D,
        "THR2": THR2_DEFAULT,
        "PROTECT_DC": PROTECT_DC_DEFAULT,
        "PROTECT_NYQ": PROTECT_NYQ_DEFAULT,
    }
)

WIDTHS: Final = MappingProxyType(
    {
        "W_Qw": W_Qw,
        "W_tw": W_tw,
        "W_u": W_u,
        "W_fft": W_fft,
        "W_fft_pre": W_fft_pre,
        "W_can_pre": W_can_pre,
        "W_can": W_can,
        "W_mag2": W_mag2,
        "W_ifft": W_ifft,
        "W_z": W_z,
        "W_ola": W_ola,
    }
)

CONTRACT: Final = MappingProxyType(
    {
        "fft_mode": FFT_MODE,
        "rounding_mode": ROUNDING_MODE,
        "tail_policy": TAIL_POLICY,
        "threshold_mapping": THRESHOLD_MAPPING,
        "memh_encoding": MEMH_ENCODING,
        "hash_rule": HASH_RULE,
    }
)

ARTIFACT_CONTRACT: Final = MappingProxyType(
    {
        "memh_encoding": MEMH_ENCODING,
        "hash_rule": HASH_RULE,
        "coefficient_rows": dict(COEFFICIENT_ROWS),
        "stream_file_names": {
            "x_in": "x_in.memh",
            "y_out": "y_out.memh",
        },
        "statistics_file_names": {
            "frame_stats": "frame_stats.csv",
            "metrics": "metrics.json",
            "bin_stats": "bin_stats.csv",
        },
        "manifest_file_names": {
            "coeff_manifest": "coeff_manifest.json",
            "test_vectors": "test_vectors.json",
            "quality_bounds": "quality_bounds.json",
            "artifact_index": "artifact_index.json",
            "frozen_release_manifest": "frozen_release_manifest.json",
        },
    }
)


@dataclass(frozen=True, slots=True)
class FullTailGeometry:
    """Derived finite-stream geometry for one nonempty input vector."""

    ns: int
    frames: int
    tau_last: int
    ny: int
    bin_stats_rows: int


def require_nonempty_ns(ns: int) -> int:
    """Validate and return a Revision J signoff input length."""

    if not isinstance(ns, int):
        raise TypeError(f"Ns must be an int, got {type(ns).__name__}")
    if ns <= 0:
        raise ValueError("Revision J full_tail signoff requires Ns > 0")
    return ns


def full_tail_nframes(ns: int) -> int:
    """Return Revision J active-window full-tail frame count for ``Ns`` samples."""

    checked_ns = require_nonempty_ns(ns)
    return (checked_ns + L - 2) // H


def full_tail_ny(ns: int) -> int:
    """Return Revision J full-tail emitted output length for ``Ns`` samples."""

    return (full_tail_nframes(ns) * H) + G + L


def full_tail_geometry(ns: int) -> FullTailGeometry:
    """Return all derived full-tail geometry values for ``Ns`` samples."""

    frames = full_tail_nframes(ns)
    tau_last = frames * H
    return FullTailGeometry(
        ns=require_nonempty_ns(ns),
        frames=frames,
        tau_last=tau_last,
        ny=tau_last + G + L,
        bin_stats_rows=frames * UNIQUE_BINS,
    )


def configuration(*, ns: int | None = None, thr2: str = THR2_DEFAULT) -> dict[str, int | str]:
    """Return a schema-compatible configuration dictionary.

    When ``ns`` is provided, vector-specific ``Ns``, ``Ny``, and ``frames`` fields
    are included. ``THR2`` is intentionally a decimal string because it is a
    W_mag2-wide signoff value.
    """

    cfg: dict[str, int | str] = dict(CONFIGURATION_BASE)
    cfg["THR2"] = thr2
    if ns is not None:
        geom = full_tail_geometry(ns)
        cfg.update({"Ns": geom.ns, "Ny": geom.ny, "frames": geom.frames})
    return cfg


def widths() -> dict[str, int]:
    """Return Revision J width configuration as a mutable dictionary copy."""

    return dict(WIDTHS)


def contract() -> dict[str, str]:
    """Return the golden-model artifact contract string fields."""

    return dict(CONTRACT)


def artifact_contract() -> dict[str, Any]:
    """Return the artifact contract block used by core_config.json."""

    return {
        "memh_encoding": MEMH_ENCODING,
        "hash_rule": HASH_RULE,
        "coefficient_rows": dict(COEFFICIENT_ROWS),
        "stream_file_names": {"x_in": "x_in.memh", "y_out": "y_out.memh"},
        "statistics_file_names": {
            "frame_stats": "frame_stats.csv",
            "metrics": "metrics.json",
            "bin_stats": "bin_stats.csv",
        },
        "manifest_file_names": {
            "coeff_manifest": "coeff_manifest.json",
            "test_vectors": "test_vectors.json",
            "quality_bounds": "quality_bounds.json",
            "artifact_index": "artifact_index.json",
            "frozen_release_manifest": "frozen_release_manifest.json",
        },
    }


def artifact_rows_for_vector(ns: int, *, include_bin_stats: bool = False) -> dict[str, int]:
    """Return expected artifact row counts for one vector."""

    geom = full_tail_geometry(ns)
    rows = dict(COEFFICIENT_ROWS)
    rows.update(
        {
            "x_in": geom.ns,
            "y_out": geom.ny,
            "frame_stats_data_rows": geom.frames,
        }
    )
    if include_bin_stats:
        rows["bin_stats_data_rows"] = geom.bin_stats_rows
    return rows


def core_config_payload() -> dict[str, Any]:
    """Return a complete object compatible with core_config.schema.json."""

    return {
        "schema": SCHEMA,
        "spec_revision": SPEC_REVISION,
        "telemetry_revision": TELEMETRY_REVISION,
        "configuration": configuration(),
        "contract": {
            "fft_mode": FFT_MODE,
            "rounding_mode": ROUNDING_MODE,
            "tail_policy": TAIL_POLICY,
            "threshold_mapping": THRESHOLD_MAPPING,
        },
        "widths": widths(),
        "artifact_contract": artifact_contract(),
        "source_modes": {
            "bram_replay": 0,
            "adc_live": 1,
            "audio_wrapper": 2,
            "diagnostic_source": 3,
        },
    }


__all__ = [
    "ARTIFACT_CONTRACT",
    "ARTIFACT_DIRECTORIES",
    "COEFFICIENT_MEMH",
    "COEFFICIENT_ROWS",
    "CONFIGURATION_BASE",
    "CONTRACT",
    "D",
    "ELIGIBLE_UNIQUE_BINS",
    "F",
    "FFT_MODE",
    "FullTailGeometry",
    "G",
    "GENERATOR_VERSION",
    "GOLDEN_MODEL_VERSION",
    "H",
    "HASH_RULE",
    "L",
    "MEMH_ENCODING",
    "N",
    "P",
    "PROTECT_DC_DEFAULT",
    "PROTECT_NYQ_DEFAULT",
    "REQUIRED_BIN_STATS_HEADER",
    "REQUIRED_FRAME_STATS_HEADER",
    "ROUNDING_MODE",
    "SCHEMA",
    "SPEC_REVISION",
    "TAIL_POLICY",
    "TELEMETRY_REVISION",
    "THR2_DEFAULT",
    "THRESHOLD_MAPPING",
    "UNIQUE_BINS",
    "WIDTHS",
    "W_Qw",
    "W_can",
    "W_can_pre",
    "W_fft",
    "W_fft_pre",
    "W_ifft",
    "W_mag2",
    "W_ola",
    "W_tw",
    "W_u",
    "W_z",
    "artifact_contract",
    "artifact_rows_for_vector",
    "configuration",
    "contract",
    "core_config_payload",
    "full_tail_geometry",
    "full_tail_nframes",
    "full_tail_ny",
    "require_nonempty_ns",
    "widths",
]
