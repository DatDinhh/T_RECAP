#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Independently validate an offline export of all 20 qualification cases.

No subprocess, serial, network, extraction, or hardware access. Result files are
flat: CASE.json, CASE.memh, CASE.log (combined stdout/stderr), and CASE.exit.
The optional binary SHA-256 is an external receipt identifier, not an attestation
that this validator has inspected the executable or proven physical execution.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_object(items):
    out = {}
    for name, value in items:
        require(name not in out, "Duplicate JSON key: " + name)
        out[name] = value
    return out


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object,
                      parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))


def safe_file(root, name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name,
            "Invalid portable file name")
    require(all(part not in ("", ".", "..") for part in name.split("/")), "Unsafe relative path")
    path = (root/name).resolve()
    require(path.is_relative_to(root) and path.is_file(), "Missing or escaped file: " + name)
    return path


def words(path):
    tokens = path.read_text(encoding="ascii").split()
    require(all(re.fullmatch(r"[0-9a-fA-F]{3}", token) for token in tokens),
            "Malformed unsigned12 MEMH: " + path.name)
    return [int(token, 16) for token in tokens]


def inventory(vectors, manifest):
    require(bool(manifest["files"]), "Empty vector file inventory")
    for name, record in manifest["files"].items():
        path = safe_file(vectors, name)
        require(path.stat().st_size == record["bytes"] and sha(path) == record["sha256"],
                "Vector file hash/size mismatch: " + name)


def integer(value, expected, message):
    require(type(value) is int and value == expected, message)


def check_accepted(case, result, actual, expected):
    integer(result["threshold2"], case["threshold2"], "Threshold differs from oracle case")
    require(result["schema"] == "trecap-preallocated-cpu-benchmark-1" and
            result["status"] == "PASS_FUNCTIONAL_ADMISSION" and result["verify_only"] is True,
            "Missing verify-only functional admission")
    require(result["records"] == [], "Export contains timing records")
    for key in ("trials", "warmup_epochs", "timed_total_epochs", "timed_input_samples",
                "timed_output_samples", "timed_frames", "final_consumer_checksum"):
        integer(result[key], 0, "Verify-only result ran timed/consumer work: " + key)
    wanted = {"inputs_per_epoch": case["input_samples"], "frames_per_epoch": case["frames"],
              "tau_last": case["tau_last"], "outputs_per_epoch": case["output_samples"]}
    require(set(result["geometry"]) == set(wanted), "Unexpected geometry fields")
    for key, value in wanted.items():
        integer(result["geometry"][key], value, "Full-tail geometry mismatch: " + key)
    for key, value in {"N": 12, "L": 256, "H": 128, "F": 15, "G": 128, "D": 384,
                       "final_saturation_bits": 12}.items():
        integer(result["contract"][key], value, "Fixed-point contract mismatch: " + key)
    require(result["contract"]["rounding"] == "nearest ties away from zero" and
            result["contract"]["threshold_comparison"] == "strict mag2 < threshold; DC protected, Nyquist eligible",
            "Rounding or mask contract mismatch")
    checks = result["validation"]
    integer(checks["mismatches"], 0, "Executable reported mismatches")
    integer(checks["full_output_samples_checked_outside_timing"], 2*case["output_samples"],
            "Checked and fast full-output admissions were not both performed")
    require(checks["internal_ranges_checked_outside_timing"] is True and
            checks["timed_kernel_internal_guards"] is False,
            "Executable range-check policy differs from qualified kernel")
    got, wanted_words = words(actual), words(expected)
    require(len(got) == len(wanted_words) == case["output_samples"], "Full output word count mismatch")
    differences = [(i, a, b) for i, (a, b) in enumerate(zip(got, wanted_words)) if a != b]
    require(not differences, "Output sample mismatch (first five): " + repr(differences[:5]))
    require(sha(actual) == sha(expected) == case["output_sha256"],
            "Output bytes/hash differ from canonical expected MEMH")
    env = result["environment"]
    require(isinstance(env["compile_architecture"], str) and isinstance(env["execution_label"], str),
            "Missing architecture/execution metadata")
    require(env["board_identity_attested"] is False, "Unexpected executable board-attestation claim")
    requested = env.get("requested_cpu")
    if requested is not None:
        require(type(requested) is int and requested >= 0 and
                env.get("requested_affinity_applied_and_read_back") is True and
                env["allowed_cpus"] == [requested], "Requested CPU affinity was not confirmed")
    return {"status": "PASS_EXACT_OUTPUT", "checked_output_samples": len(got), "mismatch_count": 0,
            "actual_output_sha256": sha(actual), "compile_architecture": env["compile_architecture"],
            "execution_label": env["execution_label"], "requested_cpu": requested,
            "physical_board_identity_attested_by_executable": False}


def verify(args):
    vectors, exported = args.vectors.resolve(), args.result_dir.resolve()
    require(exported.is_dir(), "Exported result directory is missing")
    manifest_path = safe_file(vectors, "manifest.json")
    manifest = read_json(manifest_path)
    require(manifest["schema"] == "trecap-arm-qualification-vectors-1" and
            manifest["status"] == "GENERATED_ORACLE_EXPECTATIONS", "Unexpected vector manifest")
    require(manifest["case_count"] == len(manifest["cases"]) == 20 and
            manifest["accepted_cases"] == 19 and manifest["rejected_cases"] == 1,
            "Expected the complete 20-case vector set")
    ids = [c["case_id"] for c in manifest["cases"]]
    require(len(set(ids)) == 20 and all(re.fullmatch(r"[A-Za-z0-9_]+", name) for name in ids),
            "Duplicate or unsafe case ID")
    inventory(vectors, manifest)
    vector_hash = sha(manifest_path)
    report = {"schema": "trecap-exported-functional-qualification-1", "status": "FAIL",
              "scope": "Offline exact-output validation; physical board identity and binary provenance require a separate receipt",
              "provided_binary_sha256": args.binary_sha256.lower() if args.binary_sha256 else None,
              "binary_hash_verified_by_this_validator": False,
              "physical_execution_attested_by_this_validator": False,
              "vector_manifest_sha256": vector_hash, "validator_sha256": sha(Path(__file__)),
              "cases_expected": 20, "cases": [], "exported_files_sha256": {}}
    failed = []
    for case in manifest["cases"]:
        case_id = case["case_id"]
        row = {"case_id": case_id, "status": "FAIL", "threshold2": case["threshold2"],
               "input_samples": case["input_samples"], "input_sha256": case["input_sha256"],
               "expected_output_sha256": case["output_sha256"]}
        try:
            source = safe_file(vectors, case["input_file"])
            require(sha(source) == case["input_sha256"] and len(words(source)) == case["input_samples"],
                    "Case input/hash disagrees with vector manifest")
            exit_file = safe_file(exported, case_id+".exit")
            log_file = safe_file(exported, case_id+".log")
            code_text = exit_file.read_text(encoding="ascii").strip()
            require(re.fullmatch(r"[0-9]{1,3}", code_text) is not None and int(code_text) <= 255,
                    "Invalid exported process exit code")
            code = int(code_text);row["exit_code"] = code
            log = log_file.read_text(encoding="utf-8", errors="strict")
            for path in (exit_file, log_file):report["exported_files_sha256"][path.name] = sha(path)
            if case["oracle_status"] == "rejected":
                require(case["input_samples"] == 0 and case["oracle_rejection"] == "empty stream or invalid window",
                        "Unknown oracle rejection case")
                require(code == 1, "Expected normal empty-input rejection exit code1")
                diagnostic = re.search(r"(?m)^trecap_cpu_benchmark: empty or unreadable MEMH ([^\r\n]+)\r?$", log)
                require(diagnostic is not None and
                        diagnostic[1].replace("\\", "/").endswith("/"+case["input_file"]),
                        "Missing known empty-input diagnostic for this case; arbitrary failure is not accepted")
                require(not (exported/(case_id+".json")).exists() and not (exported/(case_id+".memh")).exists(),
                        "Rejected case produced JSON or output samples")
                require("PASS:" not in log, "Rejected case log also claims success")
                row.update(status="PASS_EXPECTED_REJECTION", checked_output_samples=0)
            else:
                require(case["oracle_status"] == "accepted" and code == 0, "Accepted case process failed")
                expected = safe_file(vectors, case["output_file"])
                require(sha(expected) == case["output_sha256"], "Expected vector hash mismatch")
                result_file, actual = safe_file(exported, case_id+".json"), safe_file(exported, case_id+".memh")
                for path in (result_file, actual):report["exported_files_sha256"][path.name] = sha(path)
                row.update(check_accepted(case, read_json(result_file), actual, expected))
                require(re.search(r"(?m)^PASS: 0 timing records; " + str(2*case["output_samples"]) +
                                  r" output samples checked outside timing\. Result: .+\r?$", log) is not None,
                        "Missing complete verify-only stdout receipt")
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
            row["status"] = "FAIL";row["error"] = str(error);failed.append(case_id)
        report["cases"].append(row)
    try:
        inventory(vectors, manifest)
        require(sha(manifest_path) == vector_hash, "Vector manifest changed during validation")
        for name, expected_hash in report["exported_files_sha256"].items():
            require(sha(safe_file(exported, name)) == expected_hash, "Export changed during validation: " + name)
    except (OSError, ValueError) as error:
        failed.append("evidence_identity_changed");report["identity_error"] = str(error)
    architectures = {c["compile_architecture"] for c in report["cases"] if c["status"] == "PASS_EXACT_OUTPUT"}
    labels = {c["execution_label"] for c in report["cases"] if c["status"] == "PASS_EXACT_OUTPUT"}
    if len(architectures) > 1 or len(labels) > 1:
        failed.append("mixed_executable_architecture_or_execution_labels")
    report.update(status="FAIL" if failed else "PASS_EXPORTED_FUNCTIONAL_QUALIFICATION",
                  failed_cases=failed, cases_completed=len(report["cases"]),
                  exact_output_cases=sum(c["status"] == "PASS_EXACT_OUTPUT" for c in report["cases"]),
                  expected_rejections=sum(c["status"] == "PASS_EXPECTED_REJECTION" for c in report["cases"]),
                  independently_compared_output_samples=sum(c.get("checked_output_samples", 0) for c in report["cases"] if c["status"] == "PASS_EXACT_OUTPUT"),
                  exported_architectures=sorted(architectures),
                  inputs_unchanged="evidence_identity_changed" not in failed)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--binary-sha256")
    parser.add_argument("--output", type=Path, required=True, help="Fresh JSON output filename; parent must exist")
    args = parser.parse_args(argv)
    require(not args.output.exists(), "Output already exists; choose a fresh JSON filename")
    require(args.output.parent.is_dir(), "Output parent directory is missing")
    require(args.binary_sha256 is None or re.fullmatch(r"[0-9a-fA-F]{64}", args.binary_sha256),
            "--binary-sha256 must contain64 hexadecimal digits")
    try:
        report = verify(args)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        report = {"schema": "trecap-exported-functional-qualification-1", "status": "FAIL",
                  "error": str(error), "physical_execution_attested_by_this_validator": False}
    # Exclusive creation protects existing results even if another caller races.
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False);handle.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "cases_completed", "exact_output_cases",
                                           "expected_rejections", "independently_compared_output_samples") if k in report}))
    return int(report["status"] != "PASS_EXPORTED_FUNCTIONAL_QUALIFICATION")


if __name__ == "__main__":
    sys.exit(main())
