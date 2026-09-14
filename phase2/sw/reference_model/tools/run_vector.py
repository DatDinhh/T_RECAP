#!/usr/bin/env python3
"""Run one fixed-point reference vector without changing its input bundle."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from _trecap_tool_common import ToolError, main_wrapper
from _runner_common import (
    PACKAGE_ROOT, default_reference_exe, ensure_separate_output,
    load_vector_config, run_command,
)


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=PACKAGE_ROOT / "runs/reference_outputs")
    parser.add_argument("--output-dir", "--golden-dir", dest="output_dir", type=Path)
    parser.add_argument("--reference-exe", "--golden-exe", dest="reference_exe", type=Path)
    parser.add_argument("--coeff-dir", type=Path, default=PACKAGE_ROOT / "artifacts/coefficients")
    parser.add_argument("--vector-name")
    parser.add_argument("--thr2")
    parser.add_argument("--collect-bin-stats", action="store_true")
    args = parser.parse_args()
    config = load_vector_config(args.vector_dir)
    name = config["vector_name"]
    if args.vector_name is not None and args.vector_name != name:
        raise ToolError("--vector-name must agree with config.json")
    output = args.output_dir or args.out / name
    ensure_separate_output(output, args.vector_dir, args.coeff_dir)
    command = run_command(args.reference_exe or default_reference_exe(), args.vector_dir,
                          output, args.coeff_dir, threshold=args.thr2,
                          collect=args.collect_bin_stats)
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise ToolError(f"reference run failed with exit code {result.returncode}")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
