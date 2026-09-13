# SPDX-License-Identifier: MIT
"""Vector-level plots for generated T-RECAP golden artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .artifact_data import VectorPlotData, load_vector_plot_data


def _import_pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "matplotlib is required for plotting. Install it in the active venv with: "
            "python -m pip install matplotlib"
        ) from exc
    return plt


def _safe_ratio(num: int, den: int) -> float | None:
    return None if den == 0 else float(num) / float(den)


def _decimate_indices(length: int, max_points: int) -> np.ndarray:
    if length <= 0:
        return np.asarray([], dtype=np.int64)
    if max_points <= 0 or length <= max_points:
        return np.arange(length, dtype=np.int64)
    return np.linspace(0, length - 1, num=max_points, dtype=np.int64)


def _frame_arrays(data: VectorPlotData) -> dict[str, np.ndarray]:
    rows = data.frame_stats.rows
    frame_idx = np.asarray([row["frame_idx"] for row in rows], dtype=np.int64)
    eligible_unique = np.asarray([row["eligible_unique_bins"] for row in rows], dtype=np.float64)
    eligible_suppressed = np.asarray([row["eligible_suppressed_bins"] for row in rows], dtype=np.float64)
    total_mag2 = np.asarray([row["eligible_total_mag2"] for row in rows], dtype=np.float64)
    kept_mag2 = np.asarray([row["eligible_kept_mag2"] for row in rows], dtype=np.float64)

    suppression_ratio = np.divide(
        eligible_suppressed,
        eligible_unique,
        out=np.full_like(eligible_suppressed, np.nan, dtype=np.float64),
        where=eligible_unique != 0,
    )
    kept_mag2_ratio = np.divide(
        kept_mag2,
        total_mag2,
        out=np.full_like(kept_mag2, np.nan, dtype=np.float64),
        where=total_mag2 != 0,
    )
    return {
        "frame_idx": frame_idx,
        "eligible_suppression_ratio": suppression_ratio,
        "eligible_kept_mag2_ratio": kept_mag2_ratio,
        "eligible_suppressed_bins": eligible_suppressed,
        "eligible_unique_bins": eligible_unique,
        "eligible_kept_mag2": kept_mag2,
        "eligible_total_mag2": total_mag2,
    }


def _metric_summary(data: VectorPlotData) -> dict[str, Any]:
    suppression = data.metrics.get("suppression_totals", {})
    spectral = data.metrics.get("spectral_totals", {})
    errors = data.metrics.get("time_domain_errors", {})
    return {
        "eligible_suppression_ratio": _safe_ratio(
            int(suppression.get("eligible_suppressed_bins", 0)),
            int(suppression.get("eligible_unique_bins", 0)),
        ),
        "eligible_kept_mag2_ratio": _safe_ratio(
            int(spectral.get("eligible_kept_mag2", 0)),
            int(spectral.get("eligible_total_mag2", 0)),
        ),
        "sum_abs_err": str(errors.get("sum_abs_err", "")),
        "sum_sq_err": str(errors.get("sum_sq_err", "")),
        "max_abs_err": str(errors.get("max_abs_err", "")),
        "error_sample_count": str(errors.get("error_sample_count", "")),
    }


def _write_summary(path: Path, data: VectorPlotData, generated_files: list[str]) -> None:
    summary: dict[str, Any] = {
        "schema": "trecap_phase2_plot_summary_v1",
        "vector": data.name,
        "Ns": data.ns,
        "Ny": data.ny,
        "frames": data.frames,
        "D": data.delay,
        "THR2": data.threshold,
        "plots": generated_files,
        "metrics": _metric_summary(data),
    }
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def _bin_matrices(data: VectorPlotData) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    if data.bin_stats is None or not data.bin_stats.rows:
        return None
    frames = data.frames
    unique_bins = max(row["bin_idx"] for row in data.bin_stats.rows) + 1
    mag2 = np.full((frames, unique_bins), np.nan, dtype=np.float64)
    mask = np.zeros((frames, unique_bins), dtype=np.float64)
    pre_mask = np.zeros((frames, unique_bins), dtype=np.float64)
    for row in data.bin_stats.rows:
        frame = row["frame_idx"]
        bin_idx = row["bin_idx"]
        mag2[frame, bin_idx] = float(row["mag2"])
        mask[frame, bin_idx] = float(row["mask"])
        pre_mask[frame, bin_idx] = float(row["pre_mask"])
    return mag2, mask, pre_mask


def plot_vector_artifacts(
    artifacts: str | Path,
    vector_name: str,
    out_dir: str | Path,
    *,
    max_samples: int = 2048,
    include_bin_stats: bool = True,
) -> list[Path]:
    """Generate PNG plots for one vector and return written paths."""

    data = load_vector_plot_data(artifacts, vector_name)
    out = Path(out_dir) / vector_name
    out.mkdir(parents=True, exist_ok=True)
    plt = _import_pyplot()

    written: list[Path] = []
    idx = _decimate_indices(data.ny, max_samples)

    # 1) Delayed input vs reconstructed output.  Phase 2 must compare x[n-D], not raw x[n].
    fig = plt.figure()
    plt.plot(idx, data.x_delayed[idx], label="x[n-D] delayed input")
    plt.plot(idx, data.y_out[idx], label="y[n] golden output")
    plt.title(f"{data.name}: delayed input vs golden output")
    plt.xlabel("output sample index n")
    plt.ylabel("signed sample")
    plt.grid(True)
    plt.legend()
    p = out / "waveform_overlay.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    # 2) Time-domain error.
    fig = plt.figure()
    plt.plot(idx, data.error[idx], label="x[n-D] - y[n]")
    plt.title(f"{data.name}: time-domain error")
    plt.xlabel("output sample index n")
    plt.ylabel("signed error")
    plt.grid(True)
    plt.legend()
    p = out / "error_timeseries.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    # 3) Error histogram over the full emitted stream.
    fig = plt.figure()
    plt.hist(data.error, bins=51)
    plt.title(f"{data.name}: error histogram")
    plt.xlabel("x[n-D] - y[n]")
    plt.ylabel("count")
    plt.grid(True)
    p = out / "error_histogram.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    frame = _frame_arrays(data)

    # 4) Per-frame eligible suppression ratio.
    fig = plt.figure()
    plt.plot(frame["frame_idx"], frame["eligible_suppression_ratio"], marker="o")
    plt.title(f"{data.name}: eligible suppression ratio per frame")
    plt.xlabel("frame index")
    plt.ylabel("eligible_suppressed_bins / eligible_unique_bins")
    plt.grid(True)
    p = out / "frame_suppression_ratio.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    # 5) Per-frame kept magnitude-squared ratio.  NaN means eligible_total_mag2 == 0.
    fig = plt.figure()
    plt.plot(frame["frame_idx"], frame["eligible_kept_mag2_ratio"], marker="o")
    plt.title(f"{data.name}: kept magnitude-squared ratio per frame")
    plt.xlabel("frame index")
    plt.ylabel("eligible_kept_mag2 / eligible_total_mag2")
    plt.grid(True)
    p = out / "frame_kept_mag2_ratio.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    # 6) Optional bin-level plots for vectors that generated bin_stats.csv.
    matrices = _bin_matrices(data) if include_bin_stats else None
    if matrices is not None:
        mag2, mask, pre_mask = matrices

        fig = plt.figure()
        plt.imshow(np.log10(np.maximum(mag2, 1.0)), aspect="auto", interpolation="nearest", origin="lower")
        plt.title(f"{data.name}: log10(mag2) unique-bin spectrogram")
        plt.xlabel("unique bin index")
        plt.ylabel("frame index")
        plt.colorbar(label="log10(mag2)")
        p = out / "mag2_spectrogram.png"
        fig.tight_layout()
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p)

        fig = plt.figure()
        plt.imshow(mask, aspect="auto", interpolation="nearest", origin="lower")
        plt.title(f"{data.name}: final mask heatmap")
        plt.xlabel("unique bin index")
        plt.ylabel("frame index")
        plt.colorbar(label="mask")
        p = out / "mask_heatmap.png"
        fig.tight_layout()
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p)

        fig = plt.figure()
        plt.imshow(pre_mask, aspect="auto", interpolation="nearest", origin="lower")
        plt.title(f"{data.name}: pre-protection mask heatmap")
        plt.xlabel("unique bin index")
        plt.ylabel("frame index")
        plt.colorbar(label="pre_mask")
        p = out / "pre_mask_heatmap.png"
        fig.tight_layout()
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p)

    _write_summary(out / "plot_summary.json", data, [path.name for path in written])
    written.append(out / "plot_summary.json")
    return written


__all__ = ["plot_vector_artifacts"]
