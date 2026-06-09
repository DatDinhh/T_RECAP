#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate suite-level and per-vector plots for T-RECAP generated artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_repo_imports() -> None:
    repo = Path(__file__).resolve().parents[1]
    python_dir = repo / "python"
    if str(python_dir) not in sys.path:
        sys.path.insert(0, str(python_dir))


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plot a T-RECAP golden artifact suite")
    parser.add_argument("--artifacts", default="artifacts", help="Artifact tree root")
    parser.add_argument("--out", default="out/plots", help="Output directory for PNG/CSV files")
    parser.add_argument("--max-samples", type=int, default=2048, help="Maximum samples shown in per-vector time plots")
    parser.add_argument("--summary-only", action="store_true", help="Generate only suite-level summary plots")
    return parser


def main(argv: list[str] | None = None) -> int:
    _bootstrap_repo_imports()
    from trecap_golden.plots.suite_plots import plot_suite_artifacts

    args = build_argparser().parse_args(argv)
    paths = plot_suite_artifacts(
        args.artifacts,
        args.out,
        max_samples=args.max_samples,
        per_vector=not args.summary_only,
    )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
