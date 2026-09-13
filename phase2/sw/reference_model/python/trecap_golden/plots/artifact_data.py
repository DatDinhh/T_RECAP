# SPDX-License-Identifier: MIT
"""Data loading for T-RECAP artifact plots.

The loaders here consume the same generated artifacts that the checker consumes:
``x_in.memh``, ``y_out.memh``, ``frame_stats.csv``, ``metrics.json``, and
optional ``bin_stats.csv``.  All stream comparison uses the Phase 2 delayed
reference ``x[n-D]`` rather than raw ``x[n]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from trecap_golden.artifacts.csv_io import CsvReadResult, read_bin_stats, read_frame_stats
from trecap_golden.artifacts.manifests import ManifestError, discover_vector_artifacts, read_json
from trecap_golden.artifacts.memh import MemhContract, contract_for_kind, read_memh
from trecap_golden.generated import trecap_config as cfg


class PlotDataError(ValueError):
    """Raised when plot input artifacts are missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class VectorPlotData:
    """Loaded artifact data for one generated golden vector."""

    name: str
    config: dict[str, Any]
    metrics: dict[str, Any]
    x_in: np.ndarray
    y_out: np.ndarray
    x_delayed: np.ndarray
    error: np.ndarray
    frame_stats: CsvReadResult
    bin_stats: CsvReadResult | None
    vector_root: Path
    golden_root: Path

    @property
    def ns(self) -> int:
        return int(self.config["configuration"]["Ns"])

    @property
    def ny(self) -> int:
        return int(self.config["configuration"]["Ny"])

    @property
    def frames(self) -> int:
        return int(self.config["configuration"]["frames"])

    @property
    def delay(self) -> int:
        return int(self.config["configuration"].get("D", cfg.D))

    @property
    def threshold(self) -> str:
        return str(self.config["configuration"].get("THR2", ""))


@dataclass(frozen=True, slots=True)
class CoefficientPlotData:
    """Loaded generated coefficient ROM artifact data."""

    root: Path
    manifest: dict[str, Any]
    window_qw: np.ndarray
    twiddle_re: np.ndarray
    twiddle_im: np.ndarray
    twiddle_inv_re: np.ndarray
    twiddle_inv_im: np.ndarray


def _as_int_array(values: tuple[int, ...]) -> np.ndarray:
    return np.asarray(values, dtype=np.int64)


def _read_array(path: Path, contract: MemhContract) -> np.ndarray:
    return _as_int_array(read_memh(path, contract).values)


def delayed_reference(x_in: np.ndarray, ny: int, delay: int = cfg.D) -> np.ndarray:
    """Return ``xz[n-delay]`` for ``0 <= n < ny`` using zero extension."""

    out = np.zeros(int(ny), dtype=np.int64)
    if ny <= delay:
        return out
    ncopy = min(len(x_in), ny - delay)
    if ncopy > 0:
        out[delay : delay + ncopy] = x_in[:ncopy]
    return out


def available_vectors(artifacts: str | Path) -> tuple[str, ...]:
    """Return vector names in ``test_vectors.json`` manifest order."""

    try:
        return tuple(item.name for item in discover_vector_artifacts(Path(artifacts)))
    except ManifestError as exc:
        raise PlotDataError(f"cannot discover vectors under {artifacts}: {exc}") from exc


def load_vector_plot_data(artifacts: str | Path, vector_name: str) -> VectorPlotData:
    """Load one vector's generated artifacts and compute delayed reference/error arrays."""

    artifacts_dir = Path(artifacts)
    try:
        vectors = {item.name: item for item in discover_vector_artifacts(artifacts_dir)}
    except ManifestError as exc:
        raise PlotDataError(f"cannot discover vectors under {artifacts_dir}: {exc}") from exc
    if vector_name not in vectors:
        names = ", ".join(sorted(vectors)) or "<none>"
        raise PlotDataError(f"unknown vector {vector_name!r}; available vectors: {names}")

    vec = vectors[vector_name]
    config = read_json(vec.config)
    metrics = read_json(vec.metrics)
    conf = config.get("configuration", {})
    rows = config.get("artifact_rows", {})
    ns = int(conf["Ns"])
    ny = int(conf["Ny"])
    frames = int(conf["frames"])
    delay = int(conf.get("D", cfg.D))

    x_in = _read_array(vec.x_in, contract_for_kind("x_in", rows=ns))
    y_out = _read_array(vec.y_out, contract_for_kind("y_out", rows=ny))
    x_delayed = delayed_reference(x_in, ny, delay)
    error = x_delayed - y_out

    frame_stats = read_frame_stats(vec.frame_stats, expected_rows=frames)
    bin_stats = None
    expected_bin_rows = rows.get("bin_stats_data_rows")
    if expected_bin_rows is not None:
        bin_stats = read_bin_stats(vec.bin_stats, expected_rows=int(expected_bin_rows))
    elif vec.bin_stats.exists():
        bin_stats = read_bin_stats(vec.bin_stats)

    return VectorPlotData(
        name=vector_name,
        config=config,
        metrics=metrics,
        x_in=x_in,
        y_out=y_out,
        x_delayed=x_delayed,
        error=error,
        frame_stats=frame_stats,
        bin_stats=bin_stats,
        vector_root=vec.test_vector_dir,
        golden_root=vec.golden_dir,
    )


def load_coefficients(artifacts: str | Path) -> CoefficientPlotData:
    """Load generated coefficient ROM artifacts from ``artifacts/coefficients``."""

    coeff_root = Path(artifacts) / "coefficients"
    manifest = read_json(coeff_root / "coeff_manifest.json")
    return CoefficientPlotData(
        root=coeff_root,
        manifest=manifest,
        window_qw=_read_array(coeff_root / "window_qw.memh", contract_for_kind("window_qw", rows=cfg.L)),
        twiddle_re=_read_array(coeff_root / "twiddle_re.memh", contract_for_kind("twiddle_re", rows=cfg.L)),
        twiddle_im=_read_array(coeff_root / "twiddle_im.memh", contract_for_kind("twiddle_im", rows=cfg.L)),
        twiddle_inv_re=_read_array(coeff_root / "twiddle_inv_re.memh", contract_for_kind("twiddle_inv_re", rows=cfg.L)),
        twiddle_inv_im=_read_array(coeff_root / "twiddle_inv_im.memh", contract_for_kind("twiddle_inv_im", rows=cfg.L)),
    )


__all__ = [
    "CoefficientPlotData",
    "PlotDataError",
    "VectorPlotData",
    "available_vectors",
    "delayed_reference",
    "load_coefficients",
    "load_vector_plot_data",
]
