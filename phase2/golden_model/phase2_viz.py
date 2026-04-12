## Arizona State University 
## Capstone Senior Project
## Sigma Force
## Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jaeson
"""
phase2_viz.py

Visualization utility for T-RECAP Phase 2 golden-model artifacts.

Expected artifacts (matching the Phase 2 spec / model defaults):
  - x_in.memh
  - y_out.memh
  - frame_stats.csv
  - metrics.json
Optional debug artifacts:
  - frame_000000_fft_raw.csv
  - frame_000000_fft_can.csv
  - frame_000000_fft_masked.csv
  - ...

This script is intentionally verification-oriented. It does not just overlay x and y.
It also applies the exact delayed-reference rule used by Phase 2:
    e[n] = x[n - D] - y[n]
with zero extension outside the original input range.

Typical use:
  python phase2_viz.py --indir out_multitone
  python phase2_viz.py --indir out_dbg --debug-dir out_dbg/debug --debug-frame 0
  python phase2_viz.py --indir out_signoff --sample-start 300 --sample-count 800
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Select a non-interactive backend unless the user explicitly asks for --show.
_PRE = argparse.ArgumentParser(add_help=False)
_PRE.add_argument("--show", action="store_true")
_PRE_ARGS, _ = _PRE.parse_known_args()
if not _PRE_ARGS.show:
    import matplotlib
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Plot outputs from the T-RECAP Phase 2 golden model"
    )
    ap.add_argument(
        "--indir",
        default=".",
        help="Artifact directory containing x_in.memh, y_out.memh, frame_stats.csv, metrics.json",
    )
    ap.add_argument("--x", default=None, help="Path to input memh. Default: <indir>/x_in.memh")
    ap.add_argument("--y", default=None, help="Path to output memh. Default: <indir>/y_out.memh")
    ap.add_argument(
        "--frame-csv",
        default=None,
        help="Path to frame_stats.csv. Default: <indir>/frame_stats.csv",
    )
    ap.add_argument(
        "--metrics",
        default=None,
        help="Path to metrics.json. Default: <indir>/metrics.json",
    )
    ap.add_argument(
        "--debug-dir",
        default=None,
        help="Optional directory holding frame_XXXXXX_fft_raw/can/masked.csv dumps",
    )
    ap.add_argument(
        "--debug-frame",
        type=int,
        default=None,
        help="Optional frame index for spectrum debug plot. If omitted, first available frame is used.",
    )
    ap.add_argument(
        "--n",
        type=int,
        default=None,
        help="Bit width N for memh decode. Default: metrics.json['N']",
    )
    ap.add_argument(
        "--d",
        type=int,
        default=None,
        help="Delay D for alignment. Default: metrics.json['D']",
    )
    ap.add_argument(
        "--sample-start",
        type=int,
        default=0,
        help="First sample index for time-domain plots",
    )
    ap.add_argument(
        "--sample-count",
        type=int,
        default=2048,
        help="Number of samples to show in time-domain plots",
    )
    ap.add_argument(
        "--frame-start",
        type=int,
        default=0,
        help="First frame index for per-frame plots",
    )
    ap.add_argument(
        "--frame-count",
        type=int,
        default=512,
        help="Maximum number of frames to show in per-frame plots",
    )
    ap.add_argument(
        "--save-dir",
        default=None,
        help="Directory for PNG outputs. Default: <indir>/plots_phase2",
    )
    ap.add_argument(
        "--prefix",
        default="phase2",
        help="Filename prefix for saved plots",
    )
    ap.add_argument(
        "--show",
        action="store_true",
        help="Show plots interactively in addition to saving them",
    )
    ap.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save PNG files",
    )
    ap.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip recomputing error metrics from memh",
    )
    return ap


def resolve_path(indir: Path, maybe_path: Optional[str], default_name: str) -> Path:
    return Path(maybe_path) if maybe_path is not None else (indir / default_name)


def strip_comment(line: str) -> str:
    # Allow //, #, and ; comments.
    for marker in ("//", "#", ";"):
        pos = line.find(marker)
        if pos >= 0:
            line = line[:pos]
    return line.strip()


def read_memh_signed(path: Path, nbits: int) -> np.ndarray:
    if nbits <= 0:
        raise ValueError("nbits must be positive")

    values: List[int] = []
    full = 1 << nbits
    sign_bit = 1 << (nbits - 1)

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            s = strip_comment(raw)
            if not s:
                continue
            u = int(s, 16)
            if u & sign_bit:
                u -= full
            values.append(int(u))

    return np.asarray(values, dtype=np.int64)


def delayed_reference(x: np.ndarray, out_len: int, delay: int) -> np.ndarray:
    ref = np.zeros(out_len, dtype=np.int64)
    if delay < 0:
        raise ValueError("delay D must be nonnegative")
    if len(x) == 0 or out_len == 0:
        return ref

    start = delay
    stop = min(out_len, delay + len(x))
    if stop > start:
        ref[start:stop] = x[: stop - start]
    return ref


def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_frame_stats(path: Path) -> List[Dict[str, int]]:
    rows: List[Dict[str, int]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        required = {
            "frame_idx",
            "raw_unique_bins",
            "raw_suppressed_bins",
            "eligible_unique_bins",
            "eligible_suppressed_bins",
            "kept_mag2",
            "total_mag2",
        }
        if rdr.fieldnames is None:
            raise ValueError(f"{path} has no CSV header")
        missing = required - set(rdr.fieldnames)
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")

        for row in rdr:
            rows.append({k: int(v) for k, v in row.items() if k is not None})
    return rows


def load_complex_csv(path: Path) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    bins: List[int] = []
    re_vals: List[int] = []
    im_vals: List[int] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        required = {"bin", "re", "im"}
        if rdr.fieldnames is None:
            raise ValueError(f"{path} has no CSV header")
        missing = required - set(rdr.fieldnames)
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        for row in rdr:
            bins.append(int(row["bin"]))
            re_vals.append(int(row["re"]))
            im_vals.append(int(row["im"]))
    return (
        np.asarray(bins, dtype=np.int64),
        np.asarray(re_vals, dtype=np.int64),
        np.asarray(im_vals, dtype=np.int64),
    )


def safe_ratio(num: int, den: int, default: float = 0.0) -> float:
    return default if den == 0 else float(num) / float(den)


def error_metrics(ref: np.ndarray, y: np.ndarray) -> Dict[str, object]:
    if len(ref) != len(y):
        L = min(len(ref), len(y))
        ref = ref[:L]
        y = y[:L]
    e = ref.astype(np.int64) - y.astype(np.int64)
    abs_e = np.abs(e)
    sum_abs = int(abs_e.sum(dtype=np.int64)) if len(abs_e) else 0
    sum_sq = int(np.dot(e.astype(object), e.astype(object))) if len(e) else 0
    max_abs = int(abs_e.max()) if len(abs_e) else 0
    rmse = math.sqrt(sum_sq / len(e)) if len(e) else 0.0
    return {
        "sum_abs_err": sum_abs,
        "sum_sq_err": sum_sq,
        "max_abs_err": max_abs,
        "rmse": rmse,
        "error_sample_count": int(len(e)),
        "error": e,
    }


def choose_debug_frame(debug_dir: Path, requested: Optional[int]) -> Optional[int]:
    if requested is not None:
        return requested
    pat = re.compile(r"frame_(\d{6})_fft_raw\.csv$")
    found: List[int] = []
    for p in debug_dir.glob("frame_*_fft_raw.csv"):
        m = pat.search(p.name)
        if m:
            found.append(int(m.group(1)))
    if not found:
        return None
    return min(found)


def print_summary(
    x: np.ndarray,
    y: np.ndarray,
    metrics: Optional[Dict],
    recomputed: Optional[Dict],
    frame_rows: Optional[List[Dict[str, int]]],
) -> None:
    print("Phase 2 visualization summary")
    print(f"  x samples                : {len(x)}")
    print(f"  y samples                : {len(y)}")
    if metrics is not None:
        for key in ("N", "L", "H", "F", "G", "D", "Ns", "frames", "thr2"):
            if key in metrics:
                print(f"  {key:<24}: {metrics[key]}")
        for key in (
            "raw_suppression_ratio",
            "eligible_suppression_ratio",
            "kept_energy_ratio",
            "rmse",
            "overflow_window_input",
            "overflow_fft",
            "overflow_canon_pre",
            "overflow_canon",
            "overflow_mag2",
            "overflow_ifft",
            "overflow_z",
            "overflow_ola",
        ):
            if key in metrics:
                print(f"  {key:<24}: {metrics[key]}")
    if frame_rows is not None:
        print(f"  frame_stats rows         : {len(frame_rows)}")
    if recomputed is not None:
        print("  recomputed from memh:")
        print(f"    sum_abs_err            : {recomputed['sum_abs_err']}")
        print(f"    sum_sq_err             : {recomputed['sum_sq_err']}")
        print(f"    max_abs_err            : {recomputed['max_abs_err']}")
        print(f"    rmse                   : {recomputed['rmse']:.12f}")
        if metrics is not None:
            for key in ("sum_abs_err", "sum_sq_err", "max_abs_err", "error_sample_count"):
                if key in metrics:
                    match = int(metrics[key]) == int(recomputed[key])
                    print(f"    match {key:<16}: {match}")
            if "rmse" in metrics:
                diff = abs(float(metrics["rmse"]) - float(recomputed["rmse"]))
                print(f"    match rmse             : {diff < 1e-12}")
    print()


def save_fig(fig: plt.Figure, out_path: Path) -> None:
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)


def plot_raw_waveform(
    x: np.ndarray,
    y: np.ndarray,
    start: int,
    count: int,
    out_path: Optional[Path] = None,
) -> plt.Figure:
    x_pad = np.zeros(len(y), dtype=np.int64)
    x_pad[: min(len(x_pad), len(x))] = x[: min(len(x_pad), len(x))]
    s0 = max(0, start)
    s1 = min(len(y), s0 + max(1, count))

    fig = plt.figure()
    plt.plot(np.arange(s0, s1), x_pad[s0:s1], label="x[n] raw input")
    plt.plot(np.arange(s0, s1), y[s0:s1], label="y[n] output")
    plt.title(f"Raw input vs output (shows causal delay) [{s0}:{s1}]")
    plt.xlabel("sample index n")
    plt.ylabel("sample value")
    plt.grid(True)
    plt.legend()
    if out_path is not None:
        save_fig(fig, out_path)
    return fig


def plot_aligned_waveform(
    ref: np.ndarray,
    y: np.ndarray,
    start: int,
    count: int,
    delay: int,
    out_path: Optional[Path] = None,
) -> plt.Figure:
    s0 = max(0, start)
    s1 = min(len(y), s0 + max(1, count))
    fig = plt.figure()
    plt.plot(np.arange(s0, s1), ref[s0:s1], label=f"x[n-D], D={delay}")
    plt.plot(np.arange(s0, s1), y[s0:s1], label="y[n]")
    plt.title(f"Delayed reference vs output [{s0}:{s1}]")
    plt.xlabel("sample index n")
    plt.ylabel("sample value")
    plt.grid(True)
    plt.legend()
    if out_path is not None:
        save_fig(fig, out_path)
    return fig


def plot_error(
    err: np.ndarray,
    start: int,
    count: int,
    out_path: Optional[Path] = None,
) -> plt.Figure:
    s0 = max(0, start)
    s1 = min(len(err), s0 + max(1, count))
    fig = plt.figure()
    plt.plot(np.arange(s0, s1), err[s0:s1], label="e[n]")
    plt.title(f"Aligned error e[n] = x[n-D] - y[n] [{s0}:{s1}]")
    plt.xlabel("sample index n")
    plt.ylabel("error")
    plt.grid(True)
    plt.legend()
    if out_path is not None:
        save_fig(fig, out_path)
    return fig


def plot_error_hist(err: np.ndarray, out_path: Optional[Path] = None) -> plt.Figure:
    fig = plt.figure()
    plt.hist(err, bins=81)
    plt.title("Histogram of aligned error")
    plt.xlabel("error")
    plt.ylabel("count")
    plt.grid(True)
    if out_path is not None:
        save_fig(fig, out_path)
    return fig


def plot_cumulative_error(err: np.ndarray, out_path: Optional[Path] = None) -> plt.Figure:
    abs_err = np.abs(err.astype(np.int64))
    csum = np.cumsum(abs_err, dtype=np.int64)
    count = np.arange(1, len(abs_err) + 1, dtype=np.int64)
    mean_abs = csum / np.maximum(count, 1)

    fig = plt.figure()
    plt.plot(count - 1, mean_abs)
    plt.title("Cumulative mean absolute error")
    plt.xlabel("sample index n")
    plt.ylabel("mean |e| up to n")
    plt.grid(True)
    if out_path is not None:
        save_fig(fig, out_path)
    return fig


def plot_frame_suppression(
    rows: List[Dict[str, int]],
    start: int,
    count: int,
    out_path: Optional[Path] = None,
) -> plt.Figure:
    sub = rows[start : start + max(1, count)]
    idx = [r["frame_idx"] for r in sub]
    raw_ratio = [safe_ratio(r["raw_suppressed_bins"], r["raw_unique_bins"]) for r in sub]
    elig_ratio = [safe_ratio(r["eligible_suppressed_bins"], r["eligible_unique_bins"]) for r in sub]

    fig = plt.figure()
    plt.plot(idx, raw_ratio, label="raw suppression ratio")
    plt.plot(idx, elig_ratio, label="eligible suppression ratio")
    plt.title("Per-frame suppression ratios")
    plt.xlabel("frame index")
    plt.ylabel("ratio")
    plt.ylim(-0.02, 1.02)
    plt.grid(True)
    plt.legend()
    if out_path is not None:
        save_fig(fig, out_path)
    return fig


def plot_frame_energy(
    rows: List[Dict[str, int]],
    start: int,
    count: int,
    out_path: Optional[Path] = None,
) -> plt.Figure:
    sub = rows[start : start + max(1, count)]
    idx = [r["frame_idx"] for r in sub]
    keep_ratio = [safe_ratio(r["kept_mag2"], r["total_mag2"], default=1.0) for r in sub]

    fig = plt.figure()
    plt.plot(idx, keep_ratio)
    plt.title("Per-frame kept-energy ratio")
    plt.xlabel("frame index")
    plt.ylabel("kept_mag2 / total_mag2")
    plt.ylim(-0.02, 1.02)
    plt.grid(True)
    if out_path is not None:
        save_fig(fig, out_path)
    return fig


def plot_debug_spectrum(
    debug_dir: Path,
    frame_idx: int,
    out_path: Optional[Path] = None,
) -> Optional[plt.Figure]:
    raw_p = debug_dir / f"frame_{frame_idx:06d}_fft_raw.csv"
    can_p = debug_dir / f"frame_{frame_idx:06d}_fft_can.csv"
    msk_p = debug_dir / f"frame_{frame_idx:06d}_fft_masked.csv"
    if not (raw_p.exists() and can_p.exists() and msk_p.exists()):
        return None

    b0, r0, i0 = load_complex_csv(raw_p)
    b1, r1, i1 = load_complex_csv(can_p)
    b2, r2, i2 = load_complex_csv(msk_p)
    mag0 = np.sqrt(r0.astype(np.float64) ** 2 + i0.astype(np.float64) ** 2)
    mag1 = np.sqrt(r1.astype(np.float64) ** 2 + i1.astype(np.float64) ** 2)
    mag2 = np.sqrt(r2.astype(np.float64) ** 2 + i2.astype(np.float64) ** 2)

    fig = plt.figure()
    plt.plot(b0, mag0, label="raw FFT |X|")
    plt.plot(b1, mag1, label="canonicalized |Xcan|")
    plt.plot(b2, mag2, label="masked |Xhat|")
    plt.title(f"Debug spectrum for frame {frame_idx}")
    plt.xlabel("bin")
    plt.ylabel("magnitude")
    plt.grid(True)
    plt.legend()
    if out_path is not None:
        save_fig(fig, out_path)
    return fig


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = build_argparser()
    args = ap.parse_args(argv)

    indir = Path(args.indir)
    x_path = resolve_path(indir, args.x, "x_in.memh")
    y_path = resolve_path(indir, args.y, "y_out.memh")
    frame_path = resolve_path(indir, args.frame_csv, "frame_stats.csv")
    metrics_path = resolve_path(indir, args.metrics, "metrics.json")

    metrics: Optional[Dict] = None
    if metrics_path.exists():
        metrics = load_json(metrics_path)

    nbits = args.n if args.n is not None else (int(metrics["N"]) if metrics and "N" in metrics else None)
    if nbits is None:
        raise SystemExit("ERROR: need --n or metrics.json containing N")

    delay = args.d if args.d is not None else (int(metrics["D"]) if metrics and "D" in metrics else 0)

    if not x_path.exists():
        raise SystemExit(f"ERROR: input memh not found: {x_path}")
    if not y_path.exists():
        raise SystemExit(f"ERROR: output memh not found: {y_path}")

    x = read_memh_signed(x_path, nbits)
    y = read_memh_signed(y_path, nbits)
    ref = delayed_reference(x, len(y), delay)

    recomputed: Optional[Dict] = None
    if not args.no_verify:
        recomputed = error_metrics(ref, y)

    frame_rows: Optional[List[Dict[str, int]]] = None
    if frame_path.exists():
        frame_rows = load_frame_stats(frame_path)

    print_summary(x, y, metrics, recomputed, frame_rows)

    save_dir = Path(args.save_dir) if args.save_dir is not None else (indir / "plots_phase2")
    save_enabled = not args.no_save
    if save_enabled:
        save_dir.mkdir(parents=True, exist_ok=True)

    err = recomputed["error"] if recomputed is not None else (ref.astype(np.int64) - y.astype(np.int64))

    figs: List[plt.Figure] = []
    figs.append(
        plot_raw_waveform(
            x,
            y,
            args.sample_start,
            args.sample_count,
            None if not save_enabled else save_dir / f"{args.prefix}_wave_raw.png",
        )
    )
    figs.append(
        plot_aligned_waveform(
            ref,
            y,
            args.sample_start,
            args.sample_count,
            delay,
            None if not save_enabled else save_dir / f"{args.prefix}_wave_aligned.png",
        )
    )
    figs.append(
        plot_error(
            err,
            args.sample_start,
            args.sample_count,
            None if not save_enabled else save_dir / f"{args.prefix}_error.png",
        )
    )
    figs.append(
        plot_error_hist(
            err,
            None if not save_enabled else save_dir / f"{args.prefix}_error_hist.png",
        )
    )
    figs.append(
        plot_cumulative_error(
            err,
            None if not save_enabled else save_dir / f"{args.prefix}_cumulative_mae.png",
        )
    )

    if frame_rows is not None and len(frame_rows) > 0:
        figs.append(
            plot_frame_suppression(
                frame_rows,
                args.frame_start,
                args.frame_count,
                None if not save_enabled else save_dir / f"{args.prefix}_frame_suppression.png",
            )
        )
        figs.append(
            plot_frame_energy(
                frame_rows,
                args.frame_start,
                args.frame_count,
                None if not save_enabled else save_dir / f"{args.prefix}_frame_kept_energy.png",
            )
        )

    debug_dir = Path(args.debug_dir) if args.debug_dir is not None else None
    if debug_dir is not None and debug_dir.exists():
        chosen = choose_debug_frame(debug_dir, args.debug_frame)
        if chosen is not None:
            fig = plot_debug_spectrum(
                debug_dir,
                chosen,
                None if not save_enabled else save_dir / f"{args.prefix}_debug_frame_{chosen:06d}.png",
            )
            if fig is not None:
                figs.append(fig)

    # Save a small text summary for run-to-run traceability.
    if save_enabled:
        summary_path = save_dir / f"{args.prefix}_summary.txt"
        with summary_path.open("w", encoding="utf-8") as f:
            f.write("Phase 2 visualization summary\n")
            f.write(f"x_path={x_path}\n")
            f.write(f"y_path={y_path}\n")
            f.write(f"frame_stats_path={frame_path if frame_path.exists() else 'MISSING'}\n")
            f.write(f"metrics_path={metrics_path if metrics_path.exists() else 'MISSING'}\n")
            f.write(f"N={nbits}\n")
            f.write(f"D={delay}\n")
            f.write(f"x_len={len(x)}\n")
            f.write(f"y_len={len(y)}\n")
            if metrics is not None:
                for k in sorted(metrics.keys()):
                    f.write(f"metrics.{k}={metrics[k]}\n")
            if recomputed is not None:
                for k in ("sum_abs_err", "sum_sq_err", "max_abs_err", "rmse", "error_sample_count"):
                    f.write(f"recomputed.{k}={recomputed[k]}\n")

    if save_enabled:
        print(f"Saved plots to: {save_dir}")

    if args.show:
        plt.show()
    else:
        for fig in figs:
            plt.close(fig)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
