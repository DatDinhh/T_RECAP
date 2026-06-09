# SPDX-License-Identifier: MIT
"""Plotting helpers for generated T-RECAP golden-model artifacts.

This package is intentionally read-only with respect to the artifact contract:
it reads generated/frozen artifacts and writes PNG/CSV/JSON plot outputs under
``out/``.  It does not generate coefficients, vectors, golden outputs,
quality bounds, or release manifests.
"""

from __future__ import annotations

from .artifact_data import CoefficientPlotData, VectorPlotData, available_vectors, load_coefficients, load_vector_plot_data

__all__ = [
    "CoefficientPlotData",
    "VectorPlotData",
    "available_vectors",
    "load_coefficients",
    "load_vector_plot_data",
]
