# SPDX-License-Identifier: MIT
"""Tests for JSON Schema loading, inference, and validation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from trecap_golden.contracts.contract_paths import default_paths, normalize_schema_name
from trecap_golden.contracts.schema_loader import load_all_schemas, schema_inventory
from trecap_golden.contracts.schema_validate import infer_schema_name, validate_file, validate_obj
from trecap_golden.generated import trecap_config as cfg

REPO = Path(__file__).resolve().parents[2]


def run_tool(args: list[str], *, cwd: Path = REPO) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "python")
    subprocess.run([sys.executable, *args], cwd=cwd, env=env, text=True, check=True)


def test_schema_inventory_is_complete_and_deterministic() -> None:
    paths = default_paths(REPO)
    records = load_all_schemas(paths)
    assert sorted(records) == [
        "artifact_index",
        "coeff_manifest",
        "core_config",
        "frozen_release_manifest",
        "metrics",
        "quality_bounds",
        "test_vectors",
        "vector_config",
    ]
    inventory = schema_inventory(paths)
    assert [item["name"] for item in inventory] == sorted(records)
    assert all(len(item["sha256"]) == 64 and item["sha256"].islower() for item in inventory)
    assert normalize_schema_name("metrics.json") == "metrics.schema.json"


def test_generated_core_config_payload_validates_against_schema() -> None:
    result = validate_obj(cfg.core_config_payload(), "core_config", paths=default_paths(REPO))
    assert result.ok, result.errors
    assert cfg.full_tail_geometry(4096).frames == 33
    assert cfg.full_tail_geometry(4096).ny == 4608


def test_coeff_manifest_and_vector_config_generated_by_tools_validate(tmp_path: Path) -> None:
    coeff_dir = tmp_path / "artifacts" / "coefficients"
    vector_dir = tmp_path / "artifacts" / "test_vectors"
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "single.json").write_text(
        json.dumps(
            {
                "name": "schema_constant",
                "Ns": 8,
                "generator": "constant",
                "parameters": {"value": 0},
                "THR2": "0",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    run_tool(["tools/gen_coeffs.py", "--out", str(coeff_dir)])
    run_tool(
        [
            "tools/gen_vectors.py",
            "--configs",
            str(config_dir),
            "--coefficients",
            str(coeff_dir),
            "--out",
            str(vector_dir),
        ]
    )

    for path in (
        coeff_dir / "coeff_manifest.json",
        vector_dir / "test_vectors.json",
        vector_dir / "schema_constant" / "config.json",
    ):
        result = validate_file(path, paths=default_paths(REPO))
        assert result.ok, result.errors

    config = json.loads((vector_dir / "schema_constant" / "config.json").read_text(encoding="utf-8"))
    assert infer_schema_name(vector_dir / "schema_constant" / "config.json", config) == "vector_config"


def test_schema_validation_reports_stable_error_path() -> None:
    payload = cfg.core_config_payload()
    payload["configuration"]["N"] = 16
    result = validate_obj(payload, "core_config", paths=default_paths(REPO))
    assert not result.ok
    assert any(issue.path == "$.configuration.N" for issue in result.errors)
    assert any("12 was expected" in issue.message for issue in result.errors)


def test_json_schema_rejects_placeholder_hashes(tmp_path: Path) -> None:
    coeff_dir = tmp_path / "coefficients"
    run_tool(["tools/gen_coeffs.py", "--out", str(coeff_dir)])
    manifest = json.loads((coeff_dir / "coeff_manifest.json").read_text(encoding="utf-8"))
    manifest["hashes"]["window_qw_sha256"] = "<sha256-hex>"

    result = validate_obj(manifest, "coeff_manifest", paths=default_paths(REPO))

    assert not result.ok
    assert any(issue.path == "$.hashes.window_qw_sha256" for issue in result.errors)
