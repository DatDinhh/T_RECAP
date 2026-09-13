#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate coefficient, suite, and per-vector plots for generated artifacts."""

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
    parser = argparse.ArgumentParser(description="Plot all generated T-RECAP golden artifacts")
    parser.add_argument("--artifacts", default="artifacts", help="Artifact tree root")
    parser.add_argument("--out", default="out/plots", help="Output directory for PNG/CSV/JSON files")
    parser.add_argument("--max-samples", type=int, default=2048, help="Maximum samples shown in time-domain plots")
    parser.add_argument("--summary-only", action="store_true", help="Generate suite summaries but skip per-vector plots")
    parser.add_argument("--skip-coefficients", action="store_true", help="Do not plot coefficient ROM artifacts")
    return parser


def main(argv: list[str] | None = None) -> int:
    _bootstrap_repo_imports()
    from trecap_golden.plots.coefficient_plots import plot_coefficients
    from trecap_golden.plots.suite_plots import plot_suite_artifacts

    args = build_argparser().parse_args(argv)
    paths = []
    if not args.skip_coefficients:
        paths.extend(plot_coefficients(args.artifacts, args.out))
    paths.extend(
        plot_suite_artifacts(
            args.artifacts,
            args.out,
            max_samples=args.max_samples,
            per_vector=not args.summary_only,
        )
    )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
