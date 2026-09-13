#!/usr/bin/env python3
"""Run the C++ Phase 2 golden model for exactly one frozen input vector."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from _trecap_tool_common import (
    ToolError,
    read_json,
    main_wrapper,
    require_vector_name,
    validate_threshold,
)


def default_golden_exe() -> Path:
    candidates = [Path("build/phase2_golden_model"), Path("build_verify/phase2_golden_model")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ToolError("phase2_golden_model executable not found; run `make build` first or pass --golden-exe")


def run() -> int:
    parser = argparse.ArgumentParser(description="Run one T-RECAP Phase 2 golden vector")
    parser.add_argument("--vector-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("artifacts/golden"), help="Golden output root")
    parser.add_argument("--golden-dir", type=Path, default=None, help="Exact per-vector golden output directory")
    parser.add_argument("--golden-exe", type=Path, default=None)
    parser.add_argument("--vector-name", default=None)
    parser.add_argument("--thr2", default=None)
    parser.add_argument("--collect-bin-stats", action="store_true")
    args = parser.parse_args()

    vdir = args.vector_dir
    if not (vdir / "x_in.memh").exists():
        raise ToolError(f"missing x_in.memh in {vdir}")
    config = read_json(vdir / "config.json") if (vdir / "config.json").exists() else {}
    name = require_vector_name(args.vector_name or config.get("vector_name") or vdir.name)
    thr2 = validate_threshold(args.thr2 if args.thr2 is not None else config.get("configuration", {}).get("THR2", "0"))
    rows = config.get("artifact_rows", {}) if isinstance(config, dict) else {}
    collect_bin_stats = bool(args.collect_bin_stats or "bin_stats_data_rows" in rows)
    golden_dir = args.golden_dir or (args.out / name)
    exe = args.golden_exe or default_golden_exe()

    cmd = [
        str(exe),
        "--input",
        str(vdir / "x_in.memh"),
        "--test-vector-dir",
        str(vdir),
        "--golden-dir",
        str(golden_dir),
        "--vector-name",
        name,
        "--thr2",
        thr2,
    ]
    if collect_bin_stats:
        cmd.append("--collect-bin-stats")

    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        raise ToolError(f"golden vector run failed with exit code {proc.returncode}: {' '.join(cmd)}")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
