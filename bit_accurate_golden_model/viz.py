# Arizona State Univerity 
# Capstone Senior Project
# Sigma Force
# Dat Dinh, Dat Huyynh, Paul Applebee, Kyung Jae Son
import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt


def read_memh_signed(path: str, N: int) -> np.ndarray:
    """
    Read one hex value per line representing an N-bit two's complement number
    Returns int32 numpy array
    """
    p = Path(path)
    data = []
    with p.open("r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            u = int(s, 16)

            # Sign-extend from N bits
            sign_bit = 1 << (N - 1)
            full = 1 << N
            if (u & sign_bit) != 0:
                u = u - full
            data.append(u)

    return np.array(data, dtype=np.int32)


def read_flags(path: str) -> np.ndarray:
    """
    Read one 0/1 per line 
    Returns int32 numpy array
    """
    p = Path(path)
    flags = []
    with p.open("r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            flags.append(1 if s != "0" else 0)
    return np.array(flags, dtype=np.int32)


def moving_average(x: np.ndarray, w: int) -> np.ndarray:
    if w <= 1:
        return x
    w = min(w, len(x))
    kernel = np.ones(w, dtype=np.float64) / float(w)
    return np.convolve(x.astype(np.float64), kernel, mode="same")


def main():
    ap = argparse.ArgumentParser(description="Visualize golden_model memh outputs")
    ap.add_argument("--n", type=int, required=True, help="Bit width N used by golden model")
    ap.add_argument("--x", default="x.memh", help="Input memh")
    ap.add_argument("--y", default="y.memh", help="Output memh")
    ap.add_argument("--sup", default="sup.memh", help="Suppression flags (per pair)")
    ap.add_argument("--metrics", default="metrics.json", help="Metrics json")
    ap.add_argument("--max", type=int, default=2000, help="Max samples to plot (time-domain plots)")
    ap.add_argument("--smooth", type=int, default=1, help="Moving-average window for x/y overlay (1 = off)")
    ap.add_argument("--save", action="store_true", help="Save plots as PNG files instead of only showing them")
    args = ap.parse_args()

    N = args.n

    x = read_memh_signed(args.x, N)
    y = read_memh_signed(args.y, N)

    L = min(len(x), len(y))
    if L == 0:
        raise SystemExit("ERROR: x/y length is zero. Check memh files.")

    # limit for time plots
    M = min(L, args.max)
    xt = x[:M]
    yt = y[:M]
    e = xt - yt

    # suppression: 1 flag per pair => repeat each flag twice to align with samples
    sup_pair = read_flags(args.sup)
    sup_samp = np.repeat(sup_pair, 2)
    sup_samp = sup_samp[:M]  # align with plotted region

    # print metrics.json
    met_path = Path(args.metrics)
    if met_path.exists():
        with met_path.open("r") as f:
            met = json.load(f)
        print("metrics.json =", met)
        tp = met.get("total_pairs", 0)
        sp = met.get("suppressed_pairs", 0)
        if tp > 0:
            print("suppressed_ratio =", sp / tp)
        print()
    else:
        print(f"NOTE: {args.metrics} not found.\n")

    # optional smoothing 
    xt_plot = moving_average(xt, args.smooth)
    yt_plot = moving_average(yt, args.smooth)

    # Plot 1: x vs y overlay
    plt.figure()
    plt.plot(xt_plot, label="x (input)")
    plt.plot(yt_plot, label="y (recon)")
    plt.title(f"x vs y (first {M} samples)  N={N}  smooth={args.smooth}")
    plt.xlabel("sample index")
    plt.ylabel("value (signed)")
    plt.grid(True)
    plt.legend()

    # Plot 2: error over time
    plt.figure()
    plt.plot(e, label="e = x - y")
    plt.title(f"Error over time (first {M} samples)")
    plt.xlabel("sample index")
    plt.ylabel("error")
    plt.grid(True)
    plt.legend()

    # Plot 3: suppression markers
    # show as a stem-like line: 0/1 repeated per sample
    plt.figure()
    plt.plot(sup_samp, label="suppressed (repeated per sample)")
    plt.ylim(-0.2, 1.2)
    plt.title("Suppression flags (per pair expanded to samples)")
    plt.xlabel("sample index")
    plt.ylabel("suppressed")
    plt.grid(True)
    plt.legend()

    # Plot 4: histograms
    plt.figure()
    plt.hist(xt, bins=51)
    plt.title("Histogram: x (input)")
    plt.xlabel("value")
    plt.ylabel("count")
    plt.grid(True)

    plt.figure()
    plt.hist(yt, bins=51)
    plt.title("Histogram: y (recon)")
    plt.xlabel("value")
    plt.ylabel("count")
    plt.grid(True)

    plt.figure()
    plt.hist(e, bins=51)
    plt.title("Histogram: error (x - y)")
    plt.xlabel("error")
    plt.ylabel("count")
    plt.grid(True)

    if args.save:
        # save all figures
        out_names = [
            "plot_x_vs_y.png",
            "plot_error.png",
            "plot_suppression.png",
            "hist_x.png",
            "hist_y.png",
            "hist_error.png",
        ]
        for fig_num, name in zip(plt.get_fignums(), out_names):
            plt.figure(fig_num)
            plt.tight_layout()
            plt.savefig(name, dpi=150)
        print("Saved PNGs:", ", ".join(out_names))
    else:
        plt.show()


if __name__ == "__main__":
    main()
