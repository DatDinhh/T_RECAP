#!/usr/bin/env python3
"""Run the golden model for every vector and finalize stream hashes in test_vectors.json."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from _trecap_tool_common import (
    BIN_STATS_HEADER,
    FRAME_STATS_HEADER,
    N,
    ZERO_SHA256,
    ToolError,
    canonical_file_hash,
    csv_row_count,
    load_suite_vector_names,
    read_json,
    sha256_file,
    main_wrapper,
    require_vector_name,
    validate_threshold,
    write_json,
)


def default_golden_exe() -> Path:
    candidates = [Path("build/phase2_golden_model"), Path("build_verify/phase2_golden_model")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ToolError("phase2_golden_model executable not found; run `make build` first or pass --golden-exe")


def run_one(exe: Path, vector_root: Path, out_root: Path, item: dict[str, Any]) -> dict[str, Any]:
    name = require_vector_name(str(item["name"]))
    vdir = vector_root / name
    gdir = out_root / name
    thr2 = validate_threshold(item.get("THR2", "0"))
    collect_bin_stats = bool(item.get("requires_bin_stats", False))
    cmd = [
        str(exe),
        "--input",
        str(vdir / "x_in.memh"),
        "--test-vector-dir",
        str(vdir),
        "--golden-dir",
        str(gdir),
        "--vector-name",
        name,
        "--thr2",
        thr2,
    ]
    if collect_bin_stats:
        cmd.append("--collect-bin-stats")
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"golden run failed for {name} with exit code {proc.returncode}")

    config = read_json(vdir / "config.json")
    rows = config.get("artifact_rows", {})
    frame_rows = int(rows["frame_stats_data_rows"])
    csv_row_count(gdir / "frame_stats.csv", FRAME_STATS_HEADER)
    if (gdir / "bin_stats.csv").exists():
        csv_row_count(gdir / "bin_stats.csv", BIN_STATS_HEADER)
    if csv_row_count(gdir / "frame_stats.csv", FRAME_STATS_HEADER) != frame_rows:
        raise RuntimeError(f"frame_stats.csv row count mismatch for {name}")

    updated = dict(item)
    updated["x_in_sha256"] = canonical_file_hash(vdir / "x_in.memh", N, signed=True)
    updated["y_out_sha256"] = canonical_file_hash(gdir / "y_out.memh", N, signed=True)
    updated["config_sha256"] = sha256_file(vdir / "config.json")
    updated["metrics_sha256"] = sha256_file(gdir / "metrics.json")
    updated["frame_stats_sha256"] = sha256_file(gdir / "frame_stats.csv")
    if (gdir / "bin_stats.csv").exists():
        updated["bin_stats_sha256"] = sha256_file(gdir / "bin_stats.csv")
    updated["lifecycle_status"] = "golden_frozen"
    if updated.get("y_out_sha256") == ZERO_SHA256:
        raise RuntimeError(f"golden y_out_sha256 did not finalize for {name}")
    return updated


def run() -> int:
    parser = argparse.ArgumentParser(description="Run all T-RECAP golden vectors")
    parser.add_argument("--vectors", type=Path, default=Path("artifacts/test_vectors"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/golden"))
    parser.add_argument("--golden-exe", type=Path, default=None)
    parser.add_argument(
        "--suite",
        type=Path,
        default=None,
        help="Optional suite config selecting which manifest vectors to run",
    )
    args = parser.parse_args()

    manifest_path = args.vectors / "test_vectors.json"
    manifest = read_json(manifest_path)
    exe = args.golden_exe or default_golden_exe()
    manifest_vectors = list(manifest.get("vectors", []))
    if args.suite is not None:
        wanted = load_suite_vector_names(args.suite)
        by_name = {str(item.get("name")): item for item in manifest_vectors}
        missing = [name for name in wanted if name not in by_name]
        if missing:
            raise ToolError(
                f"suite {args.suite} references missing generated vector(s): {', '.join(missing)}"
            )
        selected = [by_name[name] for name in wanted]
    else:
        selected = manifest_vectors
    updated_selected = [run_one(exe, args.vectors, args.out, item) for item in selected]
    updated_by_name = {str(item["name"]): item for item in updated_selected}
    manifest["vectors"] = [
        updated_by_name.get(str(item.get("name")), item) for item in manifest_vectors
    ]
    write_json(manifest_path, manifest)
    print(f"suite: finalized {len(updated_selected)} vectors in {manifest_path}")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
