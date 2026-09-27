# SPDX-License-Identifier: MIT
"""Independent Revision J integer oracle; no production-model imports.

Recursive even/odd transforms preserve the normative rounding graph without
copying the C++ iterative bit-reversal implementation. WOLA uses absolute output
indices, not a circular memory. Frozen coefficients are explicit inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict


@dataclass(frozen=True)
class Config:
    N: int = 12
    L: int = 256
    H: int = 128
    F: int = 15
    G: int = 128
    D: int = 384


def rounded(value: int, shift: int) -> int:
    """Nearest integer, ties away; quotient/remainder formulation."""
    if shift < 0:
        raise ValueError("negative rounded shift")
    divisor = 1 << shift
    quotient, remainder = divmod(abs(value), divisor)
    magnitude = quotient + int(2 * remainder >= divisor)
    return -magnitude if value < 0 else magnitude


def fit(value: int, width: int) -> int:
    if not -(1 << (width - 1)) <= value < (1 << (width - 1)):
        raise ValueError(f"internal signed{width} overflow: {value}")
    return value


def saturated(value: int, width: int) -> int:
    return min((1 << (width - 1)) - 1, max(-(1 << (width - 1)), value))


def transform(values: list[tuple[int, int]], table: list[tuple[int, int]],
              inverse: bool, cfg: Config = Config()) -> list[tuple[int, int]]:
    if len(values) != cfg.L or len(table) != cfg.L:
        raise ValueError("transform/table length")
    input_width = 28 if inverse else 27
    for re, im in values:
        fit(re, input_width)
        fit(im, input_width)
        if not inverse and im:
            raise ValueError("public forward interface is real-only")
    width = 36 if inverse else 28

    def recurse(items: list[tuple[int, int]]) -> list[tuple[int, int]]:
        n = len(items)
        if n == 1:
            return items
        even = recurse(items[::2])
        odd = recurse(items[1::2])
        low, high = [], []
        for k, ((ar, ai), (br, bi)) in enumerate(zip(even, odd)):
            wr, wi = table[k * cfg.L // n]
            tr = rounded(br * wr - bi * wi, cfg.F)
            ti = rounded(br * wi + bi * wr, cfg.F)
            # Stronger RTL-domain guard, in addition to C++ output stage checks.
            fit(tr, width)
            fit(ti, width)
            shift = 0 if inverse else 1
            low.append((fit(rounded(ar + tr, shift), width),
                        fit(rounded(ai + ti, shift), width)))
            high.append((fit(rounded(ar - tr, shift), width),
                         fit(rounded(ai - ti, shift), width)))
        return low + high

    return recurse(values)


def canonical(values: list[tuple[int, int]], cfg: Config = Config()):
    out = [(0, 0)] * cfg.L
    out[0], out[cfg.L // 2] = (values[0][0], 0), (values[cfg.L // 2][0], 0)
    for k in range(1, cfg.L // 2):
        a, b = values[k], values[-k]
        re, im = rounded(a[0] + b[0], 1), rounded(a[1] - b[1], 1)
        out[k], out[-k] = (fit(re, 28), fit(im, 28)), (fit(re, 28), fit(-im, 28))
    return out


def mask(values: list[tuple[int, int]], threshold: int, frame: int,
         cfg: Config = Config()):
    if not 0 <= threshold < 1 << 56:
        raise ValueError("THR2 out of range")
    bins = []
    for k, (re, im) in enumerate(values[:cfg.L // 2 + 1]):
        magnitude = re * re + im * im
        eligible, preliminary = int(k != 0), int(magnitude < threshold)
        bins.append((frame, k, re, im, magnitude, eligible, preliminary,
                     preliminary & eligible))
    weights = [1] + [2] * (cfg.L // 2 - 1) + [1]
    stats = (frame, len(bins), sum(b[7] for b in bins),
             sum(b[5] for b in bins), sum(b[7] * b[5] for b in bins),
             sum(w * b[4] for b, w in zip(bins, weights) if b[5] and not b[7]),
             sum(w * b[4] for b, w in zip(bins, weights) if b[5]))
    masked = [value if not bins[min(k, cfg.L - k)][7] else (0, 0)
              for k, value in enumerate(values)]
    return bins, stats, masked


METRIC_NAMES = ("unique_bins", "unique_suppressed_bins", "eligible_unique_bins",
                "eligible_suppressed_bins", "eligible_kept_mag2", "eligible_total_mag2",
                "sum_abs_err", "sum_sq_err", "max_abs_err", "error_sample_count")


def run(samples: list[int], threshold: int, window: list[int], forward, inverse,
        cfg: Config = Config()) -> dict[tuple, tuple]:
    if not samples or len(window) != cfg.L:
        raise ValueError("empty stream or invalid window")
    for sample in samples:
        fit(sample, cfg.N)
    if any(not 0 <= w <= 1 << cfg.F for w in window):
        raise ValueError("window domain")
    # Derive active frames by nonzero-window support, not the batch formula.
    taus = []
    tau = cfg.H
    while tau - cfg.L < len(samples):
        if any(window[i] != 0 and 0 <= tau - cfg.L + i < len(samples)
               for i in range(cfg.L)):
            taus.append(tau)
        tau += cfg.H
    if not taus:
        raise ValueError("no active frame")
    ny = taus[-1] + cfg.G + cfg.L
    records = {("G",): (len(samples), len(taus), taus[-1], ny)}
    contributions: dict[int, int] = defaultdict(int)
    totals = [0] * 6
    for frame, tau in enumerate(taus):
        source = [samples[n] if 0 <= n < len(samples) else 0
                  for n in range(tau - cfg.L, tau)]
        analysis = [(fit(x * w, 27), 0) for x, w in zip(source, window)]
        raw = transform(analysis, forward, False, cfg)
        can = canonical(raw, cfg)
        bins, stats, masked = mask(can, threshold, frame, cfg)
        time = transform(masked, inverse, True, cfg)
        z = [(fit(rounded(re * w, cfg.F), 36), 0)
             for (re, _), w in zip(time, window)]
        for stage, array in (("analysis", analysis), ("fft", raw), ("canonical", can),
                             ("masked", masked), ("ifft", time), ("z", z)):
            for k, value in enumerate(array):
                records[("S", frame, stage, k)] = value
        records[("F", frame)] = stats[1:]
        for row in bins:
            records[("B", row[0], row[1])] = row[2:]
        totals = [a + b for a, b in zip(totals, stats[1:])]
        for i, (value, _) in enumerate(z):
            target = tau + cfg.G + i
            contributions[target] = fit(contributions[target] + value, 37)
    errors = []
    for n in range(ny):
        y = saturated(rounded(contributions.get(n, 0), cfg.F), cfg.N)
        records[("Y", n)] = (y,)
        ref = samples[n - cfg.D] if 0 <= n - cfg.D < len(samples) else 0
        errors.append(ref - y)
    metrics = totals + [sum(abs(e) for e in errors), sum(e * e for e in errors),
                        max(abs(e) for e in errors), ny]
    for name, value in zip(METRIC_NAMES, metrics):
        records[("M", name)] = (value,)
    return records