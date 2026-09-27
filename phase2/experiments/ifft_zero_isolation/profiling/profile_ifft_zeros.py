#!/usr/bin/env python3
"""Profile exact-zero opportunities in the current iterative radix-2 IFFT.

The existing recursive integer oracle supplies masked spectra and expected
IFFT/output values. This script independently replays the RTL's bit-reversed
load and stage/base/j butterfly order, including integer ties-away rounding.
It does not run hardware or predict measured electrical energy savings.
"""

import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


THRESHOLDS = (0, 10**8, 10**9, 10**10, 10**11, 10**12, 10**13, (1 << 56)-1)
COUNTERS = ("total_butterflies", "a_complex_zero", "b_complex_zero", "both_complex_zero",
            "neither_complex_zero", "a_re_zero", "a_im_zero", "b_re_zero", "b_im_zero",
            "twiddle_axis_trivial", "twiddle_identity", "b_zero_axis_twiddle",
            "b_zero_nontrivial_twiddle", "real_products_zero", "total_real_products")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def memh(path, width, signed=True):
    words = [int(value, 16) for value in path.read_text().split()]
    if not all(0 <= value < (1 << width) for value in words):
        raise ValueError("Out-of-range memory word in " + path.name)
    return [value-(1 << width) if signed and value >= (1 << (width-1)) else value for value in words]


def encoded_samples(values):
    if not all(-2048 <= value < 2048 for value in values):
        raise ValueError("Input/output sample does not fit signed12")
    return "".join(f"{value & 0xfff:03x}\n" for value in values).encode("ascii")


def rounded_q15(value):
    # Independent formulation: magnitude bias then shift; exact ties go away.
    magnitude = (abs(value) + (1 << 14)) >> 15
    return -magnitude if value < 0 else magnitude


def fit36(value):
    if not -(1 << 35) <= value < (1 << 35):
        raise ValueError("36-bit IFFT internal overflow")
    return value


def complex_hash(values):
    content = "".join(f"{re},{im}\n" for re, im in values).encode("ascii")
    return hashlib.sha256(content).hexdigest()


def iterative_ifft(values, inverse):
    if len(values) != 256 or len(inverse) != 256:
        raise ValueError("This profile requires the current 256-point geometry")
    memory = [(0, 0)] * 256
    for index, value in enumerate(values):
        address = 0
        for bit in range(8):
            address = (address << 1) | ((index >> bit) & 1)
        memory[address] = value
    stages = []
    for stage in range(1, 9):
        span, half = 1 << stage, 1 << (stage-1)
        counts = {name: 0 for name in COUNTERS}
        for base in range(0, 256, span):
            for j in range(half):
                ar, ai = memory[base+j]
                br, bi = memory[base+j+half]
                wr, wi = inverse[j << (8-stage)]
                az, bz = (ar == 0 and ai == 0), (br == 0 and bi == 0)
                trivial = ((abs(wr) == 32768 and wi == 0) or
                           (wr == 0 and abs(wi) == 32768))
                flags = {"a_complex_zero": az, "b_complex_zero": bz,
                         "both_complex_zero": az and bz, "neither_complex_zero": not az and not bz,
                         "a_re_zero": ar == 0, "a_im_zero": ai == 0,
                         "b_re_zero": br == 0, "b_im_zero": bi == 0,
                         "twiddle_axis_trivial": trivial, "twiddle_identity": wr == 32768 and wi == 0,
                         "b_zero_axis_twiddle": bz and trivial,
                         "b_zero_nontrivial_twiddle": bz and not trivial}
                counts["total_butterflies"] += 1
                counts["total_real_products"] += 4
                counts["real_products_zero"] += sum(v == 0 for v in (br*wr, bi*wi, br*wi, bi*wr))
                for name, flag in flags.items():
                    counts[name] += int(flag)
                tr = fit36(rounded_q15(br*wr-bi*wi))
                ti = fit36(rounded_q15(br*wi+bi*wr))
                memory[base+j] = (fit36(ar+tr), fit36(ai+ti))
                memory[base+j+half] = (fit36(ar-tr), fit36(ai-ti))
        if counts["total_butterflies"] != 128:
            raise ValueError("Unexpected stage geometry")
        stages.append(counts)
    return memory, stages


def signals(repo, inverse):
    original_path = repo/"artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh"
    original = memh(original_path, 12)
    if len(original) != 1024:
        raise ValueError("Original measurement workload must have 1024 samples")
    tone = [rounded_q15(1100*inverse[(7*n) % 256][1] + 350*inverse[(23*n) % 256][1])
            for n in range(1024)]
    broadband, state = [], 0x2468ACE1
    for _ in range(1024):
        state ^= (state << 13) & 0xffffffff
        state ^= state >> 17
        state ^= (state << 5) & 0xffffffff
        state &= 0xffffffff
        broadband.append(state % 2801 - 1400)
    transient = [0]*1024
    for index, amplitude in ((127, 1536), (513, -1024), (900, 768)):
        transient[index] = amplitude
    transient[352:368], transient[368:384] = [1000]*16, [-1000]*16
    return [
        ("measured_multitone", original, "Original measured 1024-sample multitone; input artifact copied without changes."),
        ("tonal_two_bin", tone, "1100*sin(2*pi*7*n/256)+350*sin(2*pi*23*n/256), using frozen Q15 inverse twiddle sine and one ties-away Q15 round."),
        ("broadband_xorshift", broadband, "xorshift32 seed0x2468ACE1, shifts13/17/5, each sample=(state mod2801)-1400; deterministic broadband stress, not a physical noise recording."),
        ("transient_bipolar", transient, "Impulses x[127]=1536,x[513]=-1024,x[900]=768; x[352:368]=1000,x[368:384]=-1000; remaining samples zero."),
        ("zero_control", [0]*1024, "All-zero control to distinguish exact arithmetic zeros from threshold suppression flags."),
    ]


def table_writer(path, fields):
    handle = path.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    return handle, writer


def plots(stage_rows, cases, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    selected = [r for r in stage_rows if r["signal"] == "measured_multitone" and r["threshold2"] == 10**11]
    positions = list(range(1, 9))
    both = [100*r["both_complex_zero"]/r["total_butterflies"] for r in selected]
    only_b = [100*(r["b_complex_zero"]-r["both_complex_zero"])/r["total_butterflies"] for r in selected]
    fig, axes = plt.subplots(2, 1, figsize=(10, 7.5), layout="constrained", gridspec_kw={"height_ratios": [1, 1.2]})
    axes[0].bar(positions, both, color="#8C1D40", label="Both operands zero")
    axes[0].bar(positions, only_b, bottom=both, color="#FFC627", label="Only b is zero")
    axes[0].set(xticks=positions, ylim=(0, 100), ylabel="Butterflies (%)", xlabel="IFFT stage",
                title="Measured multitone, threshold 10¹¹: exact-zero operands before each butterfly")
    axes[0].legend(frameon=False, ncol=2, loc="upper right")
    axes[0].spines[["top", "right"]].set_visible(False)
    names = list(dict.fromkeys(r["signal"] for r in stage_rows))
    matrix = [[100*r["b_complex_zero"]/r["total_butterflies"] for r in stage_rows
               if r["signal"] == name and r["threshold2"] == 10**11] for name in names]
    cmap = LinearSegmentedColormap.from_list("soft_maroon", ["#FFF8DE", "#E4A8BC", "#8C1D40"])
    image = axes[1].imshow(matrix, vmin=0, vmax=100, aspect="auto", cmap=cmap)
    axes[1].set_xticks(range(8), positions)
    axes[1].set_yticks(range(len(names)), [n.replace("_", " ") for n in names])
    axes[1].set(xlabel="IFFT stage", title="b = 0 opportunities across deterministic inputs, threshold 10¹¹")
    for row, numbers in enumerate(matrix):
        for col, value in enumerate(numbers):
            axes[1].text(col, row, f"{value:.1f}", ha="center", va="center", fontsize=9,
                         color="white" if value > 65 else "#352C30")
    fig.colorbar(image, ax=axes[1], label="Butterflies with b = 0 (%)", shrink=.9)
    fig.supxlabel("Exact integer operation opportunities; no cycle or electrical-energy savings are inferred.", fontsize=9)
    fig.savefig(out/"ifft_zero_opportunities.png", dpi=200)
    fig.savefig(out/"ifft_zero_opportunities.pdf")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory; existing output is refused")
    parser.add_argument("--thresholds", nargs="+", type=int, default=list(THRESHOLDS))
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    if out.exists():
        parser.error("Output directory already exists")
    if len(set(args.thresholds)) != len(args.thresholds) or any(t < 0 or t >= 1 << 56 for t in args.thresholds):
        parser.error("Thresholds must be distinct unsigned56 integers")
    if not args.no_plots and 10**11 not in args.thresholds:
        parser.error("Default plot needs threshold100000000000; use --no-plots for a different sweep")
    # Prevent Python import-cache writes into the read-only canonical repository.
    sys.dont_write_bytecode = True
    oracle_path = repo/"scripts/verification/reference_integer_oracle.py"
    spec = importlib.util.spec_from_file_location("zero_study_integer_oracle", oracle_path)
    oracle = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = oracle
    spec.loader.exec_module(oracle)
    coeff = repo/"artifacts/coefficients"
    coefficient_files = [coeff/name for name in ("window_qw.memh", "twiddle_re.memh", "twiddle_im.memh", "twiddle_inv_re.memh", "twiddle_inv_im.memh")]
    window = memh(coefficient_files[0], 16, False)
    forward = list(zip(memh(coefficient_files[1], 17), memh(coefficient_files[2], 17)))
    inverse = list(zip(memh(coefficient_files[3], 17), memh(coefficient_files[4], 17)))
    source_files = [oracle_path, repo/"rtl/fft/trecap_ifft256.sv", repo/"rtl/fft/trecap_fft_stage.sv",
                    repo/"rtl/fft/complex_mul_q.sv", repo/"rtl/common/round_sat.sv", *coefficient_files,
                    repo/"artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh",
                    repo/"artifacts/measurement/multitone/y_dense.memh", repo/"artifacts/measurement/multitone/y_masked.memh"]
    source_hashes = {p.relative_to(repo).as_posix(): sha(p) for p in source_files}
    out.mkdir(parents=True)
    (out/"inputs").mkdir()
    (out/"outputs").mkdir()
    frame_handle, frame_csv = table_writer(out/"frame_stage_counts.csv", ["signal", "threshold2", "frame", "stage", *COUNTERS])
    mask_handle, mask_csv = table_writer(out/"bin_masks.csv", ["signal", "threshold2", "frame", "bin", "re", "im", "magnitude_squared", "eligible", "pre_mask", "mask"])
    frames_handle, frames_csv = table_writer(out/"frame_checks.csv", ["signal", "threshold2", "frame", "input_complex_zeros", "ifft_output_complex_zeros", "ifft_mismatches", "iterative_ifft_sha256", "oracle_ifft_sha256"])
    stage_rows, cases, signal_manifest = [], [], []
    try:
        for name, samples, definition in signals(repo, inverse):
            input_path = out/"inputs"/(name+".memh")
            input_path.write_bytes(encoded_samples(samples))
            signal_manifest.append({"signal": name, "definition": definition, "samples": len(samples),
                                    "input_file": input_path.relative_to(out).as_posix(), "sha256": sha(input_path),
                                    "min_sample": min(samples), "max_sample": max(samples),
                                    "nonzero_samples": sum(x != 0 for x in samples)})
            for threshold in args.thresholds:
                records = oracle.run(samples, threshold, window, forward, inverse)
                ns, frame_count, tau_last, ny = records[("G",)]
                aggregate = [{key: 0 for key in COUNTERS} for _ in range(8)]
                total_input_zeros, total_mismatches = 0, 0
                for frame in range(frame_count):
                    masked = [records[("S", frame, "masked", k)] for k in range(256)]
                    expected = [records[("S", frame, "ifft", k)] for k in range(256)]
                    actual, counts = iterative_ifft(masked, inverse)
                    mismatches = sum(a != b for a, b in zip(actual, expected))
                    total_mismatches += mismatches
                    if mismatches:
                        raise ValueError(f"Iterative/recursive IFFT mismatch: {name}, threshold{threshold}, frame{frame}")
                    input_zeros = sum(value == (0, 0) for value in masked)
                    total_input_zeros += input_zeros
                    frames_csv.writerow({"signal": name, "threshold2": threshold, "frame": frame,
                                         "input_complex_zeros": input_zeros,
                                         "ifft_output_complex_zeros": sum(value == (0, 0) for value in actual),
                                         "ifft_mismatches": mismatches, "iterative_ifft_sha256": complex_hash(actual),
                                         "oracle_ifft_sha256": complex_hash(expected)})
                    for stage, count in enumerate(counts, 1):
                        frame_csv.writerow({"signal": name, "threshold2": threshold, "frame": frame, "stage": stage, **count})
                        for key in COUNTERS:
                            aggregate[stage-1][key] += count[key]
                    for k in range(129):
                        re_, im, mag2, eligible, pre, mask = records[("B", frame, k)]
                        mask_csv.writerow({"signal": name, "threshold2": threshold, "frame": frame, "bin": k,
                                           "re": re_, "im": im, "magnitude_squared": mag2,
                                           "eligible": eligible, "pre_mask": pre, "mask": mask})
                for stage, counts in enumerate(aggregate, 1):
                    stage_rows.append({"signal": name, "threshold2": threshold, "stage": stage, **counts})
                totals = {key: sum(stage[key] for stage in aggregate) for key in COUNTERS}
                outputs = [records[("Y", n)][0] for n in range(ny)]
                output_path = out/"outputs"/f"{name}__thr2_{threshold}.memh"
                output_path.write_bytes(encoded_samples(outputs))
                original_match = None
                if name == "measured_multitone" and threshold in (0, 10**11):
                    fixture = repo/"artifacts/measurement/multitone"/("y_dense.memh" if threshold == 0 else "y_masked.memh")
                    original_match = outputs == memh(fixture, 12)
                    if not original_match:
                        raise ValueError("Original measurement reference ROM mismatch")
                errors = [(samples[n-384] if 384 <= n < len(samples)+384 else 0)-value for n, value in enumerate(outputs)]
                sq_error = sum(e*e for e in errors)
                if sq_error != records[("M", "sum_sq_err")][0] or max(map(abs, errors)) != records[("M", "max_abs_err")][0]:
                    raise ValueError("Independent reconstruction metric disagrees with oracle")
                case = {"signal": name, "threshold2": threshold, "input_samples": ns, "output_samples": ny,
                        "frames": frame_count, "tau_last": tau_last, "ifft_mismatches": total_mismatches,
                        "full_spectrum_complex_zeros": total_input_zeros, "full_spectrum_bins": frame_count*256,
                        "eligible_unique_bins": records[("M", "eligible_unique_bins")][0],
                        "suppressed_eligible_unique_bins": records[("M", "eligible_suppressed_bins")][0],
                        "rmse_full_stream_lsb": math.sqrt(sq_error/ny), "max_abs_error_lsb": max(map(abs, errors)),
                        "sum_sq_error": sq_error, "error_denominator": ny,
                        "output_file": output_path.relative_to(out).as_posix(), "output_sha256": sha(output_path),
                        "original_measurement_rom_match": original_match, **totals}
                case["b_complex_zero_fraction"] = totals["b_complex_zero"]/totals["total_butterflies"]
                case["both_complex_zero_fraction"] = totals["both_complex_zero"]/totals["total_butterflies"]
                cases.append(case)
                if name == "measured_multitone" and threshold in (0, 10**11):
                    frame_handle.flush()
                    print(json.dumps({"signal": name, "threshold2": threshold, "b_complex_zero": totals["b_complex_zero"],
                                      "both_complex_zero": totals["both_complex_zero"], "butterflies": totals["total_butterflies"],
                                      "b_zero_by_stage": [s["b_complex_zero"] for s in aggregate]}), flush=True)
    finally:
        frame_handle.close()
        mask_handle.close()
        frames_handle.close()
    for name, rows in (("stage_counts.csv", stage_rows), ("case_summary.csv", cases)):
        handle, writer = table_writer(out/name, list(rows[0]))
        try:
            writer.writerows(rows)
        finally:
            handle.close()
    if any(sha(repo/name) != expected for name, expected in source_hashes.items()):
        raise ValueError("Canonical profiling inputs changed during the run")
    manifest = {"schema": "ifft-zero-opportunity-profile-1", "status": "PASS", "cases": len(cases),
                "checked_ifft_frames": sum(c["frames"] for c in cases), "ifft_mismatches": sum(c["ifft_mismatches"] for c in cases),
                "thresholds": args.thresholds, "signals": signal_manifest,
                "source_sha256": source_hashes, "profiler_sha256": sha(Path(__file__)),
                "geometry": {"L": 256, "stages": 8, "butterflies_per_stage_per_frame": 128,
                             "fractional_bits": 15, "data_width": 36, "per_stage_normalization": False},
                "mask_rule": "eligible=(k!=0); masked iff eligible and (re*re+im*im)<threshold; conjugate partner uses same mask; Nyquist eligible",
                "error_reference": "12-bit reconstructed full stream minus input delayed384 samples, zero-padded outside input extent; RMSE denominator output_samples",
                "counting": "Count operands before each stage/base/j transaction; b is the twiddle-multiplied operand. Counters overlap and must not be added as disjoint savings.",
                "twiddle_trivial_definition": "Exact Q15 coefficients (+/-32768,0) or (0,+/-32768)",
                "real_products_definition": "Zero among br*wr,bi*wi,br*wi,bi*wr; four products per butterfly",
                "scope": "Model-level exact-zero opportunity study. Every iterative frame matches independent recursive oracle. No RTL, timing, area or electrical-energy claim."}
    if not args.no_plots:
        plots(stage_rows, cases, out)
    (out/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    (out/"README.md").write_text("""# IFFT exact-zero opportunity profile

This profile reproduces the current 256-point IFFT's bit-reversed load and iterative stage/base/j order. The recursive integer oracle supplies masked spectra and expected frame outputs. The profiler uses an independent ties-away rounding expression and checks every reconstructed complex frame exactly.

`case_summary.csv` gives whole-case counts and full-stream reconstruction error. `stage_counts.csv` aggregates each stage across frames; `frame_stage_counts.csv` supports direct comparison with an RTL transaction monitor. `frame_checks.csv` records every frame comparison and digest. `bin_masks.csv` preserves all unique-bin mask decisions, including protected DC and eligible Nyquist. Input and reconstructed output MEMH files are included with hashes in the manifest/tables.

The original measured multitone is accompanied by deterministic tonal, broadband, transient, and zero-control inputs. Synthetic inputs are defined by integer rules in `manifest.json`; they are stress cases, not a representative application corpus. Errors use the 384-sample-delayed, zero-padded input over the full output length.

`b_complex_zero` marks an exactly zero twiddle-multiplied operand. Its product is exactly zero, leaving butterfly outputs equal to a. `both_complex_zero` is a subset where both outputs also remain zero. Component-zero, axis-twiddle, and zero-real-product counts overlap these sets. A suppressed-bin percentage does not equal a skipped-butterfly percentage; values spread and cancel during later stages.

These are arithmetic opportunities, not energy savings or implemented skipped cycles. Any optimization still needs exact output/handshake/fault checks, synthesis/timing/resource comparison, and a matched board experiment at the same threshold and output quality. The FFT and other pipeline stages remain outside this IFFT profile.

Reproduce with `python profile_ifft_zeros.py --repo <repository> --out <new-directory>`; add `--no-plots` for standard-library-only operation. Plot generation additionally needs Matplotlib.
""", encoding="utf-8")
    print(json.dumps({"status": "PASS", "cases": len(cases), "checked_ifft_frames": manifest["checked_ifft_frames"],
                      "ifft_mismatches": manifest["ifft_mismatches"]}), flush=True)


if __name__ == "__main__":
    main()
