#!/usr/bin/env python3
"""Analyze one continuous INA228 session and bracketed FPGA trials.

Timing bounds are conditional on the explicitly recorded clock-rate and sensor
timing assumptions. They do not include calibration uncertainty. All results
refer to the physical DC sensing boundary, including board background power.
"""

import argparse
import bisect
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


def read_jsonl(path):
    with open(path, encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def student_t_975(df):
    """Numerical .975 quantile; angle substitution keeps integration bounded."""
    coefficient = math.exp(math.lgamma((df+1)/2)-math.lgamma(df/2))/math.sqrt(math.pi)
    def half_cdf(angle):
        count = 2048
        step = angle/count
        total = 1.0 + math.cos(angle)**(df-1)
        for i in range(1, count):
            total += (4 if i % 2 else 2)*math.cos(i*step)**(df-1)
        return coefficient*step*total/3
    low, high = 0.0, math.pi/2
    for _ in range(45):
        middle = (low+high)/2
        if half_cdf(middle) < .475:
            low = middle
        else:
            high = middle
    return math.sqrt(df)*math.tan((low+high)/2)


def load_samples(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(handle)]
    if len(rows) < 3:
        raise ValueError("At least three meter rows are required")
    for i, row in enumerate(rows):
        if not all(math.isfinite(v) for v in row.values()):
            raise ValueError("Non-finite meter value")
        if row["t_end_s"] < row["t_start_s"]:
            raise ValueError("Reversed meter read window")
        if row["accumulation_valid"] != 1 or row["memory_ok"] != 1:
            raise ValueError("Session contains invalid accumulated energy")
        for flag in ("math_overflow", "energy_overflow", "math_overflow_latched",
                     "energy_overflow_latched", "memory_error_latched"):
            if row[flag] != 0:
                raise ValueError("Session contains a diagnostic fault: " + flag)
        if i and (row["seq"] <= rows[i-1]["seq"] or
                  row["t_start_s"] <= rows[i-1]["t_end_s"] or
                  row["energy_J"] < rows[i-1]["energy_J"]):
            raise ValueError("Sequence, time or energy discontinuity in session")
    return rows


class ClockMap:
    def __init__(self, records, session, rate_ppm):
        self.rate = rate_ppm * 1e-6
        self.points = []
        for row in records:
            if row.get("event") != "sync_reply" or row.get("device_session") != session:
                continue
            freq = float(row["qpc_frequency"])
            if freq <= 0:
                raise ValueError("Invalid QPC frequency")
            lo = row["send_before_qpc"] / freq
            hi = row["receive_qpc"] / freq
            device = row["device_t_ns"] * 1e-9
            if hi < lo:
                raise ValueError("Reversed host sync bracket")
            self.points.append((device, lo, hi))
        if len(self.points) < 2:
            raise ValueError("At least two matched sync replies in the selected session are required")
        self.points.sort()

    def device_interval(self, host_lo, host_hi):
        """Intersect inverse clock bounds from every causal sync exchange."""
        low, high = -math.inf, math.inf
        for device, anchor_lo, anchor_hi in self.points:
            differences = (host_lo - anchor_hi, host_hi - anchor_lo)
            corners = [device + delta / rate for delta in differences
                       for rate in (1-self.rate, 1+self.rate)]
            low, high = max(low, min(corners)), min(high, max(corners))
        if low > high:
            raise ValueError("Clock bounds inconsistent; check sessions/QPC or enlarge justified rate bound")
        return low, high


class EnergyTrace:
    def __init__(self, rows, guard):
        self.rows = rows
        self.lo = [r["t_start_s"] - guard for r in rows]
        self.hi = [r["t_end_s"] for r in rows]
        self.mid = [(a+b)/2 for a, b in zip(self.lo, self.hi)]
        self.energy = [r["energy_J"] for r in rows]

    def endpoint(self, lo, hi):
        before = bisect.bisect_right(self.hi, lo) - 1
        after = bisect.bisect_left(self.lo, hi)
        if before < 0 or after >= len(self.rows):
            raise ValueError("Meter capture does not bracket this trial; preserve idle padding")
        return self.energy[before], self.energy[after], before, after

    def interpolate(self, time):
        upper = bisect.bisect_left(self.mid, time)
        if upper <= 0 or upper >= len(self.mid):
            raise ValueError("Cannot interpolate outside meter time range")
        lower = upper-1
        fraction = (time-self.mid[lower])/(self.mid[upper]-self.mid[lower])
        return self.energy[lower] + fraction*(self.energy[upper]-self.energy[lower])


def analyze_trial(trial, trace, clock, frequency, args):
    if not trial.get("completed") or trial.get("mismatch_count") != 0:
        raise ValueError("Trial must be completed with an explicit zero mismatch count")
    cycles, hz, epochs = int(trial["cycles"]), float(trial["clock_hz"]), int(trial["epochs"])
    if cycles <= 0 or hz <= 0 or epochs <= 0:
        raise ValueError("Invalid fabric duration/work count")
    inputs = epochs * int(trial["inputs_per_epoch"])
    outputs = epochs * int(trial["outputs_per_epoch"])
    frames = epochs * int(trial["frames_per_epoch"])
    for key, expected in (("input_count", inputs), ("output_count", outputs), ("frame_count", frames)):
        if key in trial and int(trial[key]) != expected:
            raise ValueError("Observed " + key + " disagrees with requested work")
    nominal_duration = cycles/hz
    error = args.fabric_rate_ppm * 1e-6
    duration_lo, duration_hi = nominal_duration/(1+error), nominal_duration/(1-error)
    launch_lo = trial["launch_before_qpc"]/frequency
    launch_hi = trial["launch_after_qpc"]/frequency + args.launch_guard_s
    done_lo = trial.get("completion_before_qpc", trial["launch_before_qpc"])/frequency
    done_hi = trial["completion_after_qpc"]/frequency
    if launch_hi < launch_lo or done_hi < done_lo:
        raise ValueError("Reversed JTAG timing bracket")
    # Exact cycle count tightens wide host polling windows; clock rate is nominal.
    start_lo, start_hi = max(launch_lo, done_lo-duration_hi), min(launch_hi, done_hi-duration_lo)
    end_lo, end_hi = max(done_lo, start_lo+duration_lo), min(done_hi, start_hi+duration_hi)
    if start_lo > start_hi or end_lo > end_hi:
        raise ValueError("JTAG brackets and fabric duration are inconsistent")
    start = clock.device_interval(start_lo, start_hi)
    end = clock.device_interval(end_lo, end_hi)
    if end[0] <= start[1]:
        raise ValueError("No guaranteed active interval")
    sa, sb, si, sj = trace.endpoint(*start)
    ea, eb, ei, ej = trace.endpoint(*end)
    energy_lo, energy_hi = max(0.0, ea-sb), eb-sa
    estimate = trace.interpolate(sum(end)/2)-trace.interpolate(sum(start)/2)
    if not energy_lo-1e-6 <= estimate <= energy_hi+1e-6:
        raise ValueError("Interpolated energy escaped the conservative bracket")
    # Whole sensor read windows, including the conversion guard, lie inside active.
    first = bisect.bisect_left(trace.lo, start[1]+args.interior_trim_s)
    last = bisect.bisect_right(trace.hi, end[0]-args.interior_trim_s)-1
    if last-first < 2:
        raise ValueError("Not enough samples in the guaranteed active interior")
    plateau_energy = trace.energy[last]-trace.energy[first]
    plateau_duration = trace.mid[last]-trace.mid[first]
    plateau_lo = trace.lo[last]-trace.hi[first]
    plateau_hi = trace.hi[last]-trace.lo[first]
    if plateau_lo <= 0:
        raise ValueError("Interior read windows overlap")
    result = dict(trial)
    result.update({
        "duration_nominal_s": nominal_duration,
        "duration_host_bounds_s": [duration_lo, duration_hi],
        "device_start_bounds_s": list(start), "device_end_bounds_s": list(end),
        "energy_endpoint_row_indices": {"start_before": si, "start_after": sj,
                                         "end_before": ei, "end_after": ej},
        "board_energy_bounds_J": [energy_lo, energy_hi],
        "board_energy_interpolated_J": estimate,
        "board_J_per_input_bounds": [energy_lo/inputs, energy_hi/inputs],
        "board_J_per_input_interpolated": estimate/inputs,
        "board_J_per_output_interpolated": estimate/outputs,
        "board_J_per_epoch_interpolated": estimate/epochs,
        "total_inputs": inputs, "total_outputs": outputs, "total_frames": frames,
        "interior_rows": [first, last],
        "interior_duration_device_s": plateau_duration,
        "interior_board_power_W": plateau_energy/plateau_duration,
        "interior_board_power_timing_bounds_W": [plateau_energy/plateau_hi*(1-clock.rate),
                                                  plateau_energy/plateau_lo*(1+clock.rate)],
        "interior_scaled_energy_estimate_J": plateau_energy/plateau_duration*nominal_duration,
        "interior_mean_bus_V": statistics.mean(r["bus_voltage_V"] for r in trace.rows[first:last+1]),
        "interior_mean_current_A": statistics.mean(r["current_A"] for r in trace.rows[first:last+1]),
    })
    return result


def paired_results(trials, baseline, candidate):
    groups = {}
    for trial in trials:
        if "pair_id" not in trial:
            continue
        group = groups.setdefault(str(trial["pair_id"]), {})
        if trial["condition"] in group:
            raise ValueError("Duplicate condition in pair " + str(trial["pair_id"]))
        group[trial["condition"]] = trial
    pairs = []
    for pair_id, group in groups.items():
        if baseline not in group or candidate not in group:
            continue
        a, b = group[baseline], group[candidate]
        if any(a[key] != b[key] for key in ("total_inputs", "total_outputs", "epochs", "clock_hz")):
            raise ValueError("Unmatched work in pair " + pair_id)
        pairs.append({"pair_id": pair_id,
                      "delta_board_energy_candidate_minus_baseline_J": b["board_energy_interpolated_J"]-a["board_energy_interpolated_J"],
                      "delta_board_energy_timing_bounds_J": [b["board_energy_bounds_J"][0]-a["board_energy_bounds_J"][1],
                                                             b["board_energy_bounds_J"][1]-a["board_energy_bounds_J"][0]],
                      "delta_interior_power_candidate_minus_baseline_W": b["interior_board_power_W"]-a["interior_board_power_W"]})
    summary = {"baseline_condition": baseline, "candidate_condition": candidate, "pairs": pairs,
               "n_pairs": len(pairs), "interval_scope": "Across-pair repeatability only; calibration and timing assumptions are separate."}
    if pairs:
        for metric in ("delta_board_energy_candidate_minus_baseline_J", "delta_interior_power_candidate_minus_baseline_W"):
            values = [p[metric] for p in pairs]
            entry = {"mean": statistics.mean(values), "stdev": statistics.stdev(values) if len(values)>1 else None}
            if len(values)>1:
                halfwidth = student_t_975(len(values)-1)*statistics.stdev(values)/math.sqrt(len(values))
                entry["paired_mean_95pct_t_interval"] = [entry["mean"]-halfwidth, entry["mean"]+halfwidth]
            summary[metric] = entry
    return summary


def make_plots(trace, results, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = ["#9ebad3", "#dbb0bd", "#b4caaa", "#d8c392"]
    conditions = list(dict.fromkeys(r["condition"] for r in results))
    palette = {name: colors[i % len(colors)] for i, name in enumerate(conditions)}
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(11.5, 4.5), layout="constrained")
    ax.plot([(r["t_start_s"]+r["t_end_s"])/2 for r in trace.rows],
            [r["power_W"] for r in trace.rows], color="#485a67", lw=.8)
    for result in results:
        lo, hi = result["device_start_bounds_s"][1], result["device_end_bounds_s"][0]
        ax.axvspan(lo, hi, color=palette[result["condition"]], alpha=.35)
        ax.text((lo+hi)/2, 1.01, str(result["trial_id"]), transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=8)
    for condition in conditions:
        ax.plot([], [], color=palette[condition], lw=8, label=condition)
    ax.set(xlabel="Meter session time (s)", ylabel="Board DC-input power (W)",
           title="Whole-board power; shading marks guaranteed active interiors")
    ax.legend(loc="best", frameon=False)
    ax.grid(alpha=.2)
    fig.savefig(outdir/"board_power_timeline.png", dpi=200)
    fig.savefig(outdir/"board_power_timeline.pdf")
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), layout="constrained")
    for i, result in enumerate(results):
        point = result["board_J_per_input_interpolated"]*1e6
        lo, hi = [v*1e6 for v in result["board_J_per_input_bounds"]]
        axes[0].errorbar(i, point, yerr=[[max(0, point-lo)], [max(0, hi-point)]],
                         fmt="o", color=palette[result["condition"]], capsize=3)
        axes[1].scatter(i, result["interior_board_power_W"], color=palette[result["condition"]], s=35)
    for ax in axes:
        ax.set_xticks(range(len(results)), [str(r["trial_id"]) for r in results], rotation=45)
        ax.set_xlabel("Trial")
        ax.grid(axis="y", alpha=.2)
    axes[0].set(ylabel="Board energy per input sample (µJ)", title="Batch estimate with timing bounds")
    axes[1].set(ylabel="Board DC-input power (W)", title="Mean power inside active interval")
    fig.suptitle("Uncalibrated board measurements; uncertainty bars cover timing assumptions")
    fig.savefig(outdir/"board_trial_comparison.png", dpi=200)
    fig.savefig(outdir/"board_trial_comparison.pdf")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--sync", type=Path, required=True)
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--session", type=int, default=1)
    parser.add_argument("--device-rate-ppm", type=float, default=1000)
    parser.add_argument("--fabric-rate-ppm", type=float, default=1000)
    parser.add_argument("--sensor-time-guard-s", type=float, default=.020)
    parser.add_argument("--launch-guard-s", type=float, default=.000001)
    parser.add_argument("--interior-trim-s", type=float, default=.5)
    parser.add_argument("--baseline", default="threshold_0")
    parser.add_argument("--candidate", default="threshold_1e11")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    if not (0 <= args.device_rate_ppm < 1e6 and 0 <= args.fabric_rate_ppm < 1e6):
        parser.error("Clock rate bounds must be in [0, 1000000) ppm")
    if min(args.sensor_time_guard_s, args.launch_guard_s, args.interior_trim_s) < 0:
        parser.error("Timing guards must not be negative")
    if args.out.exists():
        parser.error("Output directory already exists; choose a new analysis directory")
    rows = load_samples(args.csv)
    clock = ClockMap(read_jsonl(args.sync), args.session, args.device_rate_ppm)
    trace = EnergyTrace(rows, args.sensor_time_guard_s)
    manifest = json.loads(args.trials.read_text(encoding="utf-8-sig"))
    frequency = float(manifest["qpc_frequency"])
    if frequency <= 0:
        parser.error("Invalid trial QPC frequency")
    results = [analyze_trial(t, trace, clock, frequency, args) for t in manifest["trials"]]
    report = {
        "schema": "board-measurement-analysis-1",
        "scope": "Whole-board DC boundary; same SOF and different threshold operating points. No automatic savings claim.",
        "sources": {name: {"path": str(path.resolve()), "sha256": sha256(path)} for name, path in
                    (("meter_csv", args.csv), ("clock_sync", args.sync), ("trial_events", args.trials))},
        "assumptions": {"device_clock_rate_bound_ppm": args.device_rate_ppm,
                        "fabric_clock_rate_bound_ppm": args.fabric_rate_ppm,
                        "sensor_effective_time_guard_s": args.sensor_time_guard_s,
                        "launch_crossing_guard_s": args.launch_guard_s,
                        "active_interior_trim_s": args.interior_trim_s,
                        "status": "Explicit engineering assumptions, not calibrated or certified bounds.",
                        "accuracy": "Calibration, shunt tolerance, sensor gain/offset and supply-boundary uncertainty are not included."},
        "meter_rows": len(rows), "matched_sync_replies": len(clock.points),
        "sequence_gaps": sum(max(0, int(b["seq"]-a["seq"]-1)) for a,b in zip(rows, rows[1:])),
        "sync_roundtrip_min_s": min(hi-lo for _,lo,hi in clock.points),
        "sync_roundtrip_max_s": max(hi-lo for _,lo,hi in clock.points),
        "trials": results, "paired_statistics": paired_results(results, args.baseline, args.candidate),
    }
    args.out.mkdir(parents=True)
    (args.out/"measurement_analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if not args.no_plots:
        make_plots(trace, results, args.out)
    print(json.dumps({"analysis": str(args.out/"measurement_analysis.json"), "trials": len(results),
                      "pairs": report["paired_statistics"]["n_pairs"]}))


if __name__ == "__main__":
    main()
