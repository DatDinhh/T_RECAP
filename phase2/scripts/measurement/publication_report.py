#!/usr/bin/env python3
"""Publish a sanitized report from a completed, admitted measurement campaign.

No serial/JTAG access. Refuses incomplete campaign data, changed source hashes,
unsuccessful output checking, and an existing output directory. Requires only
the standard library and matplotlib for the paired-difference figure.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def same_hash(path, expected):
    require(Path(path).is_file(), "Missing evidence: " + str(path))
    require(digest(path).lower() == expected.lower(), "Evidence hash mismatch: " + str(path))


def relative(path, repo):
    return Path(path).resolve().relative_to(repo).as_posix()


def write_csv(path, rows):
    require(bool(rows), "Empty output table: " + str(path))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def portable_text(text):
    forbidden = r"(?i)(?:[A-Z]:[\\/]|C:/Users/|OneDrive|PNPDeviceID|VID_[0-9A-F]{4}|PID_[0-9A-F]{4}|\bCOM\d+\b|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    require(re.search(forbidden, text) is None, "Publication input contains a host path or device identifier")
    return text


def fit_value(content, label):
    match = re.search(re.escape(label)+r"\s*:\s*([\d,]+)", content)
    require(match is not None, "Missing fitter field: " + label)
    return int(match.group(1).replace(",", ""))


def admission(repo, run_root, analysis_path, csv_path):
    analysis = read_json(analysis_path)
    campaign_dir = analysis_path.parent.parent
    campaign_path = campaign_dir/"campaign_manifest.json"
    campaign = read_json(campaign_path)
    require(campaign.get("status") == "PASS_CAPTURE_AND_TRIAL_ADMISSION",
            "Publication requires a completed and admitted campaign; do not read a live CSV")
    require(analysis.get("schema") == "board-measurement-analysis-1", "Unexpected analysis schema")
    for filename, expected in campaign["sources_sha256"].items():
        same_hash(filename, expected)
    for filename, expected in campaign["outputs_sha256"].items():
        same_hash(filename, expected)
    for name, source in analysis["sources"].items():
        same_hash(source["path"], source["sha256"])
    same_hash(csv_path, analysis["sources"]["meter_csv"]["sha256"])
    same_hash(campaign_dir/"trials.json", analysis["sources"]["trial_events"]["sha256"])
    trials = analysis["trials"]
    require(len(trials) == campaign["trial_count"] == 12, "Expected twelve admitted measured trials")
    require(len({t["trial_id"] for t in trials}) == 12, "Duplicate measured trial ID")
    for trial in trials:
        require(trial.get("completed") is True and trial["mismatch_count"] == 0 and
                trial.get("fault_flags") == 0, "Failed live output check")
        require(trial["clock_hz"] == 50_000_000 and trial["epochs"] == 16384,
                "Unexpected measured clock or finite work count")
        for actual, per_epoch in (("input_count", 1024), ("output_count", 1536), ("frame_count", 9)):
            require(trial[actual] == trial["epochs"]*per_epoch, "Incorrect live work count: " + actual)
        require(trial["threshold2"] == {"dense": 0, "masked": 100_000_000_000}[trial["condition"]],
                "Condition/threshold mismatch")
    require(len({t["cycles"] for t in trials}) == 1,
            "Dense and masked cycle counts differ; revise the fixed-duration interpretation")
    paired = analysis["paired_statistics"]
    require(paired["baseline_condition"] == "dense" and paired["candidate_condition"] == "masked"
            and paired["n_pairs"] == 6, "Expected six masked-minus-dense pairs")
    groups = {}
    for trial in trials:
        group = groups.setdefault(str(trial["pair_id"]), {})
        require(trial["condition"] not in group, "Duplicate condition within pair")
        group[trial["condition"]] = trial
    pair_rows = []
    for pair_id, group in groups.items():
        require(set(group) == {"dense", "masked"}, "Incomplete measured pair")
        a, b = group["dense"], group["masked"]
        delta = b["interior_board_power_W"]-a["interior_board_power_W"]
        recorded = next(p for p in paired["pairs"] if str(p["pair_id"]) == pair_id)
        require(math.isclose(delta, recorded["delta_interior_power_candidate_minus_baseline_W"], abs_tol=1e-12),
                "Paired difference sign/value disagreement")
        pair_rows.append({"pair_id": pair_id, "dense_trial": a["trial_id"], "masked_trial": b["trial_id"],
                          "dense_interior_power_W": a["interior_board_power_W"],
                          "masked_interior_power_W": b["interior_board_power_W"],
                          "masked_minus_dense_mW": delta*1000,
                          "difference_percent_of_pair_dense": delta/a["interior_board_power_W"]*100,
                          "power_difference_timing_lower_mW": (b["interior_board_power_timing_bounds_W"][0]-a["interior_board_power_timing_bounds_W"][1])*1000,
                          "power_difference_timing_upper_mW": (b["interior_board_power_timing_bounds_W"][1]-a["interior_board_power_timing_bounds_W"][0])*1000,
                          "batch_energy_difference_estimate_J": recorded["delta_board_energy_candidate_minus_baseline_J"],
                          "batch_energy_difference_timing_lower_J": recorded["delta_board_energy_timing_bounds_J"][0],
                          "batch_energy_difference_timing_upper_J": recorded["delta_board_energy_timing_bounds_J"][1]})
    power_stats = paired["delta_interior_power_candidate_minus_baseline_W"]
    require(math.isclose(statistics.mean(p["masked_minus_dense_mW"] for p in pair_rows),
                         power_stats["mean"]*1000, abs_tol=1e-9), "Paired mean disagreement")
    values = [p["masked_minus_dense_mW"]*.001 for p in pair_rows]
    halfwidth = 2.570581835636305 * statistics.stdev(values)/math.sqrt(6)  # t(.975,5)
    for got, expected in zip(power_stats["paired_mean_95pct_t_interval"],
                             (statistics.mean(values)-halfwidth, statistics.mean(values)+halfwidth)):
        require(math.isclose(got, expected, abs_tol=1e-9), "Paired 95% repeatability interval disagrees")

    # Check meter data only after final campaign and hashes have been admitted.
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        meter = list(csv.DictReader(handle))
    require(len(meter) == analysis["meter_rows"], "Meter row count differs from final analysis")
    for row in meter:
        require(all(math.isfinite(float(value)) for value in row.values()), "Non-finite meter data")
        require(row["accumulation_valid"] == "1" and row["memory_ok"] == "1", "Invalid meter accumulation")
        require(all(row[name] == "0" for name in ("math_overflow", "energy_overflow", "math_overflow_latched",
                                                   "energy_overflow_latched", "memory_error_latched")),
                "Meter diagnostic fault")
    capture_summary_path = campaign_dir/"capture.summary.json"
    capture_summary = read_json(capture_summary_path)
    require(capture_summary["ok"] is True and capture_summary["rows"] == len(meter),
            "Capture summary does not match the final meter data")
    metadata_path = Path(capture_summary["metadata_jsonl"])
    metadata = [json.loads(line) for line in metadata_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    sessions = [event for event in metadata if event.get("event") == "session_start"]
    require(len(sessions) == 1 and sessions[0]["accumulators_reset_once"] is True,
            "Expected one explicitly reset meter session")
    config = sessions[0]["configuration"]
    for name, wanted in {"shunt_ohms": .015, "max_current_A": 10.0, "adc_range": 0,
                         "averaging_samples": 16, "bus_conversion_us": 280, "shunt_conversion_us": 280,
                         "mode": "CONT_BUS_SHUNT", "requested_log_rate_Hz": 10}.items():
        require(config[name] == wanted, "Unexpected recorded instrument configuration: " + name)

    reference_path = repo/"artifacts/measurement/multitone/manifest.json"
    reference = read_json(reference_path)
    require((reference["input_samples"], reference["output_samples"], reference["frames"]) == (1024, 1536, 9),
            "Reference geometry does not match the measured workload")
    same_hash(repo/"artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh", reference["input_sha256"])
    for name, expected in reference["coefficient_sha256"].items():
        same_hash(repo/"artifacts/coefficients"/name, expected)
    for case in reference["cases"]:
        require(case["cpp_oracle_output_mismatches"] == 0, "Reference/oracle disagreement")
        same_hash(reference_path.parent/("y_"+case["name"]+".memh"), case["output_sha256"])
    require({c["name"]: c["threshold"] for c in reference["cases"]} ==
            {"dense": 0, "masked": 100_000_000_000}, "Unexpected reference thresholds")

    program_path, build_admission_path = run_root/"program_manifest.json", run_root/"build_admission.json"
    program, build_admission = read_json(program_path), read_json(build_admission_path)
    require(program["status"] == "PROGRAMMED" and program["exit_code"] == 0, "Programming did not pass")
    same_hash(build_admission_path, program["build_admission_sha256"])
    same_hash(program["sof"], program["sof_sha256"])
    require(program["sof_sha256"].lower() == build_admission["sof_sha256"].lower(), "Program/admission SOF mismatch")
    require(build_admission["status"] == "PASS_REVIEWED_MEASUREMENT_IMAGE" and
            build_admission["fabric_clock_hz"] == 50_000_000, "Build admission missing")
    build_root = Path(program["sof"]).resolve().parent.parent
    receipt_path = build_root/"build_receipt.json"
    build_receipt = read_json(receipt_path)
    require(build_receipt["ok"] is True and build_receipt["sof_sha256"].lower() == program["sof_sha256"].lower(),
            "Build receipt/SOF mismatch")
    fit_path = build_root/"output_files/trecap_measurement.fit.summary"
    fit = fit_path.read_text(encoding="utf-8-sig")
    require("Fitter Status : Successful" in fit, "Fitter was not successful")
    resources = {"ALMs": fit_value(fit, "Logic utilization (in ALMs)"),
                 "registers": fit_value(fit, "Total registers"),
                 "RAM blocks": fit_value(fit, "Total RAM Blocks"), "DSP blocks": fit_value(fit, "Total DSP Blocks")}
    corners_path = Path(build_receipt["timing_corners_csv"])
    with corners_path.open(encoding="utf-8-sig", newline="") as handle:
        corners = list(csv.DictReader(handle))
    require(len(corners) == 16 and len({c["corner"] for c in corners}) == 4 and
            all(float(c["slack_ns"]) >= 0 for c in corners), "Four-corner timing did not pass")
    for check in ("setup", "hold", "recovery", "removal"):
        values = [float(c["slack_ns"]) for c in corners if c["check"] == check]
        require(len(values) == 4 and math.isclose(min(values), build_admission["fabric_min_"+check+"_slack_ns"], abs_tol=1e-6),
                "Timing report/admission disagreement: " + check)
    qualification_path = run_root/"simulation_04/qualification.json"
    qualification = read_json(qualification_path)
    require(qualification["status"] == "PASS" and qualification["checks"] >= 101 and
            qualification["all_native_stage_exit_codes_zero"] is True, "Native simulation qualification missing")
    same_hash(repo/"platform/de1soc/measurement/trecap_measurement_engine.sv", qualification["engine_sha256"])
    same_hash(repo/"sim/verification/measurement_engine_tb.sv", qualification["testbench_sha256"])
    sim_path = qualification_path.parent/"simulate.stdout.log"
    same_hash(sim_path, qualification["simulation_log_sha256"])
    sim_log = sim_path.read_text(encoding="utf-8-sig", errors="replace")
    require("MEASUREMENT_ENGINE_PASS checks="+str(qualification["checks"]) in sim_log and
            re.findall(r"Errors:\s*(\d+)", sim_log) == ["0"], "Simulation evidence does not show zero-error PASS")
    evidence = {"analysis": analysis_path, "meter_csv": csv_path, "campaign_manifest": campaign_path,
                "capture_summary": capture_summary_path, "device_metadata": metadata_path,
                "clock_sync": Path(analysis["sources"]["clock_sync"]["path"]),
                "trial_events": campaign_dir/"trials.json", "reference_manifest": reference_path,
                "program_manifest": program_path, "build_admission": build_admission_path,
                "build_receipt": receipt_path, "fit_summary": fit_path, "timing_corners": corners_path,
                "simulation_qualification": qualification_path, "simulation_log": sim_path}
    return analysis, trials, pair_rows, meter, reference, resources, build_admission, qualification, evidence, program


def paired_plot(rows, stats, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    maroon, gold, soft, ink = "#8C1D40", "#FFC627", "#F8ECEF", "#29272B"
    mean = stats["mean"]*1000
    low, high = [value*1000 for value in stats["paired_mean_95pct_t_interval"]]
    timing_lo = statistics.mean(r["power_difference_timing_lower_mW"] for r in rows)
    timing_hi = statistics.mean(r["power_difference_timing_upper_mW"] for r in rows)
    fig, axes = plt.subplots(2, 1, figsize=(9, 7.0), layout="constrained", gridspec_kw={"height_ratios": [3.3, 1]})
    ax = axes[0]
    ax.axhline(0, color="#797579", lw=1.0, linestyle="--")
    ax.axvspan(5.55, 6.45, color=soft, zorder=0)
    ax.scatter(range(6), [row["masked_minus_dense_mW"] for row in rows], s=70,
               facecolor=gold, edgecolor=maroon, linewidth=1.3, zorder=3)
    ax.errorbar(6, mean, yerr=[[mean-low], [high-mean]], fmt="D", color=maroon,
                capsize=6, elinewidth=2, markersize=7, zorder=4)
    ax.set_xticks(range(7), ["Pair "+str(r["pair_id"]) for r in rows]+["Mean\n95% interval"])
    ax.set_xlim(-.5, 6.6)
    ax.set_ylabel("Masked − dense board power (mW)", color=ink)
    ax.set_title("Paired board-power difference", loc="left", fontsize=15, fontweight="bold", color=maroon, pad=14)
    ax.grid(axis="y", color="#DCD8D9", alpha=.6)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlabel("Six pairs; top interval describes repeatability only", fontsize=9)
    lower = axes[1]
    lower.axvline(0, color="#797579", lw=1, linestyle="--")
    lower.axvspan(timing_lo, timing_hi, color="#FFF4CD", zorder=0)
    lower.errorbar(mean, 0, xerr=[[mean-timing_lo], [timing_hi-mean]], fmt="D", color=maroon,
                   capsize=6, elinewidth=2, markersize=6)
    lower.set_ylim(-.6, .6)
    lower.set_yticks([])
    lower.set_xlabel("Mean masked − dense difference (mW)")
    lower.set_title(f"Conditional timing envelope: [{timing_lo:+.3f}, {timing_hi:+.3f}] mW; includes zero", fontsize=11, loc="left", pad=10)
    lower.spines[["top", "right", "left"]].set_visible(False)
    fig.supxlabel("Timing envelope is not a statistical CI. Both panels exclude calibration uncertainty.", fontsize=9)
    fig.savefig(out/"paired_power_difference.png", dpi=220)
    fig.savefig(out/"paired_power_difference.pdf")
    plt.close(fig)


def timeline_plot(meter, trials, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    palette = {"dense": "#EDD1DA", "masked": "#FBE5A0"}
    fig, ax = plt.subplots(figsize=(11.5, 5.0), layout="constrained")
    ax.plot([(float(r["t_start_s"])+float(r["t_end_s"]))/2 for r in meter],
            [float(r["power_W"]) for r in meter], color="#403B3D", lw=.8)
    for trial in trials:
        start, end = trial["device_start_bounds_s"][1], trial["device_end_bounds_s"][0]
        ax.axvspan(start, end, color=palette[trial["condition"]], alpha=.65)
        ax.text((start+end)/2, .97, trial["trial_id"].replace("trial_", "T"),
                transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=8, color="#593442")
    for condition, color in palette.items():
        ax.plot([], [], lw=8, color=color, label=condition)
    ax.set_title("Board power during finite replay trials", loc="left", color="#8C1D40", fontweight="bold", pad=18)
    ax.set(xlabel="Meter session time (s)", ylabel="Board DC-input power (W)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=.2)
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.18), ncol=2, frameon=False)
    fig.savefig(out/"board_power_timeline.png", dpi=220)
    fig.savefig(out/"board_power_timeline.pdf")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    repo, run_root, out = args.repo.resolve(), args.run_root.resolve(), args.out.resolve()
    require(not out.exists(), "Output directory already exists; choose a fresh publication directory")
    analysis, trials, pairs, meter, reference, resources, timing, qualification, evidence, program = admission(
        repo, run_root, args.analysis.resolve(), args.csv.resolve())
    stats = analysis["paired_statistics"]["delta_interior_power_candidate_minus_baseline_W"]
    condition_rows = []
    for condition in ("dense", "masked"):
        group = [t for t in trials if t["condition"] == condition]
        powers = [t["interior_board_power_W"] for t in group]
        condition_rows.append({"condition": condition, "threshold2": group[0]["threshold2"], "trials": len(group),
                               "mean_interior_board_power_W": statistics.mean(powers),
                               "trial_power_stdev_W": statistics.stdev(powers),
                               "mean_batch_energy_interpolated_J": statistics.mean(t["board_energy_interpolated_J"] for t in group),
                               "mean_board_uJ_per_input_interpolated": statistics.mean(t["board_J_per_input_interpolated"]*1e6 for t in group),
                               "mean_interior_voltage_V": statistics.mean(t["interior_mean_bus_V"] for t in group),
                               "mean_interior_current_A": statistics.mean(t["interior_mean_current_A"] for t in group)})
    trial_rows = []
    for t in trials:
        trial_rows.append({"trial_id": t["trial_id"], "pair_id": t["pair_id"], "condition": t["condition"],
                           "threshold2": t["threshold2"], "epochs": t["epochs"], "cycles": t["cycles"],
                           "nominal_duration_s": t["duration_nominal_s"], "inputs": t["total_inputs"],
                           "outputs": t["total_outputs"], "frames": t["total_frames"], "mismatches": t["mismatch_count"],
                           "interior_board_power_W": t["interior_board_power_W"],
                           "interior_power_timing_lower_W": t["interior_board_power_timing_bounds_W"][0],
                           "interior_power_timing_upper_W": t["interior_board_power_timing_bounds_W"][1],
                           "batch_energy_interpolated_J": t["board_energy_interpolated_J"],
                           "batch_energy_timing_lower_J": t["board_energy_bounds_J"][0],
                           "batch_energy_timing_upper_J": t["board_energy_bounds_J"][1],
                           "board_uJ_per_input_interpolated": t["board_J_per_input_interpolated"]*1e6})
    quality_rows = [{"condition": c["name"], "threshold2": c["threshold"],
                     "reference_RMSE_full_stream_LSB": c["rmse_full_stream_lsb"],
                     "reference_max_abs_error_LSB": c["max_abs_error_lsb"],
                     "eligible_bins": c["eligible_bins"], "suppressed_bins": c["suppressed_bins"],
                     "reference_spectral_retention_ratio": c["spectral_retention_ratio"]} for c in reference["cases"]]
    out.mkdir(parents=True)
    (out/"data").mkdir()
    write_csv(out/"data/condition_summary.csv", condition_rows)
    write_csv(out/"data/trials.csv", trial_rows)
    write_csv(out/"data/paired_power.csv", pairs)
    write_csv(out/"data/reference_quality.csv", quality_rows)
    shutil.copyfile(args.csv, out/"data/meter_samples.csv")
    published = {"meter_csv": "data/meter_samples.csv", "clock_sync": "data/clock_sync.jsonl",
                 "trial_events": "data/trial_events.json", "analysis": "data/measurement_analysis.json"}
    for role in ("clock_sync", "trial_events"):
        portable_text(evidence[role].read_text(encoding="utf-8-sig"))
        shutil.copyfile(evidence[role], out/published[role])
    portable_analysis = json.loads(json.dumps(analysis))
    for role, filename in (("meter_csv", "meter_samples.csv"), ("clock_sync", "clock_sync.jsonl"),
                           ("trial_events", "trial_events.json")):
        portable_analysis["sources"][role]["path"] = filename
    analysis_text = portable_text(json.dumps(portable_analysis, indent=2, allow_nan=False)+"\n")
    (out/published["analysis"]).write_text(analysis_text, encoding="utf-8")
    for stem in ("board_trial_comparison",):
        for suffix in (".png", ".pdf"):
            path = args.analysis.parent/(stem+suffix)
            require(path.is_file(), "Missing analyzer plot: " + str(path))
            shutil.copyfile(path, out/path.name)
            evidence[stem+suffix] = path
            published[stem+suffix] = path.name
    timeline_plot(meter, trials, out)
    paired_plot(pairs, stats, out)
    provenance = []
    for role, path in evidence.items():
        location = relative(path, repo)
        if role in ("meter_csv", "device_metadata", "clock_sync"):
            location = relative(path.parent, repo)+"/"
        provenance.append({"source_role": role, "repository_location": location,
                           "sha256": digest(path), "published_copy": published.get(role, ""),
                           "copy_transformation": "Only sources.path fields made local to data/" if role == "analysis" else ""})
    write_csv(out/"data/provenance.csv", provenance)
    mean_mw = stats["mean"]*1000
    ci = [v*1000 for v in stats["paired_mean_95pct_t_interval"]]
    dense_power = condition_rows[0]["mean_interior_board_power_W"]
    pct = stats["mean"]/dense_power*100
    total_outputs = sum(t["total_outputs"] for t in trials)
    total_inputs = sum(t["total_inputs"] for t in trials)
    conditions_md = "\n".join(f"| {r['condition']} | {r['threshold2']:,} | {r['mean_interior_board_power_W']:.6f} | {r['mean_batch_energy_interpolated_J']:.4f} | {r['mean_board_uJ_per_input_interpolated']:.4f} |" for r in condition_rows)
    quality_md = "\n".join(f"| {r['condition']} | {r['reference_RMSE_full_stream_LSB']:.3f} | {r['reference_max_abs_error_LSB']} | {r['suppressed_bins']}/{r['eligible_bins']} |" for r in quality_rows)
    interpretation = ("The repeatability interval includes zero; this campaign does not resolve a consistent direction of the power difference."
                      if ci[0] <= 0 <= ci[1] else
                      "The repeatability interval excludes zero for these paired runs. It does not establish calibrated accuracy or generalize beyond this board, image, input, and operating conditions.")
    assumptions = analysis["assumptions"]
    timing_power_envelope = [statistics.mean(row["power_difference_timing_lower_mW"] for row in pairs),
                             statistics.mean(row["power_difference_timing_upper_mW"] for row in pairs)]
    host_guard_ms = read_json(evidence["trial_events"])["clock_mapping"]["tcl_timestamp_guard_ms"]
    sync_rows = [json.loads(line) for line in evidence["clock_sync"].read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    session_index = next(row["device_session"] for row in sync_rows if row.get("event") == "sync_reply")
    unresolved_energy_pairs = sum(row["batch_energy_difference_timing_lower_J"] <= 0 <=
                                  row["batch_energy_difference_timing_upper_J"] for row in pairs)
    energy_interpretation = (f"All {len(pairs)} paired full-batch energy-difference bounds include zero. "
                             "The direct batch-energy result therefore does not establish a direction of change within the stated timing bounds."
                             if unresolved_energy_pairs == len(pairs) else
                             f"The full-batch energy-difference timing bounds include zero in {unresolved_energy_pairs} of {len(pairs)} pairs. "
                             "Those bounds and the instrument limitations must accompany any energy comparison.")
    report = f"""# T-RECAP board-power measurement

Date: 2026-09-25. Platform: DE1-SoC, Cyclone V 5CSEMA5F31C6. Configuration: standalone FPGA replay image without an HPS software workload.

## Observed result

Across six pairs, the mean masked-minus-dense difference in steady active board power was **{mean_mw:+.3f} mW**, with a **95% paired repeatability interval of [{ci[0]:+.3f}, {ci[1]:+.3f}] mW**. The mean difference was **{pct:+.4f}%** of the dense-condition mean power. Positive values mean the masked setting drew more power. {interpretation}

Propagating the per-trial timing bounds independently gives a **conditional timing envelope of [{timing_power_envelope[0]:+.3f}, {timing_power_envelope[1]:+.3f}] mW for the same mean power difference**. It includes zero, before adding calibration uncertainty. It is an interval from timing assumptions, not a statistical confidence interval. The small paired repeatability interval therefore does not establish a direction of power change after these timing allowances.

| Condition | Squared-magnitude threshold | Mean active board power (W) | Mean batch energy estimate (J) | Mean board energy/input estimate (µJ) |
|---|---:|---:|---:|---:|
{conditions_md}

![Paired power difference](paired_power_difference.png)

The upper panel shows six paired observations and their mean. The upper panel interval describes variation between those pairs and excludes systematic calibration uncertainty. Batch-energy central values use interpolation; their conditional timing bounds appear in [the trial table](data/trials.csv).

**{energy_interpretation}** The small steady-active power difference does not by itself qualify an electrical energy-saving claim.

## What was run and checked

The campaign used twelve measured trials in ABBA order repeated three times. Each trial ran 16,384 epochs at a nominal 50 MHz. Every epoch replayed the same 1,024 input samples, produced 1,536 output samples including startup/tail output, and processed nine frames. Both conditions used {trials[0]['cycles']:,} fabric cycles per trial, equivalent to {trials[0]['duration_nominal_s']:.6f} nominal seconds. This is repeated finite replay, not a continuous externally paced stream.

The measured trials consumed **{total_inputs:,} input samples** and checked **{total_outputs:,} output samples**. All terminal counters matched and all on-chip reference comparisons reported **zero mismatches and zero fault flags**. Each output's index and value were compared with the reference ROM for its condition. This evidence covers these workloads; it is not whole-project verification signoff. The measurement-controller simulation separately passed **{qualification['checks']} checks**, including repeated replay and injected faults.

![Board power across the completed campaign](board_power_timeline.png)

![Trial energy timing bounds and active power](board_trial_comparison.png)

The programmed image passed four timing corners. Minimum fabric setup slack was **+{timing['fabric_min_setup_slack_ns']:.3f} ns** and hold slack was **+{timing['fabric_min_hold_slack_ns']:.3f} ns**. Fitter use was **{resources['ALMs']:,} ALMs, {resources['registers']:,} registers, {resources['RAM blocks']} RAM blocks, and {resources['DSP blocks']} DSP blocks**. These totals include the replay source, output checker, counters, and JTAG shell. The timing review retained vendor JTAG hard-primitive/interface exceptions; it did not identify an unknown fabric clockless endpoint.

## Measurement boundary and timing

An INA228 with its stock 15 mΩ shunt measured the board's DC supply. VBUS was connected upstream of the shunt, so the boundary includes the shunt and downstream wiring losses. The FPGA image, board background consumption, replay/checker logic, and attached board peripherals contribute to the reading. Feather USB power and the adapter's AC-to-DC conversion loss are outside this boundary. This is DC input energy, not wall-plug energy or a measurement of an individual FPGA rail.

The sensor used continuous bus/shunt conversion, 16 averages, and 280 µs per channel, with 10 Hz host logging. The final capture contains {len(meter):,} valid rows and {analysis['matched_sync_replies']} matched clock exchanges. Hardware accumulated energy supplied the integral. A request/reply protocol bounded the correspondence between device time and the host clock; host brackets and fabric cycle counts located each batch. The longest recorded synchronization round trip was {analysis['sync_roundtrip_max_s']:.3f} s; the analysis retained timing uncertainty rather than assuming immediate USB delivery. The active-power calculation used only the guaranteed interior, trimmed by another {assumptions['active_interior_trim_s']:.3f} s at each end.

The analysis assumes device and fabric clock-rate bounds of {assumptions['device_clock_rate_bound_ppm']:g} ppm and {assumptions['fabric_clock_rate_bound_ppm']:g} ppm, respectively, and a {assumptions['sensor_effective_time_guard_s']*1000:g} ms sensor effective-time guard. Host Tcl timestamps used a ±{host_guard_ms:g} ms UTC-to-QPC guard. These are explicit engineering timing assumptions, not calibration certificates. Sensor gain/offset, shunt tolerance, temperature effects, and absolute calibration uncertainty remain outside those bounds. No idle-power subtraction is applied in this report.

## Output-quality tradeoff

The following error values come from the reference workload artifacts, not from the electrical meter. They compare reconstructed output with the input delayed by 384 samples and zero-padded outside its original extent. Metrics cover the full 1,536-sample output stream, including startup and tail regions.

| Condition | Reference RMSE (LSB) | Maximum absolute error (LSB) | Suppressed / eligible bins |
|---|---:|---:|---:|
{quality_md}

Both settings execute the same fixed FFT/IFFT schedule. Thresholding changes reconstructed output and arithmetic data activity; this experiment does not isolate a zero-aware compute-skipping implementation. A measured board-power difference by itself is not a general energy-saving result. Conclusions must retain the output-quality tradeoff and this board/workload boundary.

## Reproduction and provenance

The source input, reference output ROMs, coefficient files, build/program receipts, final capture, and admitted trial events were checked against recorded hashes before publication. The programmed SOF SHA-256 is `{program['sof_sha256'].lower()}`.

- [Condition summary](data/condition_summary.csv), [trial measurements and timing bounds](data/trials.csv), [paired differences](data/paired_power.csv), and [reference quality](data/reference_quality.csv).
- [Sanitized meter samples](data/meter_samples.csv), [clock exchanges](data/clock_sync.jsonl), and [admitted trial events](data/trial_events.json) preserve the original acquisition data without host paths or device identifiers.
- [Portable analysis](data/measurement_analysis.json) changes only the three source-path fields to names local to `data/`. Original source hashes and all numerical results are retained.
- [Provenance hashes](data/provenance.csv) identify retained evidence under `{relative(run_root, repo)}`. The run directory is ignored by Git; the published meter, sync, and trial files reproduce the timing/energy calculation without it.
- Implementation: [`platform/de1soc/measurement`](../../../platform/de1soc/measurement), [`sw/measurement/ina228`](../../../sw/measurement/ina228), and [`scripts/measurement`](../../../scripts/measurement).

With Python and Matplotlib available, run this command from the repository root, choosing a fresh output directory:

```text
python scripts/measurement/analyze_board_measurement.py --csv docs/results/board_power_20260925/data/meter_samples.csv --sync docs/results/board_power_20260925/data/clock_sync.jsonl --trials docs/results/board_power_20260925/data/trial_events.json --session {session_index} --baseline dense --candidate masked --device-rate-ppm {assumptions['device_clock_rate_bound_ppm']:g} --fabric-rate-ppm {assumptions['fabric_clock_rate_bound_ppm']:g} --sensor-time-guard-s {assumptions['sensor_effective_time_guard_s']:g} --launch-guard-s {assumptions['launch_crossing_guard_s']:g} --interior-trim-s {assumptions['active_interior_trim_s']:g} --out runs/measurement/publication_recheck_20260925
```

Vector figures: [power timeline](board_power_timeline.pdf), [trial comparison](board_trial_comparison.pdf), and [paired power difference](paired_power_difference.pdf).

The plotted and tabulated values preserve source precision for reproducibility. Displayed decimal places do not imply calibrated measurement accuracy.
"""
    portable_text(report)
    (out/"README.md").write_text(report, encoding="utf-8")
    publication = {"schema": "trecap-board-power-publication-1", "date": "2026-09-25",
                   "measurement_scope": "whole-board DC input; same fixed-schedule image, threshold operating points",
                   "pairs": 6, "trials": 12, "sof_sha256": program["sof_sha256"].lower(),
                   "paired_power_difference_mW": mean_mw, "paired_repeatability_95pct_interval_mW": ci,
                   "paired_mean_conditional_timing_envelope_mW": timing_power_envelope,
                   "source_hashes": {row["source_role"]: row["sha256"] for row in provenance},
                   "files": {path.relative_to(out).as_posix(): digest(path) for path in sorted(out.rglob("*")) if path.is_file()}}
    (out/"publication_manifest.json").write_text(json.dumps(publication, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"report": str(out/"README.md"), "pairs": 6, "trials": 12}))


if __name__ == "__main__":
    main()
