# SPDX-License-Identifier: MIT
"""Coefficient ROM plots for generated T-RECAP golden artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from trecap_golden.generated import trecap_config as cfg

from .artifact_data import load_coefficients
from .vector_plots import _import_pyplot


def plot_coefficients(artifacts: str | Path, out_dir: str | Path) -> list[Path]:
    """Generate PNG/JSON plots for generated coefficient artifacts."""

    data = load_coefficients(artifacts)
    out = Path(out_dir) / "coefficients"
    out.mkdir(parents=True, exist_ok=True)
    plt = _import_pyplot()
    written: list[Path] = []
    x = np.arange(cfg.L)

    fig = plt.figure()
    plt.plot(x, data.window_qw)
    plt.title("Periodic sqrt-Hann window coefficient ROM: window_qw")
    plt.xlabel("coefficient index i")
    plt.ylabel("unsigned Qw value")
    plt.grid(True)
    p = out / "window_qw.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    fig = plt.figure()
    plt.plot(x, data.twiddle_re, label="twiddle_re")
    plt.plot(x, data.twiddle_im, label="twiddle_im")
    plt.title("Forward twiddle ROM")
    plt.xlabel("twiddle exponent e")
    plt.ylabel("signed coefficient")
    plt.grid(True)
    plt.legend()
    p = out / "twiddle_forward.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    fig = plt.figure()
    plt.plot(x, data.twiddle_inv_re, label="twiddle_inv_re")
    plt.plot(x, data.twiddle_inv_im, label="twiddle_inv_im")
    plt.title("Inverse twiddle ROM")
    plt.xlabel("twiddle exponent e")
    plt.ylabel("signed coefficient")
    plt.grid(True)
    plt.legend()
    p = out / "twiddle_inverse.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    fig = plt.figure()
    plt.hist(data.window_qw, bins=51)
    plt.title("window_qw value histogram")
    plt.xlabel("unsigned Qw value")
    plt.ylabel("count")
    plt.grid(True)
    p = out / "window_qw_histogram.png"
    fig.tight_layout()
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p)

    summary = {
        "schema": "trecap_phase2_coefficient_plot_summary_v1",
        "L": cfg.L,
        "F": cfg.F,
        "W_Qw": cfg.W_Qw,
        "W_tw": cfg.W_tw,
        "plots": [path.name for path in written],
        "hashes": data.manifest.get("hashes", {}),
    }
    summary_path = out / "coefficient_plot_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    written.append(summary_path)
    return written


__all__ = ["plot_coefficients"]
