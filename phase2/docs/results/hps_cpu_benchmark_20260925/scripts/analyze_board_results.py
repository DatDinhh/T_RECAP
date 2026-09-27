#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Admit physical HPS timings and compare complete records with historical FPGA cycles.

No hardware access. Input files and receipts are read only. Writes a fresh report
directory with portable summaries, numerical tables and optional Matplotlib plots.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


CONDITIONS = {"dense": 0, "masked": 100_000_000_000}
SHAPE = {"inputs_per_epoch": 1024, "frames_per_epoch": 9,
         "tau_last": 1152, "outputs_per_epoch": 1536}
CONTRACT = {"N": 12, "L": 256, "H": 128, "F": 15, "G": 128, "D": 384,
            "rounding": "nearest ties away from zero", "final_saturation_bits": 12,
            "threshold_comparison": "strict mag2 < threshold; DC protected, Nyquist eligible"}
COEFFICIENTS = ("window_qw.memh", "twiddle_re.memh", "twiddle_im.memh",
                "twiddle_inv_re.memh", "twiddle_inv_im.memh")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def parse_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))


def read_json(path):
    return parse_json(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path):
    return [parse_json(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def same_hash(path, wanted):
    require(valid_hash(wanted) and path.is_file() and sha(path) == wanted.lower(),
            "Missing or changed evidence: " + path.name)


def portable(text):
    require(re.search(r"(?i)(?:[a-z]:[/\\]|/Users/|/home/|OneDrive|AppData|\bCOM\d+\b)", text) is None,
            "Public output contains a host-specific path or serial identifier")
    return text


def write_json(path, data):
    path.write_text(portable(json.dumps(data, indent=2, allow_nan=False) + "\n"), encoding="utf-8")


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    portable(path.read_text())


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values)-1)*fraction
    low = math.floor(position)
    high = math.ceil(position)
    return values[low] + (values[high]-values[low])*(position-low)


def describe(values):
    return {"n": len(values), "minimum": min(values), "q1": percentile(values, .25),
            "median": statistics.median(values), "q3": percentile(values, .75),
            "maximum": max(values), "mean": statistics.mean(values),
            "sample_stdev": statistics.stdev(values)}


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, "Invalid integer: " + label)
    return value


def finite(value, label):
    require(type(value) in (int, float) and math.isfinite(value), "Invalid finite number: " + label)
    return value


def recorded_hash(inventory, path):
    matches = [value for name, value in inventory.items() if Path(name).resolve() == path.resolve()]
    require(len(matches) == 1, "Evidence is not uniquely bound to campaign: " + path.name)
    same_hash(path, matches[0])


def probe_words(text):
    require(isinstance(text, str) and re.fullmatch(r"[0-9a-fA-F]{120}", text), "Malformed FPGA probe")
    value = int(text, 16)
    return [(value >> (32*i)) & 0xffffffff for i in range(15)]


def admit_vectors(directory):
    path = directory/"manifest.json"
    vectors = read_json(path)
    require(vectors["schema"] == "trecap-arm-qualification-vectors-1" and
            vectors["status"] == "GENERATED_ORACLE_EXPECTATIONS", "Unrecognized qualification vectors")
    for name, record in vectors["files"].items():
        target = (directory/name).resolve()
        require(target.is_relative_to(directory) and target.stat().st_size == record["bytes"],
                "Invalid vector inventory path/size")
        same_hash(target, record["sha256"])
    cases = {}
    for condition, threshold in CONDITIONS.items():
        matching = [case for case in vectors["cases"] if case["case_id"] == "multitone_"+condition]
        require(len(matching) == 1, "Missing or duplicate multitone reference")
        case = matching[0]
        require(case["oracle_status"] == "accepted" and case["threshold2"] == threshold and
                case["input_samples"] == 1024 and case["output_samples"] == 1536 and
                case["frames"] == 9 and case["tau_last"] == 1152 and
                case["measurement_reference_rom_match"] is True, "Wrong workload geometry/reference")
        cases[condition] = case
    require(cases["dense"]["input_sha256"] == cases["masked"]["input_sha256"], "Input differs by condition")
    return vectors, cases


def admit_fpga(jtag, cases, vectors):
    campaign_dir = jtag.parent
    root = campaign_dir.parent
    campaign_path = campaign_dir/"campaign_manifest.json"
    program_path, admission_path = root/"program_manifest.json", root/"build_admission.json"
    source_path = root/"source_manifest.json"
    campaign, program, admission, sources = map(read_json, (campaign_path, program_path, admission_path, source_path))
    require(campaign["schema"] == "trecap_host_campaign_v1" and
            campaign["status"] == "PASS_CAPTURE_AND_TRIAL_ADMISSION", "Historical FPGA campaign was not admitted")
    recorded_hash(campaign["outputs_sha256"], jtag)
    recorded_hash(campaign["sources_sha256"], program_path)
    require(program["status"] == "PROGRAMMED" and program["exit_code"] == 0, "Historical programming failed")
    same_hash(admission_path, program["build_admission_sha256"])
    same_hash(Path(program["sof"]), program["sof_sha256"])
    require(program["sof_sha256"].lower() == admission["sof_sha256"].lower() and
            admission["status"] == "PASS_REVIEWED_MEASUREMENT_IMAGE" and
            admission["fabric_clock_hz"] == 50_000_000, "Historical image/clock admission mismatch")
    require(all(admission["fabric_min_"+check+"_slack_ns"] >= 0 for check in ("setup", "hold", "recovery", "removal")),
            "Historical fitted timing did not pass")
    for name in COEFFICIENTS:
        key = "artifacts/coefficients/"+name
        require(sources["sha256"][key] == vectors["source_sha256"][key], "FPGA coefficient identity differs: " + name)
    require(sources["sha256"]["artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh"] ==
            cases["dense"]["input_sha256"], "FPGA input identity differs")
    events = read_jsonl(jtag)
    require(events and events[-1]["event"] == "campaign_complete" and events[-1]["completed"] is True and
            not any(event.get("event") == "campaign_error" for event in events), "Historical campaign did not finish cleanly")
    results = {}
    for condition, threshold in CONDITIONS.items():
        require(sources["sha256"]["artifacts/measurement/multitone/y_"+condition+".memh"] ==
                cases[condition]["output_sha256"], "FPGA output-ROM identity differs")
        selected = [event for event in events if event.get("event") == "trial_complete" and
                    event.get("condition") == condition and event.get("epochs") == 1]
        require(len(selected) == 1, "Expected one historical single-record admission per threshold")
        event = selected[0]
        require(event["completed"] is True and event["threshold2"] == threshold and
                event["outputs"] == 1536 and event["useful_inputs"] == 1024 and event["frames"] == 9 and
                event["mismatch_count"] == 0 and event["fault_flags"] == 0 and
                event["last_epoch_outputs"] == 1536 and event["cycles"] == 88524 and
                event["last_epoch_cycles"] == 88138, "Historical one-record counters differ from reviewed contract")
        words = probe_words(event["probe_hex"])
        mode = 1 if condition == "dense" else 2
        require(words[0] == 0x54524350 and words[1] >> 24 == 1 and words[1] & 0x44d == 0 and
                words[1] & 0x82 == 0x82 and words[1] & 0x30 == (0x10 if mode == 1 else 0x20),
                "Historical terminal protocol/status is invalid")
        require(words[2] & 0xffff0003 == (1 << 16) | mode and
                words[3:8] == [1, 1536, 0, 1024, 9] and
                (words[9] << 32 | words[8]) == event["cycles"] and
                words[10:14] == [0xffffffff, 0, 1536, 88138], "Historical raw probe disagrees with decoded counters")
        results[condition] = {"condition": condition, "threshold2": threshold, "epochs": 1,
                              "cycles": event["cycles"], "nominal_clock_hz": 50_000_000,
                              "nominal_wall_s": event["cycles"]/50_000_000,
                              "mismatch_count": 0, "fault_flags": 0,
                              "raw_probe_hex": event["probe_hex"], "source_trial_id": event["trial_id"],
                              "source_launch_utc_ms": event["launch_before_ms"],
                              "source_completion_utc_ms": event["completion_after_ms"],
                              "input_sha256": cases[condition]["input_sha256"],
                              "reference_output_sha256": cases[condition]["output_sha256"]}
    provenance = {"jtag_receipts_sha256": sha(jtag), "campaign_manifest_sha256": sha(campaign_path),
                  "program_manifest_sha256": sha(program_path), "build_admission_sha256": sha(admission_path),
                  "source_manifest_sha256": sha(source_path), "sof_sha256": program["sof_sha256"].lower(),
                  "programmed_utc": program["finished_utc"], "historical_measurement": True,
                  "fresh_fpga_run_claimed": False, "fabric_clock_calibrated": False}
    return results, provenance


def admit_arm(board, metadata, vectors, cases):
    require(metadata["schema"] == "trecap-hps-physical-benchmark-receipt-1" and
            metadata["status"] == "PASS_PHYSICAL_BOARD_CAPTURE" and
            metadata["physical_board_attested"] is True and
            metadata["platform"] == "DE1-SoC HPS Cortex-A9", "Physical HPS receipt is missing or not admitted")
    require(valid_hash(metadata["executable_sha256"]) and bool(metadata["source_sha256"]) and
            all(valid_hash(value) for value in metadata["source_sha256"].values()), "Missing executable/source identities")
    require(metadata["vector_manifest_sha256"] == sha(vectors/"manifest.json"), "Board vector identity differs")
    require(metadata["input_sha256"] == cases["dense"]["input_sha256"], "ARM input identity differs")
    reference = read_json(vectors/"manifest.json")
    for name in COEFFICIENTS:
        require(metadata["coefficient_sha256"][name] == reference["source_sha256"]["artifacts/coefficients/"+name],
                "ARM coefficient identity differs: " + name)
    require(isinstance(metadata["clock_metadata"], dict) and bool(metadata["clock_metadata"]),
            "Clock metadata must state its source or explicit unavailability")
    results = {}
    for condition, threshold in CONDITIONS.items():
        filename = "multitone_"+condition+".json"
        result_path = board/filename
        same_hash(result_path, metadata["result_sha256"][filename])
        require(metadata["expected_output_sha256"][condition] == cases[condition]["output_sha256"],
                "ARM expected-output identity differs")
        data = read_json(result_path)
        require(data["schema"] == "trecap-preallocated-cpu-benchmark-1" and
                data["status"] == "PASS_FUNCTIONAL_ADMISSION" and data["verify_only"] is False,
                "Result is not an admitted benchmark run")
        require(data["contract"] == CONTRACT and data["geometry"] == SHAPE and
                data["threshold2"] == threshold, "ARM algorithm/geometry/threshold mismatch")
        require(data["epochs_per_trial"] == 1 and data["trials"] == 30 and len(data["records"]) == 30 and
                data["warmup_epochs"] >= 1 and data["timed_total_epochs"] == 30 and
                data["timed_input_samples"] == 30*1024 and data["timed_output_samples"] == 30*1536 and
                data["timed_frames"] == 30*9, "Expected 30 warmed single-record trials")
        environment = data["environment"]
        require(environment["compile_architecture"] == "arm32" and
                environment["uname"]["machine"] == "armv7l" and environment["uname"]["sysname"] == "Linux" and
                environment["requested_cpu"] == 0 and environment["requested_affinity_applied_and_read_back"] is True and
                environment["allowed_cpus"] == [0] and environment["cpu_at_metadata_collection"] == 0,
                "Run is not an admitted CPU0-pinned arm32 Linux execution")
        require(environment["cpuinfo_selected"]["CPU part"].lower() == "0xc09", "Observed CPU part is not Cortex-A9")
        validation = data["validation"]
        require(validation["mismatches"] == 0 and validation["internal_ranges_checked_outside_timing"] is True and
                validation["last_timed_epoch_checked_each_record"] is True and
                validation["all_timed_epochs_individually_full_checked"] is True and
                validation["full_output_samples_checked_outside_timing"] == (2+3*30)*1536,
                "Full checked/fast/per-trial output admission is incomplete")
        require(validation["timed_kernel_internal_guards"] is False, "Unexpected timed kernel variant")
        timing = data["timing"]
        require(timing["wall_clock"] in ("CLOCK_MONOTONIC_RAW", "CLOCK_MONOTONIC") and
                timing["thread_cpu_clock"] == "CLOCK_THREAD_CPUTIME_ID" and
                timing["thread_timer_encloses_wall_timer"] is True,
                "Unsupported timing clocks/boundaries")
        integer(timing["wall_resolution_ns"], "wall clock resolution", 1)
        integer(timing["thread_cpu_resolution_ns"], "thread clock resolution", 1)
        require(timing["includes"] == ["per-epoch logical state reset", "all finite input/tail/output work",
                                      "one opaque O(1) output consumer per epoch"] and
                timing["excludes"] == ["file I/O", "allocations", "full output comparison", "coefficient validation",
                                      "reference quality/telemetry metric aggregation", "host transfers/JTAG"],
                "Timing boundary differs from reviewed implementation")
        for index, record in enumerate(data["records"], 1):
            require(record["trial"] == index and record["epochs"] == 1 and
                    record["full_pre_post_validation"] is True, "Trial identity/check status mismatch")
            integer(record["wall_ns"], "wall elapsed nanoseconds", 1)
            integer(record["thread_cpu_ns"], "thread CPU nanoseconds", 1)
            integer(record["checksum"], "output consumer checksum")
            require(math.isclose(finite(record["wall_s"], "wall seconds"), record["wall_ns"]/1e9, abs_tol=1e-12) and
                    finite(record["wall_ns_per_epoch"], "normalized wall time") == record["wall_ns"],
                    "Inconsistent timer units/normalization")
        require(data["records"][-1]["checksum"] == data["final_consumer_checksum"], "Consumer receipt mismatch")
        results[condition] = data
    return results


def make_plots(out, summary, rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "savefig.facecolor": "white"})
    maroon, gold, ink = "#8C1D40", "#FFC627", "#29272B"
    figure, axes = plt.subplots(1, 2, figsize=(12.2, 5.8))
    figure.subplots_adjust(left=.075, right=.98, bottom=.19, top=.78, wspace=.28)
    for index, condition in enumerate(CONDITIONS):
        cpu = [row for row in rows if row["condition"] == condition]
        for axis, key, fpga_value in ((axes[0], "wall_ms", summary[condition]["fpga_nominal_latency_ms"]),
                                      (axes[1], "useful_inputs_per_s", summary[condition]["fpga_nominal_useful_inputs_per_s"])):
            factor = 1 if key == "wall_ms" else .001
            values = [row[key]*factor for row in cpu]
            center = index*2
            axis.scatter([center+((i%7)-3)*.025 for i in range(len(values))], values,
                         color=maroon, alpha=.45, s=20, zorder=3)
            q1, median, q3 = percentile(values, .25), statistics.median(values), percentile(values, .75)
            axis.vlines(center, min(values), max(values), color=maroon, alpha=.6, lw=1.2)
            axis.vlines(center, q1, q3, color=maroon, lw=8, alpha=.25)
            axis.hlines(median, center-.17, center+.17, color=maroon, lw=2.5)
            axis.scatter([center+.65], [fpga_value*factor], marker="D", s=90,
                         color=gold, edgecolors=ink, zorder=4)
            axis.axvspan(center-.3, center+.95, color=(maroon if index == 0 else gold), alpha=.045)
        entry = summary[condition]
        axes[0].text(index*2+.325, .97,
                     f"HPS median {entry['arm_wall_latency_ms']['median']:.3f} ms\n"
                     f"FPGA {entry['fpga_nominal_latency_ms']:.3f} ms\n"
                     f"HPS/FPGA {entry['arm_median_wall_over_fpga_nominal_time']:.3f}×",
                     ha="center", va="top", transform=axes[0].get_xaxis_transform(), fontsize=9,
                     bbox={"facecolor": "white", "alpha": .9, "edgecolor": "none", "pad": 3})
        axes[1].text(index*2+.325, .97,
                     f"HPS median {entry['arm_useful_inputs_per_s']['median']/1000:.1f} k/s\n"
                     f"FPGA {entry['fpga_nominal_useful_inputs_per_s']/1000:.1f} k/s",
                     ha="center", va="top", transform=axes[1].get_xaxis_transform(), fontsize=9,
                     bbox={"facecolor": "white", "alpha": .9, "edgecolor": "none", "pad": 3})
    for axis in axes:
        axis.set_xticks([.325, 2.325], ["Dense · THR²=0", "Masked · THR²=10¹¹"])
        axis.grid(axis="y", alpha=.2)
    axes[0].set_ylim(0, 1.42*max([row['wall_ms'] for row in rows] +
                                [entry['fpga_nominal_latency_ms'] for entry in summary.values()]))
    axes[1].set_ylim(0, 1.34*max([row['useful_inputs_per_s']/1000 for row in rows] +
                                [entry['fpga_nominal_useful_inputs_per_s']/1000 for entry in summary.values()]))
    axes[0].set_title("Complete-record processing latency", loc="left", color=maroon, fontweight="bold")
    axes[0].set_ylabel("Elapsed time per 1,024-input record (ms)")
    axes[1].set_title("Useful-input processing rate", loc="left", color=maroon, fontweight="bold")
    axes[1].set_ylabel("Thousand useful input samples/s (finite records)")
    figure.legend(handles=[Patch(facecolor=maroon, alpha=.5, label="HPS CPU0: 30 wall-time observations; median and IQR"),
                           Patch(facecolor=gold, edgecolor=ink, label="Historical FPGA: one admitted fabric-cycle result")],
                  loc="upper center", bbox_to_anchor=(.5, .935), ncol=2, frameon=False, fontsize=9)
    figure.suptitle("Resident-input finite-record comparison", color=ink, fontsize=16, y=.99)
    figure.supxlabel("All 1,536 outputs included. FPGA clock is nominal 50 MHz. Timing boundaries differ as described in the report.", fontsize=9, y=.04)
    figure.savefig(out/"latency_throughput.png", dpi=220)
    figure.savefig(out/"latency_throughput.pdf")
    plt.close(figure)


def replot_admitted(summary_path, out, no_plots, trials_path=None):
    """Recalculate a published numerical report; do not re-admit its hardware."""
    result = read_json(summary_path)
    require(result["schema"] == "trecap-hps-fpga-resident-record-comparison-1" and
            result["status"] == "PASS_MATCHED_WORKLOAD_ADMISSION", "Source is not an admitted comparison summary")
    require(result["end_to_end_offload_claim"] is False and result["energy_claim"] is False and
            result["fresh_fpga_measurement_claim"] is False, "Source scope is incompatible with report-only reproduction")
    csv_path = trials_path or summary_path.with_name("arm_trials.csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        raw_rows = list(csv.DictReader(stream))
    require(len(raw_rows) == 60, "Report reproduction needs all 60 trial observations")
    rows = []
    for raw in raw_rows:
        row = {key: int(raw[key]) for key in ("threshold2", "trial", "epochs", "input_samples",
                                              "output_samples", "frames", "wall_ns", "thread_cpu_ns")}
        row["condition"] = raw["condition"]
        require(row["condition"] in CONDITIONS and row["threshold2"] == CONDITIONS[row["condition"]] and
                row["epochs"] == 1 and row["input_samples"] == 1024 and row["output_samples"] == 1536 and
                row["frames"] == 9 and row["wall_ns"] > 0 and row["thread_cpu_ns"] > 0 and
                raw["full_output_checked"] == "True", "Invalid published trial/count/check fields")
        row.update(wall_ms=row["wall_ns"]/1e6,
                   useful_inputs_per_s=1024/(row["wall_ns"]/1e9), full_output_checked=True)
        fpga = result["fpga"][row["condition"]]
        require(fpga["epochs"] == 1 and fpga["cycles"] == 88524 and fpga["nominal_clock_hz"] == 50_000_000,
                "Published FPGA record/clock geometry changed")
        row["arm_wall_over_fpga_nominal_time"] = row["wall_ns"]/1e9/(fpga["cycles"]/fpga["nominal_clock_hz"])
        for key in ("wall_ms", "useful_inputs_per_s", "arm_wall_over_fpga_nominal_time"):
            supplied = float(raw[key])
            require(math.isfinite(supplied) and math.isclose(supplied, row[key], rel_tol=1e-12, abs_tol=1e-12),
                    "Published trial numerical identity mismatch: " + key)
        rows.append(row)
    recomputed = {}
    for condition, threshold in CONDITIONS.items():
        selected = [row for row in rows if row["condition"] == condition]
        require([row["trial"] for row in selected] == list(range(1, 31)), "Missing, duplicate or reordered published trials")
        fpga = result["fpga"][condition]
        words = probe_words(fpga["raw_probe_hex"])
        require((words[9] << 32 | words[8]) == fpga["cycles"], "Published FPGA probe/cycles mismatch")
        fpga_ms = fpga["cycles"]/fpga["nominal_clock_hz"]*1000
        times = [row["wall_ms"] for row in selected]
        recomputed[condition] = {"threshold2": threshold, "arm_wall_latency_ms": describe(times),
                                "arm_thread_cpu_latency_ms": describe([row["thread_cpu_ns"]/1e6 for row in selected]),
                                "arm_useful_inputs_per_s": describe([row["useful_inputs_per_s"] for row in selected]),
                                "fpga_cycles": fpga["cycles"], "fpga_nominal_latency_ms": fpga_ms,
                                "fpga_nominal_useful_inputs_per_s": 1024/(fpga["cycles"]/fpga["nominal_clock_hz"]),
                                "arm_median_wall_over_fpga_nominal_time": statistics.median(times)/fpga_ms,
                                "observed_arm_wall_over_fpga_nominal_range": [min(times)/fpga_ms, max(times)/fpga_ms],
                                "ratio_interpretation": "Above 1 means shorter FPGA service time; below 1 means shorter ARM service time"}
    require(recomputed == result["conditions"], "Published summary does not match recalculated trial statistics")
    portable(json.dumps(result, allow_nan=False))
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/"comparison_summary.json", result)
    write_csv(out/"arm_trials.csv", rows)
    if not no_plots:
        make_plots(out, recomputed, rows)
    ratios = "\n".join(f"| {condition} | {entry['arm_wall_latency_ms']['median']:.4f} | {entry['fpga_nominal_latency_ms']:.5f} | {entry['arm_median_wall_over_fpga_nominal_time']:.3f}× |"
                       for condition, entry in recomputed.items())
    readme = f"""# Reproduction of admitted HPS/FPGA timing numbers

All 60 published CPU observations were checked against their counts, units and admitted summary. Latency statistics, finite-record useful-input rates and HPS/FPGA ratios were recalculated exactly. Source summary and CSV hashes are recorded in this reproduction's manifest. This mode does not depend on the original publication-manifest schema.

| Condition | HPS median wall time (ms) | Historical FPGA nominal time (ms) | HPS/FPGA time ratio |
| --- | ---: | ---: | ---: |
{ratios}

This is report-only reproduction. It does not repeat physical acquisition, validate the original transfer/build/program receipts, or independently re-attest board identity. It relies on the prior admitted summary and its historical FPGA probe. Source identities remain in `comparison_summary.json`. The original timing-boundary, clock-accuracy and workload limitations still apply. No new hardware, energy or end-to-end offload claim is made.

```text
python analyze_board_results.py --summary comparison_summary.json --trials arm_trials.csv --out NEW_REPORT_DIRECTORY
```

If `--trials` is omitted, the source summary must have `arm_trials.csv` beside it. `--replot-summary` is an alias for `--summary`. Python and Matplotlib are sufficient for plots; `--no-plots` needs only the standard library. No ignored local acquisition directory or FPGA binary is needed in this mode.
"""
    if not no_plots:
        readme += "\n![Reproduced latency and useful-input rates](latency_throughput.png)\n\n[Vector PDF](latency_throughput.pdf).\n"
    (out/"README.md").write_text(portable(readme), encoding="utf-8")
    write_json(out/"publication_manifest.json", {
        "schema": "trecap-hps-fpga-timing-publication-1", "status": "PASS_REPORT_REPRODUCTION_ONLY",
        "hardware_readmission_performed": False, "analyzer_sha256": sha(Path(__file__)),
        "source_summary_sha256": sha(summary_path), "source_trial_csv_sha256": sha(csv_path),
        "files": {path.relative_to(out).as_posix(): sha(path) for path in sorted(out.rglob("*")) if path.is_file()}})
    print(json.dumps({"status": "PASS_REPORT_REPRODUCTION_ONLY", "observations": 60,
                      "recalculated_statistics_match": True, "hardware_readmission_performed": False}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-dir", type=Path)
    parser.add_argument("--vectors", type=Path)
    parser.add_argument("--fpga-jtag", type=Path)
    parser.add_argument("--replot-summary", "--summary", dest="replot_summary", type=Path,
                        help="Recalculate/plot an admitted summary and its sibling arm_trials.csv; no hardware re-admission")
    parser.add_argument("--trials", type=Path, help="Optional CSV path for report-only reproduction")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args(argv)
    require(not args.out.exists(), "Output directory must be fresh")
    if args.replot_summary:
        require(not any((args.board_dir, args.vectors, args.fpga_jtag)), "Report-only mode cannot mix acquisition arguments")
        return replot_admitted(args.replot_summary.resolve(), args.out.resolve(), args.no_plots,
                              args.trials.resolve() if args.trials else None)
    require(args.trials is None, "--trials is only valid with --summary/--replot-summary")
    require(all((args.board_dir, args.vectors, args.fpga_jtag)), "Full admission requires --board-dir, --vectors and --fpga-jtag")
    board, vector_dir, jtag, out = [path.resolve() for path in (args.board_dir, args.vectors, args.fpga_jtag, args.out)]
    require(not out.exists(), "Output directory must be fresh")
    metadata_path = board/"metadata.json"
    metadata = read_json(metadata_path)
    vectors, cases = admit_vectors(vector_dir)
    fpga, fpga_provenance = admit_fpga(jtag, cases, vectors)
    arm = admit_arm(board, metadata, vector_dir, cases)
    source_identities = {metadata_path: sha(metadata_path), vector_dir/"manifest.json": sha(vector_dir/"manifest.json"),
                         jtag: sha(jtag), **{board/("multitone_"+condition+".json"): sha(board/("multitone_"+condition+".json"))
                                         for condition in CONDITIONS}}
    rows, summary = [], {}
    for condition in CONDITIONS:
        times = [record["wall_ns"]/1e6 for record in arm[condition]["records"]]
        rates = [1024/(record["wall_ns"]/1e9) for record in arm[condition]["records"]]
        fpga_ms = fpga[condition]["nominal_wall_s"]*1000
        summary[condition] = {"threshold2": CONDITIONS[condition], "arm_wall_latency_ms": describe(times),
                              "arm_thread_cpu_latency_ms": describe([record["thread_cpu_ns"]/1e6 for record in arm[condition]["records"]]),
                              "arm_useful_inputs_per_s": describe(rates), "fpga_cycles": fpga[condition]["cycles"],
                              "fpga_nominal_latency_ms": fpga_ms,
                              "fpga_nominal_useful_inputs_per_s": 1024/fpga[condition]["nominal_wall_s"],
                              "arm_median_wall_over_fpga_nominal_time": statistics.median(times)/fpga_ms,
                              "observed_arm_wall_over_fpga_nominal_range": [min(times)/fpga_ms, max(times)/fpga_ms],
                              "ratio_interpretation": "Above 1 means shorter FPGA service time; below 1 means shorter ARM service time"}
        for record in arm[condition]["records"]:
            rows.append({"condition": condition, "threshold2": CONDITIONS[condition], "trial": record["trial"],
                         "epochs": 1, "input_samples": 1024, "output_samples": 1536, "frames": 9,
                         "wall_ns": record["wall_ns"], "wall_ms": record["wall_ns"]/1e6,
                         "thread_cpu_ns": record["thread_cpu_ns"],
                         "useful_inputs_per_s": 1024/(record["wall_ns"]/1e9),
                         "arm_wall_over_fpga_nominal_time": record["wall_ns"]/1e6/fpga_ms,
                         "full_output_checked": True})
    public_environment = {condition: {key: arm[condition]["environment"][key] for key in
                          ("compile_architecture", "compiler", "cplusplus", "build_flags", "uname",
                           "requested_cpu", "requested_affinity_applied_and_read_back", "allowed_cpus",
                           "cpu_at_metadata_collection", "cpuinfo_selected")} for condition in CONDITIONS}
    result = {"schema": "trecap-hps-fpga-resident-record-comparison-1", "status": "PASS_MATCHED_WORKLOAD_ADMISSION",
              "scope": "Physical HPS CPU0 wall time versus historical FPGA fabric time for resident-input complete finite records",
              "end_to_end_offload_claim": False, "energy_claim": False, "fresh_fpga_measurement_claim": False,
              "clock_accuracy_calibrated": False, "conditions": summary, "fpga": fpga,
              "fpga_provenance": fpga_provenance, "arm_environment": public_environment,
              "physical_platform": metadata["platform"], "physical_board_attested_by_acquisition_receipt": True,
              "clock_metadata": metadata["clock_metadata"],
              "governor": metadata.get("governor"), "temperature": metadata.get("temperature"),
              "provenance": {"board_receipt_sha256": sha(metadata_path), "executable_sha256": metadata["executable_sha256"],
                             "source_sha256": metadata["source_sha256"], "result_sha256": metadata["result_sha256"],
                             "vector_manifest_sha256": sha(vector_dir/"manifest.json"), "analyzer_sha256": sha(Path(__file__))},
              "statistics": {"quantiles": "Linear interpolation at (n-1)*p", "intervals": "IQR and observed range, not confidence intervals",
                             "fpga_replicates": "One historical E=1 admission per threshold; no invented distribution"},
              "timing_boundaries": {"arm": arm["dense"]["timing"],
                                    "fpga_includes": ["accepted batch command to terminal checked completion", "batch clear/init", "per-record startup and full tail",
                                                      "parallel on-chip reference comparison and metrics", "completion/checker drain"],
                                    "fpga_excludes": ["JTAG host latency", "ARM-to-FPGA input transfer", "FPGA-to-ARM output transfer"]}}
    # Fail before creating the publication if selected metadata is not portable.
    portable(json.dumps(result, allow_nan=False))
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/"comparison_summary.json", result)
    write_csv(out/"arm_trials.csv", rows)
    write_json(out/"historical_fpga_admissions.json", {"provenance": fpga_provenance, "conditions": fpga})
    if not args.no_plots:
        make_plots(out, summary, rows)
    table = "\n".join(f"| {condition} | {entry['arm_wall_latency_ms']['median']:.4f} | {entry['arm_wall_latency_ms']['q1']:.4f}–{entry['arm_wall_latency_ms']['q3']:.4f} | {entry['fpga_nominal_latency_ms']:.5f} | {entry['arm_median_wall_over_fpga_nominal_time']:.3f}× |"
                      for condition, entry in summary.items())
    rates = "\n".join(f"| {condition} | {entry['arm_useful_inputs_per_s']['median']:,.1f} | {entry['fpga_nominal_useful_inputs_per_s']:,.1f} |"
                      for condition, entry in summary.items())
    report = f"""# HPS and FPGA resident-input finite-record timing

These results compare a physical DE1-SoC Cortex-A9 CPU0 run with the admitted historical FPGA measurement image. They measure complete 1,024-input records with nine frames and 1,536 reconstructed outputs, including startup and tail. Input, five coefficient tables, threshold and expected output identities match the independent qualification vectors.

| Condition | HPS median wall time (ms) | HPS interquartile range (ms) | Historical FPGA nominal time (ms) | HPS/FPGA time ratio |
| --- | ---: | ---: | ---: | ---: |
{table}

A ratio above one means the FPGA has shorter processing service time; below one means the HPS implementation has shorter service time. Ratios use HPS median wall time divided by FPGA cycles at nominal 50 MHz. They describe these implementations and this workload, not a general processor capability or an end-to-end accelerator speedup. Quartiles show the spread of 30 observations per threshold and are not confidence intervals.

| Condition | HPS median useful input samples/s | Historical FPGA nominal useful input samples/s |
| --- | ---: | ---: |
{rates}

Rates divide the 1,024 useful inputs by complete-record processing time. They are finite-record processing rates, not a measured continuously paced stream rate or frame latency.

## What the timers include

The HPS benchmark uses preallocated workspace, resident input and coefficients, one pinned CPU, checked priming and warmup. Every timed trial executes one complete record, including logical state reset and an opaque output consumer. All 1,536 timed output values are checked after its timer stops. Range-checked executions before and after the trial verify the admitted workload; arithmetic guards, reference comparisons, quality metrics, file operations and allocation are outside the timed region. Wall time is the comparison metric; thread CPU time is retained separately and includes its enclosing timestamp calls.

The historical FPGA cycle counter runs from accepted shell command through terminal exact completion. Its 88,524 clocks include batch clear/init, all finite-record startup/tail work, parallel on-chip output checking/metrics and completion drain. It excludes JTAG latency and transfers between HPS memory and FPGA memory. **This boundary differs from the CPU datapath timer:** hardware checking and metrics remain active inside FPGA time while CPU comparisons and metrics are excluded. The result is a disclosed service-time comparison, not two identical instruction-level kernels.

The FPGA's repeated-record increment of 88,138 clocks is not substituted for the observed one-record result. No fresh FPGA run is claimed. FPGA timing belongs to the historical image identified by SHA-256 `{fpga_provenance['sof_sha256']}` and its retained programming/campaign receipts. The currently booted HPS software does not attest that image is presently loaded.

## Admission and interpretation limits

Both physical HPS conditions completed 30 single-record timing trials with exact full-output checks, CPU0 affinity applied and read back, arm32/armv7l execution and Cortex-A9 CPU identity. The executable/source and transferred input/expected/coefficient hashes are bound by the physical acquisition receipt. Native host qualification is separate and is not used as board timing evidence.

Clock-framework readings, governor availability and temperature availability are retained in [the summary](comparison_summary.json). A reported CPU clock rate is not an oscilloscope calibration; missing governor or thermal interfaces are not replaced with assumed values. The FPGA time uses nominal 50 MHz. No confidence interval or calibrated uncertainty is asserted for the ratio.

Thirty successive observations of an immutable workload with checked priming describe warmed local-memory execution. Operating-system interruptions can affect wall time and are retained in the individual observations. This experiment does not measure input transfer, launch/synchronization overhead, output return, application latency, energy, or a multicore/NEON-tuned CPU performance limit. It supports no energy-saving claim.

## Evidence

- [Summary, environment and source identities](comparison_summary.json).
- [All 60 HPS timing observations](arm_trials.csv).
- [Historical FPGA admissions and raw probes](historical_fpga_admissions.json).

"""
    if not args.no_plots:
        report += "![Latency and useful-input processing rate](latency_throughput.png)\n\n[Vector PDF](latency_throughput.pdf).\n\n"
    report += "Reproduce the published numbers and plots with `python analyze_board_results.py --summary comparison_summary.json --trials arm_trials.csv --out NEW_REPORT_DIRECTORY`. This mode checks all CSV observations against the admitted summary, recomputes the statistics and does not re-admit hardware. No ignored acquisition files, FPGA binary or original publication-manifest schema are required.\n\nRepeat the original evidence admission with `python analyze_board_results.py --board-dir BOARD_RESULTS --vectors QUALIFICATION_VECTORS --fpga-jtag HISTORICAL_JTAG_JSONL --out NEW_REPORT_DIRECTORY`. The board directory contains `metadata.json`, `multitone_dense.json` and `multitone_masked.json`; historical source/build/program receipts must remain beside the original JTAG campaign. Matplotlib is required for figures; use `--no-plots` for numerical admission only.\n"
    (out/"README.md").write_text(portable(report), encoding="utf-8")
    for path, expected in source_identities.items():
        same_hash(path, expected)
    publication = {"schema": "trecap-hps-fpga-timing-publication-1", "status": "PASS",
                   "analyzer_sha256": sha(Path(__file__)),
                   "files": {path.relative_to(out).as_posix(): sha(path) for path in sorted(out.rglob("*")) if path.is_file()}}
    write_json(out/"publication_manifest.json", publication)
    print(json.dumps({"status": "PASS_MATCHED_WORKLOAD_ADMISSION", "arm_trials": 60,
                      "fpga_admissions": 2, "ratios": {condition: entry["arm_median_wall_over_fpga_nominal_time"] for condition, entry in summary.items()}}))


if __name__ == "__main__":
    main()
