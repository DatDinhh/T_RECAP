# SPDX-License-Identifier: MIT
"""Tests for frozen Revision J input-vector generators."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from trecap_golden.artifacts.memh import contract_for_kind, read_memh
from trecap_golden.generators import GeneratorError, SUPPORTED_GENERATORS, generate_samples

REPO = Path(__file__).resolve().parents[2]


def test_supported_generator_vocabulary_is_frozen() -> None:
    assert SUPPORTED_GENERATORS == (
        "constant",
        "impulse",
        "step",
        "sine",
        "exact_bin_sine",
        "cosine",
        "exact_bin_cosine",
        "multitone_sine_sum",
        "uniform_noise_xorshift32",
    )


def test_basic_generators_are_deterministic_and_saturating() -> None:
    assert generate_samples("constant", 4, {"value": 5000}) == (2047, 2047, 2047, 2047)
    assert generate_samples("impulse", 6, {"index": 2, "amplitude": -5000}) == (
        0,
        0,
        -2048,
        0,
        0,
        0,
    )
    assert generate_samples("step", 5, {"index": 3, "amplitude": 9}) == (0, 0, 0, 9, 9)


def test_trigonometric_generators_have_stable_known_sequences() -> None:
    assert generate_samples("sine", 8, {"amplitude": 10, "f_num": 1, "f_den": 4}) == (
        0,
        10,
        0,
        -10,
        0,
        10,
        0,
        -10,
    )
    assert generate_samples("cosine", 8, {"amplitude": 10, "f_num": 1, "f_den": 4}) == (
        10,
        0,
        -10,
        0,
        10,
        0,
        -10,
        0,
    )
    assert generate_samples("exact_bin_cosine", 8, {"amplitude": 7, "bin": 0}) == (7,) * 8
    assert generate_samples("exact_bin_sine", 8, {"amplitude": 7, "bin": 0}) == (0,) * 8


def test_xorshift32_generator_has_known_sequence_and_rejects_bad_parameters() -> None:
    assert generate_samples("uniform_noise_xorshift32", 8, {"seed": 1, "B": 4}) == (
        -7,
        -7,
        -3,
        7,
        -7,
        -8,
        2,
        -6,
    )
    with pytest.raises(GeneratorError, match="seed must be nonzero"):
        generate_samples("uniform_noise_xorshift32", 8, {"seed": 0, "B": 4})
    with pytest.raises(GeneratorError, match="1 <= B <= 32"):
        generate_samples("uniform_noise_xorshift32", 8, {"seed": 1, "B": 0})


def test_generator_validation_rejects_ambiguous_or_legacy_inputs() -> None:
    with pytest.raises(GeneratorError, match="phase_rad must be a decimal string"):
        generate_samples("sine", 4, {"amplitude": 1, "f_num": 1, "f_den": 8, "phase_rad": "1/2"})
    with pytest.raises(GeneratorError, match="f_den must be positive"):
        generate_samples("cosine", 4, {"amplitude": 1, "f_num": 1, "f_den": 0})
    with pytest.raises(GeneratorError, match="0 <= k <= L/2"):
        generate_samples("exact_bin_cosine", 4, {"amplitude": 1, "bin": 129})
    with pytest.raises(GeneratorError, match="unsupported generator"):
        generate_samples("haar_phase1", 4, {})


def test_gen_vectors_cli_delegates_to_package_generators(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    out = tmp_path / "test_vectors"
    configs.mkdir()
    (configs / "small_bundle.json").write_text(
        json.dumps(
            {
                "schema": "trecap_phase2_vector_bundle_v1",
                "bundle_name": "small_bundle",
                "spec_revision": "core_rev_j",
                "generator_version": "phase2_generators_revision_j",
                "tail_policy": "full_tail",
                "rounding": "round_nearest_ties_away_from_zero",
                "threshold_mapping": "raw_thr2",
                "default_protection": {"PROTECT_DC": 1, "PROTECT_NYQ": 0},
                "vectors": [
                    {
                        "name": "small_constant",
                        "Ns": 4,
                        "generator": "constant",
                        "parameters": {"value": -2},
                        "THR2": "0",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "python")
    subprocess.run(
        [sys.executable, "tools/gen_vectors.py", "--configs", str(configs), "--out", str(out)],
        cwd=REPO,
        env=env,
        text=True,
        check=True,
    )

    parsed = read_memh(out / "small_constant" / "x_in.memh", contract_for_kind("x_in", rows=4))
    manifest = json.loads((out / "test_vectors.json").read_text(encoding="utf-8"))
    assert parsed.values == generate_samples("constant", 4, {"value": -2})
    assert manifest["vectors"][0]["x_in_sha256"] != "0" * 64
