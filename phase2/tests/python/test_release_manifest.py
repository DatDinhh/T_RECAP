# SPDX-License-Identifier: MIT
"""Tests for reviewed release configs and generated release manifests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from trecap_golden.artifacts.memh import contract_for_kind, write_memh
from trecap_golden.contracts.schema_validate import validate_file
from trecap_golden.generated import trecap_config as cfg

REPO = Path(__file__).resolve().parents[2]
RELEASE_DIR = REPO / "configs" / "releases"
ZERO_SHA = "0" * 64


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_tool(args: list[str]) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "python")
    subprocess.run([sys.executable, *args], cwd=REPO, env=env, text=True, check=True)


def metric_payload(vector_name: str, ns: int) -> dict[str, Any]:
    geom = cfg.full_tail_geometry(ns)
    unique_bins = geom.frames * cfg.UNIQUE_BINS
    eligible_bins = geom.frames * (cfg.ELIGIBLE_UNIQUE_BINS)
    return {
        "schema": "trecap_phase2_metrics_v1",
        "vector_name": vector_name,
        "configuration": {
            "N": cfg.N,
            "L": cfg.L,
            "P": cfg.P,
            "H": cfg.H,
            "F": cfg.F,
            "G": cfg.G,
            "D": cfg.D,
            "Ns": ns,
            "Ny": geom.ny,
            "frames": geom.frames,
            "THR2": "0",
            "PROTECT_DC": 1,
            "PROTECT_NYQ": 0,
        },
        "contract": {
            "fft_mode": "custom_radix2_dit_bitrev_in_natural_out",
            "rounding_mode": "round_nearest_ties_away_from_zero",
            "tail_policy": "full_tail",
            "threshold_mapping": "raw_thr2",
            "memh_encoding": "fixed_width_lowercase_hex_lf",
            "hash_rule": "logical_integer_vector_fixed_width_hex_lf",
        },
        "widths": cfg.widths(),
        "hashes": {
            "window_qw_sha256": ZERO_SHA,
            "twiddle_re_sha256": ZERO_SHA,
            "twiddle_im_sha256": ZERO_SHA,
            "twiddle_inv_re_sha256": ZERO_SHA,
            "twiddle_inv_im_sha256": ZERO_SHA,
        },
        "stream_hashes": {"x_in_sha256": ZERO_SHA, "y_out_sha256": ZERO_SHA},
        "suppression_totals": {
            "unique_bins": str(unique_bins),
            "unique_suppressed_bins": "0",
            "eligible_unique_bins": str(eligible_bins),
            "eligible_suppressed_bins": "0",
        },
        "spectral_totals": {"eligible_kept_mag2": "0", "eligible_total_mag2": "0"},
        "time_domain_errors": {
            "sum_abs_err": "0",
            "sum_sq_err": "0",
            "max_abs_err": "0",
            "error_sample_count": str(geom.ny),
        },
    }


def write_minimal_golden_outputs(artifacts: Path) -> None:
    manifest = read_json(artifacts / "test_vectors" / "test_vectors.json")
    for item in manifest["vectors"]:
        name = item["name"]
        ns = int(item["Ns"])
        geom = cfg.full_tail_geometry(ns)
        out_dir = artifacts / "golden" / name
        out_dir.mkdir(parents=True, exist_ok=True)
        write_memh(out_dir / "y_out.memh", [0] * geom.ny, contract_for_kind("y_out", rows=geom.ny))
        rows = [
            {
                "frame_idx": frame,
                "unique_bins": cfg.UNIQUE_BINS,
                "unique_suppressed_bins": 0,
                "eligible_unique_bins": cfg.UNIQUE_BINS - 1,
                "eligible_suppressed_bins": 0,
                "eligible_kept_mag2": 0,
                "eligible_total_mag2": 0,
            }
            for frame in range(geom.frames)
        ]
        frame_stats = out_dir / "frame_stats.csv"
        frame_stats.write_text(
            "frame_idx,unique_bins,unique_suppressed_bins,eligible_unique_bins,"
            "eligible_suppressed_bins,eligible_kept_mag2,eligible_total_mag2\n"
            + "".join(
                f"{row['frame_idx']},{row['unique_bins']},{row['unique_suppressed_bins']},"
                f"{row['eligible_unique_bins']},{row['eligible_suppressed_bins']},"
                f"{row['eligible_kept_mag2']},{row['eligible_total_mag2']}\n"
                for row in rows
            ),
            encoding="utf-8",
            newline="\n",
        )
        (out_dir / "metrics.json").write_text(
            json.dumps(metric_payload(name, ns), indent=2) + "\n",
            encoding="utf-8",
        )


def prepare_temp_artifacts(tmp_path: Path) -> Path:
    artifacts = tmp_path / "artifacts"
    coeff_dir = artifacts / "coefficients"
    vector_dir = artifacts / "test_vectors"
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "release_vector.json").write_text(
        json.dumps(
            {
                "name": "release_constant",
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
    write_minimal_golden_outputs(artifacts)
    (artifacts / "manifests").mkdir(parents=True, exist_ok=True)
    run_tool(
        [
            "tools/make_quality_bounds.py",
            "--artifacts",
            str(artifacts),
            "--out",
            str(artifacts / "manifests" / "quality_bounds.json"),
        ]
    )
    return artifacts


def test_release_recipe_files_are_reviewed_inputs_not_generated_manifests() -> None:
    assert {path.name for path in RELEASE_DIR.glob("*.json")} == {
        "phase2_revJ_dev.json",
        "phase2_revJ_signoff.json",
    }
    for path in sorted(RELEASE_DIR.glob("*.json")):
        obj = read_json(path)
        assert obj["schema"] == "trecap_phase2_release_config_v1"
        assert obj["release_config_name"] == path.stem
        assert obj["spec_revision"] == "core_rev_j"
        assert obj["telemetry_revision"] == "telemetry_rev_g"
        assert obj["suite_config"].startswith("configs/suites/")
        assert obj["artifact_root"] == "artifacts"
        assert isinstance(obj["reproduction"]["commands"], list)
        assert obj["reproduction"]["commands"]


def test_signoff_release_config_declares_external_rtl_and_bram_gates() -> None:
    signoff = read_json(RELEASE_DIR / "phase2_revJ_signoff.json")
    external = signoff["required_gates"]["external_signoff"]
    names = {item["name"] for item in external}
    assert {
        "rtl_simulation_matches_y_out_memh",
        "rtl_simulation_matches_frame_stats_csv",
        "rtl_simulation_matches_metrics_json",
        "bram_replay_board_matches_mandatory_artifacts",
        "overflow_or_wrap_flags_remain_deasserted",
    } <= names
    assert all(item["required"] is True for item in external)
    assert all(item["status"] == "required_outside_golden_repo" for item in external)


def test_freeze_release_generates_schema_valid_manifest_from_recipe(tmp_path: Path) -> None:
    artifacts = prepare_temp_artifacts(tmp_path)
    out = tmp_path / "frozen_release_manifest.json"

    run_tool(
        [
            "tools/freeze_release.py",
            "--release-config",
            "configs/releases/phase2_revJ_dev.json",
            "--artifacts",
            str(artifacts),
            "--out",
            str(out),
            "--skip-check",
        ]
    )

    manifest = read_json(out)
    recipe = read_json(RELEASE_DIR / "phase2_revJ_dev.json")
    assert manifest["release_name"] == recipe["release_name"]
    assert manifest["release_version"] == recipe["release_version"]
    assert manifest["reproduction"]["commands"] == recipe["reproduction"]["commands"]
    assert validate_file(out).ok
    assert validate_file(artifacts / "manifests" / "artifact_index.json").ok
    assert validate_file(artifacts / "manifests" / "quality_bounds.json").ok
