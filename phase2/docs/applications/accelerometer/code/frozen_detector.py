"""Shared offline step detector and independent event scoring for T-RECAP.

This file does not choose parameters, normalize records, read labels while
detecting, or contact hardware. Detector configuration and scoring intervals
must be frozen on calibration data, then reused unchanged for every route.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy import signal


DETECTOR_GRID = {
    "prominence_g": (0.03, 0.05, 0.08, 0.12, 0.20),
    "height_g": (0.0, 0.05, 0.10),
    "min_spacing_s": (0.30, 0.40, 0.50),
}


def detect_steps(xyz_g, *, fs=15.0, prominence_g=0.08, height_g=0.0,
                 min_spacing_s=0.30, lowpass_hz=None):
    """Find positive peaks in Euclidean acceleration magnitude minus 1 g.

    XYZ must already be expressed in physical g units. Nothing is scaled to a
    recording's extrema or RMS. The optional second-order Butterworth lowpass
    uses ``sosfiltfilt`` and is explicitly offline/noncausal. ``find_peaks``
    prominence and distance selection are also offline. At 15 Hz a requested
    0.30-second minimum spacing becomes ceil(4.5) = 5 samples.

    Run this on the complete contextual recording, then restrict event scoring
    with ``score_events``. Filtering a scored crop separately changes its edges.
    """
    xyz = np.asarray(xyz_g, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.all(np.isfinite(xyz)):
        raise ValueError("xyz_g must be a finite [samples, 3] array")
    if not math.isfinite(fs) or fs <= 0:
        raise ValueError("fs must be finite and positive")
    if not math.isfinite(prominence_g) or prominence_g < 0:
        raise ValueError("prominence_g must be finite and nonnegative")
    if not math.isfinite(height_g):
        raise ValueError("height_g must be finite")
    if not math.isfinite(min_spacing_s) or min_spacing_s <= 0:
        raise ValueError("min_spacing_s must be finite and positive")
    feature = np.linalg.norm(xyz, axis=1) - 1.0
    if lowpass_hz is not None:
        if not math.isfinite(lowpass_hz) or not 0 < lowpass_hz < fs / 2:
            raise ValueError("lowpass_hz must lie strictly between zero and Nyquist")
        sos = signal.butter(2, lowpass_hz, btype="lowpass", fs=fs, output="sos")
        # scipy rejects recordings too short for its fixed default edge pad;
        # do not silently change the filter or use a different short-record rule.
        feature = signal.sosfiltfilt(sos, feature)
    distance_samples = max(1, math.ceil(min_spacing_s * fs))
    indices, properties = signal.find_peaks(
        feature, prominence=prominence_g, height=height_g,
        distance=distance_samples,
    )
    return {
        "times_s": indices.astype(np.float64) / fs,
        "indices": indices,
        "feature_g": feature,
        "peak_prominences_g": properties["prominences"],
        "peak_heights_g": properties["peak_heights"],
        "config": {
            "fs": float(fs), "prominence_g": float(prominence_g),
            "height_g": float(height_g), "min_spacing_s": float(min_spacing_s),
            "min_spacing_samples": distance_samples,
            "lowpass_hz": None if lowpass_hz is None else float(lowpass_hz),
            "feature": "sqrt(x_g**2 + y_g**2 + z_g**2) - 1",
            "offline": True,
        },
    }


def _events(values, name):
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 1 or not np.all(np.isfinite(result)):
        raise ValueError(name + " must be a finite one-dimensional array")
    return result


def _intervals(values, name):
    """Validate and canonicalize half-open intervals; join touching intervals."""
    result = []
    for pair in values:
        if len(pair) != 2:
            raise ValueError(name + " must contain (start, stop) pairs")
        start, stop = map(float, pair)
        if not math.isfinite(start) or not math.isfinite(stop) or start >= stop:
            raise ValueError(name + " must contain finite start < stop pairs")
        result.append((start, stop))
    result.sort()
    merged = []
    for start, stop in result:
        if merged and start < merged[-1][1]:
            raise ValueError(name + " must not overlap")
        if merged and start == merged[-1][1]:
            merged[-1] = (merged[-1][0], stop)
        else:
            merged.append((start, stop))
    return merged


def _scored_support(score_intervals, exclude_intervals):
    support = [(-math.inf, math.inf)] if score_intervals is None else _intervals(
        score_intervals, "score_intervals")
    excluded = _intervals(() if exclude_intervals is None else exclude_intervals,
                          "exclude_intervals")
    for ex_start, ex_stop in excluded:
        split = []
        for start, stop in support:
            if ex_stop <= start or ex_start >= stop:
                split.append((start, stop))
            else:
                if start < ex_start:
                    split.append((start, ex_start))
                if ex_stop < stop:
                    split.append((ex_stop, stop))
        support = split
    return support


@dataclass(frozen=True)
class _State:
    count: int
    error: float
    pred_index: int
    truth_index: int
    previous: int


def _match_sorted(pred, truth, tolerance_s):
    """Sparse sequence DP: maximum matches, then minimum total absolute error.

    For points on a line with a common absolute-distance tolerance, crossing
    pairs can be uncrossed without reducing cardinality or increasing error.
    Thus an optimal increasing matching suffices. A Fenwick prefix tree stores
    the best chain ending before each reference event. Updates are deferred
    until all candidates for one prediction are examined, preventing reuse of
    that prediction. Repeated event timestamps remain distinct events.
    """
    if not len(pred) or not len(truth):
        return []
    states = [_State(0, 0.0, -1, -1, -1)]
    tree = np.zeros(len(truth) + 1, dtype=np.int64)

    def better(left, right):
        a, b = states[left], states[right]
        if a.count != b.count:
            return left if a.count > b.count else right
        if a.error != b.error:
            return left if a.error < b.error else right
        return min(left, right)  # Stable, deterministic tie breaking.

    def query(prefix_length):
        best = 0
        while prefix_length:
            best = better(best, int(tree[prefix_length]))
            prefix_length -= prefix_length & -prefix_length
        return best

    def update(position, state_id):
        while position < len(tree):
            tree[position] = better(int(tree[position]), state_id)
            position += position & -position

    for i, predicted in enumerate(pred):
        left = int(np.searchsorted(truth, predicted - tolerance_s, side="left"))
        right = int(np.searchsorted(truth, predicted + tolerance_s, side="right"))
        pending = []
        for j in range(left, right):
            previous = query(j)
            state = states[previous]
            states.append(_State(state.count + 1,
                                 state.error + abs(float(predicted - truth[j])),
                                 i, j, previous))
            pending.append((j + 1, len(states) - 1))
        for position, state_id in pending:
            update(position, state_id)
    state_id = query(len(truth))
    matched = []
    while state_id:
        state = states[state_id]
        matched.append((state.pred_index, state.truth_index))
        state_id = state.previous
    return matched[::-1]


def score_events(predicted_times, truth_times, *, tolerance_s=0.25,
                 score_intervals=None, exclude_intervals=None):
    """Score one-to-one step events against independently annotated timestamps.

    Input times may be unsorted; returned indices refer to the original input.
    Intervals are half-open [start, stop), and the same support is applied to
    predictions and truth. Events cannot match across separate support pieces.
    Timing must already be on the source clock (subtract the known FPGA delay
    before detection); this routine never searches for a favorable time shift.

    Undefined precision/recall/F1 is None. Zero-step intervals contribute false
    positives and exposure time, but do not manufacture perfect recall. Counts
    may be pooled before computing aggregate metrics. Count error alone cannot
    reveal missed/extra event cancellation, so TP/FP/FN are always returned.
    """
    pred = _events(predicted_times, "predicted_times")
    truth = _events(truth_times, "truth_times")
    if not math.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError("tolerance_s must be finite and nonnegative")
    support = _scored_support(score_intervals, exclude_intervals)
    pred_keep = np.zeros(len(pred), dtype=bool)
    truth_keep = np.zeros(len(truth), dtype=bool)
    matched = []
    for start, stop in support:
        pi = np.flatnonzero((pred >= start) & (pred < stop))
        ti = np.flatnonzero((truth >= start) & (truth < stop))
        pred_keep[pi], truth_keep[ti] = True, True
        pi = pi[np.argsort(pred[pi], kind="stable")]
        ti = ti[np.argsort(truth[ti], kind="stable")]
        for i, j in _match_sorted(pred[pi], truth[ti], tolerance_s):
            p, t = int(pi[i]), int(ti[j])
            matched.append({
                "prediction_index": p, "truth_index": t,
                "predicted_time_s": float(pred[p]), "truth_time_s": float(truth[t]),
                "error_s": float(pred[p] - truth[t]),
            })
    matched.sort(key=lambda row: (row["predicted_time_s"], row["prediction_index"]))
    used_pred = {row["prediction_index"] for row in matched}
    used_truth = {row["truth_index"] for row in matched}
    unmatched_pred = [int(i) for i in np.flatnonzero(pred_keep) if i not in used_pred]
    unmatched_truth = [int(i) for i in np.flatnonzero(truth_keep) if i not in used_truth]
    tp, fp, fn = len(matched), len(unmatched_pred), len(unmatched_truth)
    duration = sum(stop - start for start, stop in support)
    finite_duration = math.isfinite(duration)
    return {
        "TP": tp, "FP": fp, "FN": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "F1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None,
        "count_error": fp - fn,
        "absolute_count_error": abs(fp - fn),
        "predicted_count": tp + fp, "truth_count": tp + fn,
        "scored_duration_s": float(duration) if finite_duration else None,
        "false_positives_per_minute": 60 * fp / duration if finite_duration and duration > 0 else None,
        "tolerance_s": float(tolerance_s),
        "mean_absolute_timing_error_s": float(np.mean([abs(row["error_s"]) for row in matched])) if matched else None,
        "matched": matched,
        "unmatched_prediction_indices": unmatched_pred,
        "unmatched_truth_indices": unmatched_truth,
        "unmatched_prediction_times_s": [float(pred[i]) for i in unmatched_pred],
        "unmatched_truth_times_s": [float(truth[i]) for i in unmatched_truth],
        "excluded_prediction_indices": np.flatnonzero(~pred_keep).tolist(),
        "excluded_truth_indices": np.flatnonzero(~truth_keep).tolist(),
        "score_intervals": [[None if not math.isfinite(start) else start,
                             None if not math.isfinite(stop) else stop]
                            for start, stop in support],
    }
