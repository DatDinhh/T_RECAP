#!/usr/bin/env python3
"""Check canonical memh, CSV, JSON schema, hash, and row-count contracts."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _trecap_tool_common import (
    BIN_STATS_HEADER,
    FRAME_STATS_HEADER,
    L,
    N,
    UNIQUE_BINS,
    W_QW,
    W_TW,
    ToolError,
    canonical_file_hash,
    coefficient_hashes_from_artifacts,
    csv_row_count,
    read_json,
    main_wrapper,
)


def validate_with_schema(instance: Any, schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    if not schema_path.exists():
        return
    schema = read_json(schema_path)
    try:
        jsonschema.Draft202012Validator(schema).validate(instance)
    except jsonschema.ValidationError as exc:
        raise ToolError(f"schema validation failed for {schema_path}: {exc.message}") from exc


def check_equal(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ToolError(f"{label}: expected {expected!r}, got {actual!r}")


def check_coefficients(root: Path, schema_root: Path) -> dict[str, str]:
    coeff_dir = root / "coefficients"
    manifest_path = coeff_dir / "coeff_manifest.json"
    if not manifest_path.exists():
        raise ToolError(f"missing coefficient manifest: {manifest_path}; run tools/gen_coeffs.py")
    manifest = read_json(manifest_path)
    validate_with_schema(manifest, schema_root / "coeff_manifest.schema.json")
    hashes = coefficient_hashes_from_artifacts(coeff_dir)
    manifest_hashes = manifest.get("hashes", {})
    for key, value in hashes.items():
        check_equal(f"coeff hash {key}", value, manifest_hashes.get(key))
    expected_files = {
        "window_qw.memh": (W_QW, False, L, hashes["window_qw_sha256"]),
        "twiddle_re.memh": (W_TW, True, L, hashes["twiddle_re_sha256"]),
        "twiddle_im.memh": (W_TW, True, L, hashes["twiddle_im_sha256"]),
        "twiddle_inv_re.memh": (W_TW, True, L, hashes["twiddle_inv_re_sha256"]),
        "twiddle_inv_im.memh": (W_TW, True, L, hashes["twiddle_inv_im_sha256"]),
    }
    for name, (width, signed, rows, expected_hash) in expected_files.items():
        path = coeff_dir / name
        values_hash = canonical_file_hash(path, width, signed)
        check_equal(f"{name} sha256", values_hash, expected_hash)
        line_count = len(path.read_text(encoding="ascii").splitlines())
        check_equal(f"{name} line count", line_count, rows)
    return hashes


def check_vectors(root: Path, schema_root: Path, coeff_hashes: dict[str, str]) -> None:
    vectors_root = root / "test_vectors"
    golden_root = root / "golden"
    manifest_path = vectors_root / "test_vectors.json"
    if not manifest_path.exists():
        raise ToolError(f"missing vector manifest: {manifest_path}; run tools/gen_vectors.py and tools/run_suite.py")
    manifest = read_json(manifest_path)
    validate_with_schema(manifest, schema_root / "test_vectors.schema.json")
    for item in manifest.get("vectors", []):
        name = item["name"]
        vdir = vectors_root / name
        gdir = golden_root / name
        config_path = vdir / "config.json"
        metrics_path = gdir / "metrics.json"
        config = read_json(config_path)
        metrics = read_json(metrics_path)
        validate_with_schema(config, schema_root / "vector_config.schema.json")
        validate_with_schema(metrics, schema_root / "metrics.schema.json")
        rows = config["artifact_rows"]
        ns = int(rows["x_in"])
        ny = int(rows["y_out"])
        frames = int(rows["frame_stats_data_rows"])
        x_hash = canonical_file_hash(vdir / "x_in.memh", N, signed=True)
        y_hash = canonical_file_hash(gdir / "y_out.memh", N, signed=True)
        check_equal(f"{name} x_in_sha256 manifest", x_hash, item.get("x_in_sha256"))
        check_equal(f"{name} y_out_sha256 manifest", y_hash, item.get("y_out_sha256"))
        check_equal(f"{name} x_in_sha256 config", x_hash, config["stream_hashes"]["x_in_sha256"])
        check_equal(f"{name} y_out_sha256 config", y_hash, config["stream_hashes"]["y_out_sha256"])
        check_equal(f"{name} y_out_sha256 metrics", y_hash, metrics["stream_hashes"]["y_out_sha256"])
        check_equal(f"{name} x_in lines", len((vdir / "x_in.memh").read_text(encoding="ascii").splitlines()), ns)
        check_equal(f"{name} y_out lines", len((gdir / "y_out.memh").read_text(encoding="ascii").splitlines()), ny)
        check_equal(f"{name} frame_stats rows", csv_row_count(gdir / "frame_stats.csv", FRAME_STATS_HEADER), frames)
        if "bin_stats_data_rows" in rows or item.get("requires_bin_stats", False):
            check_equal(
                f"{name} bin_stats rows",
                csv_row_count(gdir / "bin_stats.csv", BIN_STATS_HEADER),
                int(rows.get("bin_stats_data_rows", frames * UNIQUE_BINS)),
            )
        for key, value in coeff_hashes.items():
            check_equal(f"{name} coeff hash {key} config", config["hashes"].get(key), value)
            check_equal(f"{name} coeff hash {key} metrics", metrics["hashes"].get(key), value)


def run() -> int:
    parser = argparse.ArgumentParser(description="Check T-RECAP Phase 2 artifacts")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--schemas", type=Path, default=Path("spec/schemas"))
    args = parser.parse_args()

    coeff_hashes = check_coefficients(args.artifacts, args.schemas)
    check_vectors(args.artifacts, args.schemas, coeff_hashes)
    optional_manifests = {
        "quality_bounds.json": "quality_bounds.schema.json",
        "artifact_index.json": "artifact_index.schema.json",
        "frozen_release_manifest.json": "frozen_release_manifest.schema.json",
    }
    for manifest_name, schema_name in optional_manifests.items():
        path = args.artifacts / "manifests" / manifest_name
        if path.exists():
            validate_with_schema(read_json(path), args.schemas / schema_name)
    print("artifact_check: OK")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
