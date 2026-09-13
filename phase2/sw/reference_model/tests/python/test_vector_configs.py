# SPDX-License-Identifier: MIT
"""Tests for reviewed vector and suite configs under configs/."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from _trecap_tool_common import (  # noqa: E402
    ROUNDING_MODE,
    TAIL_POLICY,
    ToolError,
    filter_specs_by_suite,
    load_suite_vector_names,
    load_vector_specs,
)

SUITE_DIR = REPO / "configs" / "suites"
VECTOR_DIR = REPO / "configs" / "vectors"

REQUIRED_VECTOR_FILES = {
    "zero_Ns4096_thr0.json",
    "no_suppression_multitone_thr0.json",
    "impulse_step.json",
    "exact_bin_tone_sweep.json",
    "off_bin_tone_sweep.json",
    "near_threshold_multitone.json",
    "noise_only_xorshift32.json",
    "high_amplitude_headroom.json",
    "short_finite_stream.json",
}
REQUIRED_SUITE_FILES = {
    "smoke.json",
    "signoff_minimal.json",
    "signoff_full.json",
    "debug_near_threshold.json",
}
REQUIRED_SIGNOFF_CLASSES = {
    "zero_input",
    "no_suppression_thr2_zero",
    "impulse",
    "step",
    "exact_bin_tone",
    "off_bin_tone",
    "near_threshold_multitone",
    "noise_only_stream",
    "high_amplitude_headroom",
    "short_finite_stream",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def configured_vectors() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(VECTOR_DIR.glob("*.json")):
        obj = read_json(path)
        assert obj["schema"] == "trecap_phase2_vector_bundle_v1"
        assert obj["bundle_name"] == path.stem
        assert obj["spec_revision"] == "core_rev_j"
        assert obj["generator_version"] == "phase2_generators_revision_j"
        assert obj["tail_policy"] == TAIL_POLICY
        assert obj["rounding"] == ROUNDING_MODE
        assert obj["threshold_mapping"] == "raw_thr2"
        assert obj["default_protection"] == {"PROTECT_DC": 1, "PROTECT_NYQ": 0}
        for item in obj["vectors"]:
            assert item["name"] not in out
            out[item["name"]] = item
    return out


def test_required_vector_bundle_files_exist() -> None:
    assert {path.name for path in VECTOR_DIR.glob("*.json")} == REQUIRED_VECTOR_FILES


def test_vector_bundles_have_stable_signoff_fields() -> None:
    vectors = configured_vectors()
    assert vectors
    for name, item in vectors.items():
        assert name
        assert isinstance(item["Ns"], int) and item["Ns"] > 0
        assert str(item["THR2"]).isdigit()
        assert item.get("PROTECT_DC", 1) in (0, 1)
        assert item.get("PROTECT_NYQ", 0) in (0, 1)
        assert item.get("tail_policy", TAIL_POLICY) == TAIL_POLICY
        assert item.get("rounding", ROUNDING_MODE) == ROUNDING_MODE
        assert isinstance(item["parameters"], dict)
        assert "x_in_sha256" not in item
        assert "y_out_sha256" not in item


def test_load_vector_specs_rejects_duplicate_names(tmp_path: Path) -> None:
    base = {
        "schema": "trecap_phase2_vector_bundle_v1",
        "bundle_name": "dup",
        "spec_revision": "core_rev_j",
        "generator_version": "phase2_generators_revision_j",
        "tail_policy": TAIL_POLICY,
        "rounding": ROUNDING_MODE,
        "threshold_mapping": "raw_thr2",
        "default_protection": {"PROTECT_DC": 1, "PROTECT_NYQ": 0},
        "vectors": [
            {"name": "duplicate", "Ns": 8, "generator": "constant", "parameters": {}, "THR2": "0"}
        ],
    }
    for stem in ("dup", "other"):
        obj = dict(base)
        obj["bundle_name"] = stem
        (tmp_path / f"{stem}.json").write_text(json.dumps(obj), encoding="utf-8")
    try:
        load_vector_specs(tmp_path)
    except ToolError as exc:
        assert "duplicate vector config" in str(exc)
        return
    raise AssertionError("duplicate vector config was accepted")


def test_suite_files_exist_and_do_not_collide_with_vector_manifest_shape() -> None:
    assert {path.name for path in SUITE_DIR.glob("*.json")} == REQUIRED_SUITE_FILES
    for path in sorted(SUITE_DIR.glob("*.json")):
        obj = read_json(path)
        assert obj["schema"] == "trecap_phase2_suite_config_v1"
        assert obj["suite_name"] == path.stem
        assert "vectors" not in obj
        names = [item["name"] for item in obj["vector_selection"]]
        assert names
        assert len(names) == len(set(names))


def test_suite_references_are_not_dangling_and_preserve_order() -> None:
    specs = load_vector_specs(VECTOR_DIR)
    vector_names = {spec.name for spec in specs}
    for path in sorted(SUITE_DIR.glob("*.json")):
        wanted = load_suite_vector_names(path)
        assert set(wanted) <= vector_names
        assert [spec.name for spec in filter_specs_by_suite(specs, path)] == wanted


def test_signoff_suites_cover_required_classes() -> None:
    for filename in ("signoff_minimal.json", "signoff_full.json"):
        suite = read_json(SUITE_DIR / filename)
        selected = {item["class"] for item in suite["vector_selection"]}
        declared = set(suite["required_class_coverage"])
        assert REQUIRED_SIGNOFF_CLASSES <= selected
        assert REQUIRED_SIGNOFF_CLASSES <= declared


def test_suite_file_is_not_accepted_as_vector_config() -> None:
    try:
        load_vector_specs(SUITE_DIR / "smoke.json")
    except ToolError as exc:
        assert "suite selector" in str(exc)
        return
    raise AssertionError("suite config was accepted as vector-config input")
