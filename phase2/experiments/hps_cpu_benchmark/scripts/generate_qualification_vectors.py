#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate bounded ARM-kernel qualification cases with the recursive oracle.

Reads a repository; writes a new portable evidence directory. No benchmark code,
production reference model, compiler, hardware or external process is invoked.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys


ORACLE_PATH = "scripts/verification/reference_integer_oracle.py"
ORACLE_SHA256 = "78fa9837f51676bed60bec01f7ad9f8fa17faa506c2405dc8b0210801d009374"
INPUT_PATH = "artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh"
COEFFICIENTS = ("window_qw.memh", "twiddle_re.memh", "twiddle_im.memh",
                "twiddle_inv_re.memh", "twiddle_inv_im.memh")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def memh(data, width, signed):
    tokens = data.decode("ascii").split()
    if any(not re.fullmatch(r"[0-9A-Fa-f]+", token) for token in tokens):
        raise ValueError("Invalid hexadecimal MEMH token")
    words = [int(token, 16) for token in tokens]
    if any(not 0 <= value < (1 << width) for value in words):
        raise ValueError("MEMH word exceeds declared width")
    return [value - (1 << width) if signed and value >= (1 << (width-1))
            else value for value in words]


def encode_samples(values):
    if any(type(value) is not int or not -2048 <= value <= 2047 for value in values):
        raise ValueError("Samples must fit signed 12 bits")
    return "".join(f"{value & 0xfff:03x}\n" for value in values).encode("ascii")


def broadband(length, seed=0x615D2EAD):
    values = []
    state = seed
    for _ in range(length):
        state ^= (state << 13) & 0xffffffff
        state ^= state >> 17
        state ^= (state << 5) & 0xffffffff
        state &= 0xffffffff
        values.append((state & 0xfff) - 2048)
    return values


def definitions(original):
    transient = [0] * 1024
    for i, position in enumerate((0, 1, 126, 127, 128, 129, 255, 256, 511, 512, 1022, 1023)):
        transient[position] = 2047 if i % 2 == 0 else -2048
    signals = [
        ("multitone", original, "Original 1024-sample measurement artifact, unchanged."),
        ("zeros", [0]*1024, "1024 zeros."),
        ("alternating_extremes", [2047 if i % 2 == 0 else -2048 for i in range(1024)],
         "Even indices +2047; odd indices -2048."),
        ("dc_positive_extreme", [2047]*1024, "1024 samples at signed12 maximum +2047."),
        ("dc_negative_extreme", [-2048]*1024, "1024 samples at signed12 minimum -2048."),
        ("broadband", broadband(1024),
         "xorshift32 seed 0x615D2EAD; shifts 13,17,5 with 32-bit state; sample=(state & 0xfff)-2048."),
        ("boundary_transients", transient,
         "Alternating +2047/-2048 impulses at indices 0,1,126,127,128,129,255,256,511,512,1022,1023; other samples zero."),
    ]
    cases = []
    for signal, samples, description in signals:
        for threshold in (0, 100_000_000_000):
            cases.append({"case_id": signal + ("_dense" if threshold == 0 else "_masked"),
                          "scope": "fixed_1024", "signal": signal, "samples": samples,
                          "threshold2": threshold, "definition": description})
    for length, threshold in ((1, 0), (1, 100_000_000_000), (127, 100_000_000_000),
                              (128, 100_000_000_000), (129, 100_000_000_000)):
        samples = broadband(length)
        samples[0] = -2048
        if length > 1:
            samples[-1] = 2047
        cases.append({"case_id": f"finite_Ns{length}" + ("_dense" if threshold == 0 else "_masked"),
                      "scope": "finite_geometry", "signal": "finite_broadband",
                      "samples": samples, "threshold2": threshold,
                      "definition": "Prefix of broadband rule; first sample replaced by -2048 and, when Ns>1, final sample by +2047."})
    cases.append({"case_id": "empty_stream_rejected", "scope": "rejection",
                  "signal": "empty", "samples": [], "threshold2": 0,
                  "definition": "Empty input must be rejected by the fixed-point finite-record interface."})
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    out = args.out.resolve()
    if out.exists():
        parser.error("--out must be a fresh directory")
    source_names = [ORACLE_PATH, INPUT_PATH, "artifacts/measurement/multitone/manifest.json"]
    source_names += ["artifacts/coefficients/" + name for name in COEFFICIENTS]
    source_bytes = {name: (repo/name).read_bytes() for name in source_names}
    hashes = {name: digest(data) for name, data in source_bytes.items()}
    if hashes[ORACLE_PATH] != ORACLE_SHA256:
        raise ValueError("Independent oracle differs from the reviewed frozen source")
    measured = json.loads(source_bytes["artifacts/measurement/multitone/manifest.json"])
    if hashes[INPUT_PATH] != measured["input_sha256"]:
        raise ValueError("Original measurement input hash mismatch")
    for name in COEFFICIENTS:
        if hashes["artifacts/coefficients/"+name] != measured["coefficient_sha256"][name]:
            raise ValueError("Frozen coefficient hash mismatch: " + name)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("arm_qualification_recursive_oracle", repo/ORACLE_PATH)
    oracle = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = oracle
    spec.loader.exec_module(oracle)
    window = memh(source_bytes["artifacts/coefficients/window_qw.memh"], 16, False)
    forward = list(zip(memh(source_bytes["artifacts/coefficients/twiddle_re.memh"], 17, True),
                       memh(source_bytes["artifacts/coefficients/twiddle_im.memh"], 17, True)))
    inverse = list(zip(memh(source_bytes["artifacts/coefficients/twiddle_inv_re.memh"], 17, True),
                       memh(source_bytes["artifacts/coefficients/twiddle_inv_im.memh"], 17, True)))
    original = memh(source_bytes[INPUT_PATH], 12, True)
    if len(original) != 1024 or any(len(table) != 256 for table in (window, forward, inverse)):
        raise ValueError("Unexpected coefficient or measured-input geometry")
    out.mkdir(parents=True, exist_ok=False)
    for name, data in source_bytes.items():
        destination = out/"sources"/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    cases = []
    metrics_rows = []
    for definition in definitions(original):
        samples = definition["samples"]
        case = {key: value for key, value in definition.items() if key != "samples"}
        directory = out/"cases"/case["case_id"]
        directory.mkdir(parents=True)
        input_data = encode_samples(samples)
        (directory/"input.memh").write_bytes(input_data)
        case.update(input_samples=len(samples), input_file=(directory/"input.memh").relative_to(out).as_posix(),
                    input_sha256=digest(input_data))
        try:
            records = oracle.run(samples, case["threshold2"], window, forward, inverse)
        except ValueError as error:
            # Record the oracle's rejection verbatim. Do not clip, relax widths,
            # or manufacture an expected-output file for an overflowing case.
            case.update(oracle_status="rejected", expected_kernel_behavior="reject",
                        oracle_rejection=str(error), output_samples=None, frames=None,
                        tau_last=None, output_file=None, output_sha256=None)
        else:
            ns, frames, tau_last, ny = records[("G",)]
            if ns != len(samples):
                raise ValueError("Oracle geometry input count mismatch")
            outputs = [records[("Y", index)][0] for index in range(ny)]
            output_data = encode_samples(outputs)
            (directory/"expected.memh").write_bytes(output_data)
            metrics = {name: records[("M", name)][0] for name in oracle.METRIC_NAMES}
            case.update(oracle_status="accepted", expected_kernel_behavior="exact_output",
                        output_samples=ny, frames=frames, tau_last=tau_last,
                        output_file=(directory/"expected.memh").relative_to(out).as_posix(),
                        output_sha256=digest(output_data), metrics=metrics,
                        output_at_min=sum(value == -2048 for value in outputs),
                        output_at_max=sum(value == 2047 for value in outputs))
            if case["signal"] == "multitone":
                name = "dense" if case["threshold2"] == 0 else "masked"
                expected = next(item for item in measured["cases"] if item["name"] == name)
                if digest(output_data) != expected["output_sha256"]:
                    raise ValueError("Qualification disagrees with measured multitone reference ROM: " + name)
                case["measurement_reference_rom_match"] = True
            metrics_rows.append({"case_id": case["case_id"], "scope": case["scope"],
                                 "threshold2": case["threshold2"], "input_samples": ns,
                                 "output_samples": ny, "frames": frames, "tau_last": tau_last,
                                 **metrics})
        cases.append(case)
        print(json.dumps({"case_id": case["case_id"], "oracle_status": case["oracle_status"],
                          "input_samples": len(samples), "output_samples": case["output_samples"]}), flush=True)
    for name, expected in hashes.items():
        if digest((repo/name).read_bytes()) != expected:
            raise ValueError("Qualification source changed during generation: " + name)
    with (out/"case_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(metrics_rows[0]))
        writer.writeheader()
        writer.writerows(metrics_rows)
    manifest = {
        "schema": "trecap-arm-qualification-vectors-1", "status": "GENERATED_ORACLE_EXPECTATIONS",
        "scope": "Bounded full-output integer qualification vectors; no executable, hardware, timing or energy claim",
        "generator_sha256": digest(Path(__file__).read_bytes()), "source_sha256": hashes,
        "format": {"input": "unsigned12 hexadecimal MEMH, one word per line; decode as signed two's complement",
                   "output": "unsigned12 hexadecimal MEMH, one word per line; full finite output in ascending sample index",
                   "newline": "LF", "word_digits": 3},
        "arithmetic": {"input_width": 12, "output_width": 12, "L": 256, "H": 128,
                       "F": 15, "G": 128, "reference_delay": 384,
                       "rounding": "nearest, ties away from zero",
                       "fft_scaling": "divide by two after each radix-2 stage",
                       "ifft_scaling": "none per stage",
                       "width_guard_policy": "Internal oracle.fit failures reject a case; final signed12 saturation is normative"},
        "case_count": len(cases), "accepted_cases": sum(c["oracle_status"] == "accepted" for c in cases),
        "rejected_cases": sum(c["oracle_status"] == "rejected" for c in cases),
        "cases": cases,
    }
    manifest["files"] = {path.relative_to(out).as_posix(): {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
                         for path in sorted(out.rglob("*")) if path.is_file()}
    (out/"manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "cases": len(cases),
                      "accepted": manifest["accepted_cases"], "rejected": manifest["rejected_cases"]}))


if __name__ == "__main__":
    main()
