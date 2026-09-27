#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run a supplied benchmark executable against frozen full-output oracle vectors.

This is functional qualification only. Running an x86 binary or an emulator does
not become an ARM/HPS performance measurement. Run this script with native Linux
Python inside WSL when the executable is a Linux binary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object,
                      parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def input_path(root, name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name,
            "Invalid portable vector path")
    require(all(part not in ("", ".", "..") for part in name.split("/")), "Unsafe vector path")
    path = (root/name).resolve()
    require(path.is_relative_to(root) and path.is_file(), "Missing or escaped vector file: " + name)
    return path


def check_inventory(root, inventory):
    for name, info in inventory.items():
        path = input_path(root, name)
        require(path.stat().st_size == info["bytes"] and sha(path) == info["sha256"],
                "Vector inventory hash mismatch: " + name)


def words(path):
    tokens = path.read_text(encoding="ascii").split()
    require(all(re.fullmatch(r"[0-9a-fA-F]{3}", token) for token in tokens),
            "Output is not unsigned12 MEMH: " + path.name)
    return [int(token, 16) for token in tokens]


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--scope", choices=("all", "fixed_1024"), default="all")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    args = parser.parse_args(argv)
    binary, vectors, run = (path.resolve() for path in (args.binary, args.vectors, args.run_dir))
    require(binary.is_file(), "Benchmark executable is missing")
    require(not run.exists(), "Run directory must be fresh")
    require(0 < args.timeout_s <= 600, "Timeout must be in (0,600] seconds")
    manifest_path = vectors/"manifest.json"
    manifest = read_json(manifest_path)
    require(manifest["schema"] == "trecap-arm-qualification-vectors-1" and
            manifest["status"] == "GENERATED_ORACLE_EXPECTATIONS", "Unexpected vector manifest")
    require(len(manifest["cases"]) == manifest["case_count"] and
            len({case["case_id"] for case in manifest["cases"]}) == manifest["case_count"],
            "Vector case count or IDs disagree")
    check_inventory(vectors, manifest["files"])
    coeff_dir = vectors/"sources/artifacts/coefficients"
    cases = [case for case in manifest["cases"] if args.scope == "all" or case["scope"] == args.scope]
    require(bool(cases), "Selected scope has no cases")
    first_expected = input_path(vectors, next(case["output_file"] for case in cases
                                            if case["oracle_status"] == "accepted"))
    binary_hash, vector_hash = sha(binary), sha(manifest_path)
    run.mkdir(parents=True, exist_ok=False)
    report = {"schema": "trecap-arm-kernel-qualification-1", "status": "RUNNING",
              "scope": "Full-output functional qualification; no physical ARM timing or energy claim",
              "selected_scope": args.scope, "binary_sha256": binary_hash,
              "vector_manifest_sha256": vector_hash, "runner_sha256": sha(Path(__file__)),
              "cases_expected": len(cases), "cases": []}
    failures = []
    for case in cases:
        case_id = case["case_id"]
        require(re.fullmatch(r"[A-Za-z0-9_]+", case_id), "Unsafe case ID")
        directory = run/case_id
        directory.mkdir()
        result_path, samples_path = directory/"benchmark.json", directory/"actual.memh"
        source = input_path(vectors, case["input_file"])
        expected = input_path(vectors, case["output_file"]) if case["oracle_status"] == "accepted" else first_expected
        command = [str(binary), "--input", str(source), "--expected", str(expected),
                   "--coeff-dir", str(coeff_dir), "--threshold", str(case["threshold2"]),
                   "--verify-only", "--output", str(result_path), "--output-samples", str(samples_path)]
        entry = {"case_id": case_id, "oracle_status": case["oracle_status"],
                 "threshold2": case["threshold2"], "input_samples": case["input_samples"],
                 "input_sha256": case["input_sha256"], "expected_output_sha256": case["output_sha256"],
                 "status": "FAIL"}
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout_s)
            entry["exit_code"] = result.returncode
            # Local diagnostic files deliberately preserve exact process text;
            # they may contain caller-supplied paths and are not public reports.
            (directory/"stdout.log").write_text(result.stdout, encoding="utf-8")
            (directory/"stderr.log").write_text(result.stderr, encoding="utf-8")
            if case["oracle_status"] == "rejected":
                require(case["input_samples"] == 0 and
                        case["oracle_rejection"] == "empty stream or invalid window",
                        "No approved executable rejection matcher for this oracle failure")
                require(result.returncode == 1 and
                        "trecap_cpu_benchmark: empty or unreadable MEMH " + str(source) in result.stderr,
                        "Expected explicit empty-input rejection; arbitrary failure is not accepted")
                require(not result_path.exists() and not samples_path.exists(),
                        "Rejected input produced success/output artifacts")
                entry.update(status="PASS_EXPECTED_REJECTION", checked_output_samples=0)
            else:
                require(result.returncode == 0, "Executable did not complete successfully")
                data = read_json(result_path)
                require(data["schema"] == "trecap-preallocated-cpu-benchmark-1" and
                        data["status"] == "PASS_FUNCTIONAL_ADMISSION" and data["verify_only"] is True,
                        "Missing verify-only functional admission")
                require(data["records"] == [] and data["trials"] == 0 and data["timed_total_epochs"] == 0,
                        "Qualification command unexpectedly ran timing trials")
                require(data["threshold2"] == case["threshold2"], "Executable threshold mismatch")
                wanted = {"inputs_per_epoch": case["input_samples"], "frames_per_epoch": case["frames"],
                          "tau_last": case["tau_last"], "outputs_per_epoch": case["output_samples"]}
                require(data["geometry"] == wanted, "Executable full-tail geometry mismatch")
                for key, value in {"N": 12, "L": 256, "H": 128, "F": 15, "G": 128, "D": 384,
                                   "final_saturation_bits": 12}.items():
                    require(data["contract"][key] == value, "Executable arithmetic contract mismatch: " + key)
                validation = data["validation"]
                require(validation["mismatches"] == 0 and
                        validation["internal_ranges_checked_outside_timing"] is True and
                        validation["full_output_samples_checked_outside_timing"] == 2*case["output_samples"],
                        "Checked/fast executable admissions incomplete")
                actual_words, expected_words = words(samples_path), words(expected)
                require(len(actual_words) == len(expected_words) == case["output_samples"], "Full output count mismatch")
                mismatches = [(i, got, want) for i, (got, want) in enumerate(zip(actual_words, expected_words)) if got != want]
                require(not mismatches, "Independent output comparison failed: " + repr(mismatches[:5]))
                entry.update(status="PASS_EXACT_OUTPUT", checked_output_samples=len(actual_words),
                             mismatch_count=0, actual_output_sha256=sha(samples_path),
                             compile_architecture=data["environment"]["compile_architecture"],
                             execution_label=data["environment"]["execution_label"],
                             physical_board_identity_attested=data["environment"]["board_identity_attested"])
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            entry["error"] = str(error)
            failures.append(case_id)
        report["cases"].append(entry)
        write_json(run/"qualification_manifest.json", report)
        print(json.dumps({"case_id": case_id, "status": entry["status"]}), flush=True)
    try:
        check_inventory(vectors, manifest["files"])
        require(sha(manifest_path) == vector_hash and sha(binary) == binary_hash,
                "Vectors or executable changed during qualification")
    except (OSError, ValueError) as error:
        failures.append("input_identity_changed")
        report["identity_error"] = str(error)
    report.update(status="FAIL" if failures else "PASS_FUNCTIONAL_QUALIFICATION",
                  failed_cases=failures, cases_completed=len(report["cases"]),
                  exact_output_cases=sum(case["status"] == "PASS_EXACT_OUTPUT" for case in report["cases"]),
                  expected_rejections=sum(case["status"] == "PASS_EXPECTED_REJECTION" for case in report["cases"]),
                  independently_compared_output_samples=sum(case.get("checked_output_samples", 0) for case in report["cases"]),
                  inputs_unchanged="input_identity_changed" not in failures)
    report["artifacts"] = {path.relative_to(run).as_posix(): sha(path) for path in sorted(run.rglob("*"))
                           if path.is_file() and path.name != "qualification_manifest.json"}
    write_json(run/"qualification_manifest.json", report)
    print(json.dumps({key: report[key] for key in ("status", "cases_completed", "exact_output_cases", "expected_rejections",
                                                "independently_compared_output_samples")}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
