#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate plots for generated coefficient ROM artifacts."""

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
    parser = argparse.ArgumentParser(description="Plot T-RECAP coefficient ROM artifacts")
    parser.add_argument("--artifacts", default="artifacts", help="Artifact tree root")
    parser.add_argument("--out", default="out/plots", help="Output directory for PNG/JSON files")
    return parser


def main(argv: list[str] | None = None) -> int:
    _bootstrap_repo_imports()
    from trecap_golden.plots.coefficient_plots import plot_coefficients

    args = build_argparser().parse_args(argv)
    paths = plot_coefficients(args.artifacts, args.out)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
