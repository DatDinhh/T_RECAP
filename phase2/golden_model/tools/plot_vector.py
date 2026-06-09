#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate plots for one T-RECAP generated golden vector artifact."""

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
    parser = argparse.ArgumentParser(description="Plot one T-RECAP golden vector artifact")
    parser.add_argument("--artifacts", default="artifacts", help="Artifact tree root")
    parser.add_argument("--vector", required=True, help="Vector name from artifacts/test_vectors/test_vectors.json")
    parser.add_argument("--out", default="out/plots", help="Output directory for PNG/JSON files")
    parser.add_argument("--max-samples", type=int, default=2048, help="Maximum samples shown in time-domain plots")
    parser.add_argument("--no-bin-stats", action="store_true", help="Skip bin_stats heatmaps even when present")
    return parser


def main(argv: list[str] | None = None) -> int:
    _bootstrap_repo_imports()
    from trecap_golden.plots.vector_plots import plot_vector_artifacts

    args = build_argparser().parse_args(argv)
    paths = plot_vector_artifacts(
        args.artifacts,
        args.vector,
        args.out,
        max_samples=args.max_samples,
        include_bin_stats=not args.no_bin_stats,
    )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
