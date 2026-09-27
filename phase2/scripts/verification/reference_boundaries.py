# SPDX-License-Identifier: MIT
"""Supplemental short-length reference qualification; never rewrites frozen data.

Example (from the repository root):
  python scripts/verification/reference_boundaries.py \
    --baseline-reference-run runs/verification/reference-v1-20260915-05 \
    --adapter build/verification/reference-v1-20260915/Release/reference_api_adapter.exe

The supplied adapter must be byte-identical to the qualified baseline executable.
This campaign adds finite-geometry cases, not a new claim of full V1 signoff.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys

from reference_integer_oracle import METRIC_NAMES, rounded, run as predict
from reference_qualification import (
    BIN_FIELDS, FRAME_FIELDS, checked_path, compare, emit_oracle, emit_sv_header,
    parse_records, read_memh, sha, write_json,
)

LENGTHS = (1, 2, 126, 127, 128, 129, 130, 254, 255, 256, 257, 258,
           383, 384, 385, 386, 511, 512, 513, 514)
THRESHOLDS = (0, 1 << 43)
BASELINE = dict(N=12, L=256, P=8, H=128, F=15, G=128, D=384,
                PROTECT_DC=1, PROTECT_NYQ=0)
BUNDLE_FILES = {"y_out.memh", "frame_stats.csv", "bin_stats.csv", "metrics.json",
                "ifft_output.csv", "trecap_artifact_expectations_pkg.sv"}
QUALIFICATION_SOURCES = (
    "scripts/verification/reference_boundaries.py",
    "scripts/verification/reference_qualification.py",
    "scripts/verification/reference_integer_oracle.py",
    "sim/verification/reference_adapter/reference_api_adapter.cpp",
    "sim/verification/reference_adapter/CMakeLists.txt",
)


def read_json(path: Path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out

    def reject_constant(token):
        raise ValueError(f"nonfinite JSON token: {token}")

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=reject_constant)


def within(root: Path, path: Path) -> Path:
    result = (path if path.is_absolute() else root / path).resolve()
    result.relative_to(root)
    return result


def stimulus(ns: int) -> list[int]:
    """A common deterministic prefix with signed extremes and odd transition data.

    Every 32-sample tile begins with min/max, their neighbors, +/-1, zero,
    and half-range boundaries. The rest uses an integer-only nonperiodic-within-
    the-window pattern. All lengths share the same prefix, so length-pair
    comparisons isolate stopping geometry rather than replacing the waveform.
    """
    anchors = (-2048, 2047, -2047, 2046, -1, 1, 0, 1023, -1024)
    values = []
    for n in range(ns):
        slot = n % 32
        values.append(anchors[slot] if slot < len(anchors)
                      else ((73 * n + 19 * (n // 7)) % 1023) - 511)
    if not values or any(not -2048 <= v <= 2047 for v in values):
        raise ValueError("invalid supplemental sample domain")
    return values


def admit_baseline(root: Path, evidence: Path, adapter: Path):
    evidence.relative_to(root / "runs/verification")
    report = read_json(evidence / "report.json")
    if report.get("status") not in ("PASS_BOUNDED_BASELINE", "PASS_BOUNDED_BASELINE_WITH_PUBLIC_API_FINDINGS"):
        raise ValueError("baseline reference report is not qualified")
    if report.get("input_identity_unchanged") is not True:
        raise ValueError("baseline reference input identities did not remain unchanged")
    identity_file = evidence / "input_identities.json"
    if report.get("input_identities_sha256") != sha(identity_file):
        raise ValueError("baseline identity manifest digest mismatch")
    identities = read_json(identity_file)
    if not isinstance(identities, dict) or not identities:
        raise ValueError("missing baseline source/input inventory")
    qualified_sources = report.get("qualification_sources", {})
    required_sources = set(QUALIFICATION_SOURCES) - {QUALIFICATION_SOURCES[0]}
    if not required_sources <= qualified_sources.keys():
        raise ValueError("baseline qualification source inventory incomplete")
    for name, digest in qualified_sources.items():
        if identities.get(name) != digest:
            raise ValueError(f"baseline source/identity disagreement: {name}")
    for name, digest in identities.items():
        path = within(root, Path(name))
        if not path.is_file() or sha(path) != digest:
            raise ValueError(f"baseline qualified identity changed: {name}")
    if sha(adapter) != report.get("adapter_sha256"):
        raise ValueError("adapter differs from baseline-qualified executable")
    for name in ("independent_baseline_primitive_comparison", "checker_negative_witnesses",
                 "impulse_Ns1024_thr0", "near_threshold_multitone_Ns1024_thr64"):
        matched = [c for c in report["checks"] if c.get("name") == name]
        if len(matched) != 1 or matched[0].get("status") != "PASS":
            raise ValueError(f"missing unique baseline qualification: {name}")
    return report, identities


def export_and_check(directory: Path, records: dict, name: str, threshold: int,
                     input_hash: str) -> dict:
    emit_oracle(directory, records)
    ns, frames, _, ny = records[("G",)]
    values = read_memh(directory / "y_out.memh", 12, True, ny)
    if values != [records[("Y", n)][0] for n in range(ny)]:
        raise ValueError("exported y serialization mismatch")
    for filename, fields, kind in (("frame_stats.csv", FRAME_FIELDS, "F"),
                                    ("bin_stats.csv", BIN_FIELDS, "B"),
                                    ("ifft_output.csv", ("frame_idx", "offset", "re", "im"), "I")):
        raw = (directory / filename).read_bytes()
        if b"\r" in raw or not raw.endswith(b"\n"):
            raise ValueError(f"noncanonical CSV newline: {filename}")
        with (directory / filename).open(newline="", encoding="ascii") as stream:
            reader = csv.reader(stream)
            if tuple(next(reader)) != fields:
                raise ValueError(f"unexpected CSV header: {filename}")
            observed = [tuple(map(int, row)) for row in reader]
        if kind == "I":
            expected = [(f, i) + records[("S", f, "ifft", i)]
                        for f in range(frames) for i in range(256)]
        else:
            expected = [key[1:] + value for key, value in records.items() if key[0] == kind]
        if observed != expected:
            raise ValueError(f"exported CSV serialization mismatch: {filename}")
    metrics = read_json(directory / "metrics.json")
    if metrics["geometry"] != dict(zip(("Ns", "Nframes", "tau_last", "Ny"), records[("G",)])):
        raise ValueError("exported metric geometry mismatch")
    for group, names in (("suppression_totals", METRIC_NAMES[:4]),
                         ("spectral_totals", METRIC_NAMES[4:6]),
                         ("time_domain_errors", METRIC_NAMES[6:])):
        if metrics[group] != {n: str(records[("M", n)][0]) for n in names}:
            raise ValueError(f"exported metric mismatch: {group}")
    emit_sv_header(directory, records, name, threshold, input_hash)
    files = list(directory.iterdir())
    if {p.name for p in files} != BUNDLE_FILES or any(not p.is_file() for p in files):
        raise ValueError("unexpected emitted oracle inventory")
    return {p.name: sha(p) for p in sorted(files)}


def summarize_numeric(records: dict) -> dict:
    _, frames, _, ny = records[("G",)]
    imaginary = [records[("S", f, "ifft", i)][1] for f in range(frames) for i in range(256)]
    # Inspect pre-final-saturation values independently of the oracle's clamped y.
    absolute_ola = defaultdict(int)
    for f in range(frames):
        for i in range(256):
            absolute_ola[(f + 1) * 128 + 128 + i] += records[("S", f, "z", i)][0]
    unclipped = [rounded(absolute_ola[n], 15) for n in range(ny)]
    return {"ifft_nonzero_imag_samples": sum(v != 0 for v in imaginary),
            "ifft_max_abs_imag": max(map(abs, imaginary)),
            "output_saturation_count": sum(not -2048 <= v <= 2047 for v in unclipped),
            "unique_suppressed_bins": str(records[("M", "unique_suppressed_bins")][0]),
            "eligible_suppressed_bins": str(records[("M", "eligible_suppressed_bins")][0]),
            "eligible_retained_bins": str(records[("M", "eligible_unique_bins")][0] - records[("M", "eligible_suppressed_bins")][0]),
            "sum_abs_err": str(records[("M", "sum_abs_err")][0]),
            "sum_sq_err": str(records[("M", "sum_sq_err")][0]),
            "max_abs_err": records[("M", "max_abs_err")][0]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--baseline-reference-run", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    root = args.repo.resolve()
    baseline_run = within(root, args.baseline_reference_run)
    adapter = within(root, args.adapter)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = checked_path(root, within(root, args.run_dir) if args.run_dir else
                            root / "runs/verification" / f"reference-boundaries-{stamp}", "runs/verification")
    evidence.mkdir(parents=True, exist_ok=False)
    names = [f"boundary_Ns{ns}_thr{thr}" for ns in LENGTHS for thr in THRESHOLDS]
    report = {"schema": "trecap_reference_qualification_v1", "campaign": "short_length_boundaries",
              "status": "RUNNING", "started_utc": stamp, "default_vectors": names,
              "all_V1_qualified": False, "checks": [], "python": platform.python_version(),
              "generator": {"id": "signed_boundary_prefix_v1", "lengths": list(LENGTHS),
                            "thresholds": [str(t) for t in THRESHOLDS], "seed": None,
                            "threshold_selection": "2^43 provides mixed eligible masks in18 of20 lengths and no final-output clipping;Ns1/2 retain protectedDC only",
                            "superseded_candidate": "THR2=4096 in reference-boundaries-20260915-01 suppressed no bins; geometry evidence only",
                            "selection_constraint": "keep the signed full-scale input prefix unchanged and require zero final-output saturations",
                            "rule": "shared prefix; 32-sample tile anchors then ((73*n+19*(n//7))%1023)-511",
                            "anchors": [-2048, 2047, -2047, 2046, -1, 1, 0, 1023, -1024]},
              "limitations": ["Supplemental generated vectors, not frozen normative rebaselining",
                              "Static thresholds only; no source/metric epochs, RTL, or board qualification",
                              "Shared frozen coefficient integers; no new transcendental-generation proof",
                              "Existing public shift>=63 reference defect remains outside baseline shifts",
                              "This increment does not establish all V1 requirements or quality bounds"]}
    identities, expected_inputs, before_ready = {}, {}, False
    try:
        qualified, identities = admit_baseline(root, baseline_run, adapter)
        identities = dict(identities)
        report.update(baseline_reference_run=baseline_run.relative_to(root).as_posix(),
                      baseline_reference_report_sha256=sha(baseline_run / "report.json"),
                      adapter_sha256=sha(adapter), public_api_findings=qualified.get("public_api_findings", []),
                      public_api_scope_status=qualified.get("public_api_scope_status", "NOT_REQUALIFIED"))
        additional = [root / p for p in QUALIFICATION_SOURCES]
        additional += [baseline_run / "report.json", baseline_run / "input_identities.json", adapter]
        for path in additional:
            identities[path.relative_to(root).as_posix()] = sha(path)
        core = read_json(root / "spec/generated/core_config.json")
        if any(core["configuration"].get(k) != v for k, v in BASELINE.items()):
            raise ValueError("unsupported baseline geometry/protection")
        coefficients = root / "artifacts/coefficients"
        tables = {name: read_memh(coefficients / f"{name}.memh", 16 if name == "window_qw" else 17,
                                  name != "window_qw", 256)
                  for name in ("window_qw", "twiddle_re", "twiddle_im", "twiddle_inv_re", "twiddle_inv_im")}
        window = tables["window_qw"]
        forward = list(zip(tables["twiddle_re"], tables["twiddle_im"]))
        inverse = list(zip(tables["twiddle_inv_re"], tables["twiddle_inv_im"]))
        # Materialize all deterministic input files before freezing the run inputs.
        for ns in LENGTHS:
            samples = stimulus(ns)
            for threshold in THRESHOLDS:
                name = f"boundary_Ns{ns}_thr{threshold}"
                input_dir = evidence / name / "input"
                input_dir.mkdir(parents=True)
                x_path = input_dir / "x_in.memh"
                x_path.write_bytes("".join(f"{v & 4095:03x}\n" for v in samples).encode("ascii"))
                if read_memh(x_path, 12, True, ns) != samples:
                    raise ValueError("generated input serialization mismatch")
                relative = x_path.relative_to(root).as_posix()
                identities[relative] = sha(x_path)
                expected_inputs[name] = (ns, threshold, x_path, samples)
        write_json(evidence / "input_identities.json", identities)
        report["input_identities_sha256"] = sha(evidence / "input_identities.json")
        report["qualification_sources"] = {p: identities[p] for p in QUALIFICATION_SOURCES}
        before_ready = True
        for name in names:
            ns, threshold, x_path, samples = expected_inputs[name]
            case_dir = evidence / name
            result = {"name": name, "status": "RUNNING",
                      "input_artifact": {"path": x_path.relative_to(root).as_posix(), "sha256": sha(x_path),
                                         "rows": ns, "width_bits": 12, "signed": True}}
            report["checks"].append(result)
            try:
                expected = predict(samples, threshold, window, forward, inverse)
                geometry = expected[("G",)]
                frames = (ns + 254) // 128
                if geometry != (ns, frames, frames * 128, frames * 128 + 384):
                    raise ValueError("independent window-support geometry disagrees with finite contract")
                result["configuration"] = dict(BASELINE, Ns=ns, Ny=geometry[3], frames=frames, THR2=str(threshold))
                command = [str(adapter), "run", str(coefficients), str(x_path), str(threshold)]
                try:
                    child = subprocess.run(command, cwd=root, text=True, encoding="utf-8", errors="strict",
                                           capture_output=True, timeout=90, check=False)
                except subprocess.TimeoutExpired as error:
                    for label, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                        raw = value if isinstance(value, bytes) else (value or "").encode("utf-8")
                        (case_dir / f"adapter.{label}.log").write_bytes(raw)
                    raise RuntimeError("reference adapter timed out after90s") from error
                (case_dir / "adapter.stdout.log").write_text(child.stdout, encoding="utf-8", newline="\n")
                (case_dir / "adapter.stderr.log").write_text(child.stderr, encoding="utf-8", newline="\n")
                result["adapter_exit_code"] = child.returncode
                if child.returncode:
                    raise RuntimeError(f"adapter exit{child.returncode}; see case logs")
                actual = parse_records(child.stdout)
                count = compare(expected, actual, name)
                observations = summarize_numeric(expected)
                if observations["output_saturation_count"]:
                    raise ValueError("boundary campaign requires zero final-output saturations")
                hashes = export_and_check(case_dir / "oracle", expected, name, threshold, sha(x_path))
                result.update(status="PASS", records=count, frames=frames, outputs=geometry[3], bins=frames * 129,
                              intermediate_complex_words=frames * 256 * 6, ifft_export_rows=frames * 256,
                              ifft_export_sha256=hashes["ifft_output.csv"], oracle_artifact_sha256=hashes,
                              numeric_observations=observations,
                              adapter_transcript_sha256=sha(case_dir / "adapter.stdout.log"))
                print(f"PASS {name}: frames={frames}, y={geometry[3]}, bins={frames*129}", flush=True)
            except (OSError, ValueError, RuntimeError) as error:
                result.update(status="FAIL", failure=str(error))
                print(f"FAIL {name}: {error}", file=sys.stderr, flush=True)
        passed = [c for c in report["checks"] if c["status"] == "PASS"]
        report["totals"] = {"cases": len(report["checks"]), "passed": len(passed),
                            "frames": sum(c["frames"] for c in passed), "outputs": sum(c["outputs"] for c in passed),
                            "bins": sum(c["bins"] for c in passed), "ifft_complex_words": sum(c["ifft_export_rows"] for c in passed),
                            "intermediate_complex_words": sum(c["intermediate_complex_words"] for c in passed)}
        report["status"] = "PASS_BOUNDED_BOUNDARY_VECTORS" if len(passed) == len(names) else "FAIL"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="FAIL", failure=str(error))
        print(f"FAIL campaign preflight: {error}", file=sys.stderr, flush=True)
    finally:
        changed = [p for p, digest in identities.items() if not (root / p).is_file() or sha(root / p) != digest]
        report["input_identity_unchanged"] = before_ready and not changed
        if not report["input_identity_unchanged"]:
            report["status"] = "FAIL"
            report["changed_inputs"] = changed
        # Retain input inventory even on preflight failure, without pretending it was qualified.
        if not before_ready:
            write_json(evidence / "input_identities.json", identities)
            report["input_identities_sha256"] = sha(evidence / "input_identities.json")
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(evidence / "report.json", report)
        lines = ["# Supplemental short-length reference qualification", "", "Status: " + report["status"], "",
                 "These deterministic generated vectors supplement the frozen suite; they do not replace it.", "",
                 "| Case | Result | Frames | Outputs | Bins | Nonzero IFFT imaginary | Output saturations |",
                 "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
        for case in report["checks"]:
            observation = case.get("numeric_observations", {})
            lines.append(f"| {case['name']} | {case['status']} | {case.get('frames', '-')} | {case.get('outputs', '-')} | {case.get('bins', '-')} | {observation.get('ifft_nonzero_imag_samples', '-')} | {observation.get('output_saturation_count', '-')} |")
            if case.get("failure"):
                lines.append("\nFailure: " + case["failure"] + "\n")
        lines += ["", "## Scope", ""] + ["- " + v for v in report["limitations"]]
        lines += ["", "Input identities unchanged: " + str(report["input_identity_unchanged"]),
                  "All V1 requirements qualified: false", ""]
        if report.get("failure"):
            lines += ["Failure: " + report["failure"], ""]
        (evidence / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("Evidence: " + str(evidence), flush=True)
    return 0 if report["status"] == "PASS_BOUNDED_BOUNDARY_VECTORS" else 1


if __name__ == "__main__":
    raise SystemExit(main())