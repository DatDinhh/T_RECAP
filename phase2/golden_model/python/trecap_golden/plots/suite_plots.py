# SPDX-License-Identifier: MIT
"""Suite-level plots for generated T-RECAP golden artifacts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

from trecap_golden.artifacts.manifests import discover_vector_artifacts, read_json

from .vector_plots import _import_pyplot, _safe_ratio, plot_vector_artifacts


def _metrics_record(artifacts: Path, name: str) -> dict[str, Any]:
    metrics = read_json(artifacts / "golden" / name / "metrics.json")
    suppression = metrics.get("suppression_totals", {})
    spectral = metrics.get("spectral_totals", {})
    errors = metrics.get("time_domain_errors", {})
    config = metrics.get("configuration", {})
    return {
        "name": name,
        "Ns": int(config.get("Ns", 0)),
        "Ny": int(config.get("Ny", 0)),
        "frames": int(config.get("frames", 0)),
        "THR2": str(config.get("THR2", "")),
        "eligible_suppression_ratio": _safe_ratio(
            int(suppression.get("eligible_suppressed_bins", 0)),
            int(suppression.get("eligible_unique_bins", 0)),
        ),
        "eligible_kept_mag2_ratio": _safe_ratio(
            int(spectral.get("eligible_kept_mag2", 0)),
            int(spectral.get("eligible_total_mag2", 0)),
        ),
        "sum_abs_err": int(errors.get("sum_abs_err", 0)),
        "sum_sq_err": int(errors.get("sum_sq_err", 0)),
        "max_abs_err": int(errors.get("max_abs_err", 0)),
        "error_sample_count": int(errors.get("error_sample_count", 0)),
    }


def _write_summary_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "name",
        "Ns",
        "Ny",
        "frames",
        "THR2",
        "eligible_suppression_ratio",
        "eligible_kept_mag2_ratio",
        "sum_abs_err",
        "sum_sq_err",
        "max_abs_err",
        "error_sample_count",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def _bar_plot(path: Path, labels: list[str], values: list[float], ylabel: str, title: str) -> Path:
    plt = _import_pyplot()
    x = np.arange(len(labels))
    fig = plt.figure()
    plt.bar(x, values)
    plt.xticks(x, labels, rotation=45, ha="right")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_suite_artifacts(
    artifacts: str | Path,
    out_dir: str | Path,
    *,
    max_samples: int = 2048,
    per_vector: bool = True,
) -> list[Path]:
    """Generate suite summary plots and optional per-vector plots."""

    artifacts_dir = Path(artifacts)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    names = [vec.name for vec in discover_vector_artifacts(artifacts_dir)]
    records = [_metrics_record(artifacts_dir, name) for name in names]
    written: list[Path] = []

    summary_csv = out / "suite_metrics_summary.csv"
    _write_summary_csv(summary_csv, records)
    written.append(summary_csv)

    labels = [record["name"] for record in records]
    written.append(
        _bar_plot(
            out / "suite_suppression_ratio.png",
            labels,
            [record["eligible_suppression_ratio"] if record["eligible_suppression_ratio"] is not None else np.nan for record in records],
            "eligible_suppressed_bins / eligible_unique_bins",
            "Suite eligible suppression ratio",
        )
    )
    written.append(
        _bar_plot(
            out / "suite_kept_mag2_ratio.png",
            labels,
            [record["eligible_kept_mag2_ratio"] if record["eligible_kept_mag2_ratio"] is not None else np.nan for record in records],
            "eligible_kept_mag2 / eligible_total_mag2",
            "Suite kept magnitude-squared ratio",
        )
    )
    written.append(
        _bar_plot(
            out / "suite_max_abs_err.png",
            labels,
            [float(record["max_abs_err"]) for record in records],
            "max_abs_err",
            "Suite maximum absolute time-domain error",
        )
    )
    written.append(
        _bar_plot(
            out / "suite_sum_sq_err.png",
            labels,
            [float(record["sum_sq_err"]) for record in records],
            "sum_sq_err",
            "Suite sum squared time-domain error",
        )
    )

    if per_vector:
        vector_dir = out / "vectors"
        for name in names:
            written.extend(plot_vector_artifacts(artifacts_dir, name, vector_dir, max_samples=max_samples))

    return written


__all__ = ["plot_suite_artifacts"]
