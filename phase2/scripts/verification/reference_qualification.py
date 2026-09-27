# SPDX-License-Identifier: MIT
"""Bounded V1 qualification of the baseline reference (not RTL or board signoff).

Run with the repository Python runtime. Requires CMake and a C++20 compiler.
Builds a test-only public-API adapter, never regenerates frozen artifacts.
Each invocation creates a new ignored evidence directory and returns nonzero on
baseline/checker/build failure. Broader public-API findings have separate status.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone

from reference_integer_oracle import (Config, METRIC_NAMES, canonical, mask,
                                      rounded, run, saturated, transform)

CASES = ("impulse_Ns1024_thr0", "near_threshold_multitone_Ns1024_thr64")
FRAME_FIELDS = ("frame_idx",) + METRIC_NAMES[:6]
BIN_FIELDS = ("frame_idx", "bin_idx", "real", "imag", "mag2", "eligible", "pre_mask", "mask")
SELF_TESTS = ("test_rounding", "test_saturation", "test_fixed_point", "test_qcoef",
              "test_fft_known_cases", "test_hermitian", "test_mask", "test_wola_small")
STAGES = ("analysis", "fft", "canonical", "masked", "ifft", "z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def read_memh(path: Path, width: int, signed: bool, rows: int) -> list[int]:
    raw = path.read_bytes()
    digits = (width + 3) // 4
    if not re.fullmatch(rb"(?:[0-9a-f]{" + str(digits).encode() + rb"}\n){" + str(rows).encode() + rb"}", raw):
        raise ValueError(f"noncanonical MEMH or row count: {path.name}")
    values = [int(word, 16) for word in raw.splitlines()]
    if any(v >= 1 << width for v in values):
        raise ValueError(f"nonzero MEMH padding bits: {path.name}")
    return [v - (1 << width) if signed and v >= 1 << (width - 1) else v for v in values]


def parse_records(text: str) -> dict[tuple, tuple]:
    if not text or not text.endswith("\n"):
        raise ValueError("empty/truncated adapter transcript")
    records, sequence = {}, {}
    for number, line in enumerate(text.splitlines(), 1):
        f = line.split("\t")
        kind = f[0]
        arity = {"G": 5, "Y": 3, "R": 3, "F": 8, "B": 9, "S": 6, "M": 3}.get(kind)
        if arity != len(f):
            raise ValueError(f"transcript schema at row {number}")
        lexical = [v for i, v in enumerate(f[1:], 1)
                   if not (kind == "S" and i == 2) and not (kind == "M" and i == 1)]
        if any(not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", v) for v in lexical):
            raise ValueError(f"noninteger field at row {number}")
        if kind == "G":
            key, values = (kind,), tuple(map(int, f[1:]))
        elif kind == "S":
            if f[2] not in STAGES:
                raise ValueError("unknown stage")
            key, values = (kind, int(f[1]), f[2], int(f[3])), tuple(map(int, f[4:]))
        elif kind == "M":
            if f[1] not in METRIC_NAMES:
                raise ValueError("unknown metric")
            key, values = (kind, f[1]), (int(f[2]),)
        else:
            split = 3 if kind == "B" else 2
            key = (kind,) + tuple(map(int, f[1:split]))
            values = tuple(map(int, f[split:]))
        if key in records:
            raise ValueError(f"duplicate record: {key}")
        if kind in ("Y", "R", "F", "S", "B"):
            group = key[:-1]
            expected_index = sequence.get(group, 0)
            if key[-1] != expected_index:
                raise ValueError(f"noncontiguous record: {key}; expected {expected_index}")
            sequence[group] = expected_index + 1
        records[key] = values
    return records


def compare(expected: dict, actual: dict, name: str) -> int:
    missing, extra = expected.keys() - actual.keys(), actual.keys() - expected.keys()
    if missing or extra:
        raise ValueError(f"{name}: missing={sorted(missing, key=str)[:3]}, extra={sorted(extra, key=str)[:3]}")
    for key, value in expected.items():
        if value != actual[key]:
            raise ValueError(f"{name}: first mismatch {key}: expected={value}, actual={actual[key]}")
    return len(expected)


def emit_oracle(directory: Path, records: dict) -> None:
    directory.mkdir()
    ny = records[("G",)][3]
    (directory / "y_out.memh").write_text(
        "".join(f"{records[('Y', n)][0] & 4095:03x}\n" for n in range(ny)), encoding="ascii", newline="\n")
    for filename, header, kind in (("frame_stats.csv", FRAME_FIELDS, "F"),
                                    ("bin_stats.csv", BIN_FIELDS, "B")):
        with (directory / filename).open("w", newline="", encoding="ascii") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(header)
            for key, value in records.items():
                if key[0] == kind:
                    writer.writerow(key[1:] + value)
    # Export the already-qualified complex IFFT boundary for a passive WOLA-input
    # scoreboard. Imaginary residuals must match exactly, not merely be tolerated.
    with (directory / "ifft_output.csv").open("w", newline="", encoding="ascii") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("frame_idx", "offset", "re", "im"))
        for frame in range(records[("G",)][1]):
            for offset in range(256):
                writer.writerow((frame, offset) + records[("S", frame, "ifft", offset)])
    metrics = {name: str(records[("M", name)][0]) for name in METRIC_NAMES}
    write_json(directory / "metrics.json", {
        "schema": "trecap_reference_qualification_numeric_metrics_v1",
        "geometry": dict(zip(("Ns", "Nframes", "tau_last", "Ny"), records[("G",)])),
        "suppression_totals": {n: metrics[n] for n in METRIC_NAMES[:4]},
        "spectral_totals": {n: metrics[n] for n in METRIC_NAMES[4:6]},
        "time_domain_errors": {n: metrics[n] for n in METRIC_NAMES[6:]}})



def emit_sv_header(directory: Path, records: dict, name: str, threshold: int, x_hash: str) -> None:
    ns, frames, _, ny = records[("G",)]
    values = {n: records[("M", n)][0] for n in METRIC_NAMES}
    lines = ["// Test-only expectations derived by the independent integer oracle.",
             "// Qualification status and provenance are in the parent run report.",
             "package trecap_artifact_expectations_pkg;", "  import trecap_core_pkg::*;",
             f'  localparam string TEXP_VECTOR_NAME = "{name}";']
    for label, value in (("NS", ns), ("NY", ny), ("FRAMES", frames),
                         ("UNIQUE_BINS", 129), ("BIN_ROWS", frames * 129)):
        lines.append(f"  localparam int unsigned TEXP_{label} = {value};")
    lines.append(f"  localparam logic [55:0] TEXP_THR2 = 56'd{threshold};")
    for label, metric, width in (
        ("UNIQUE_BINS_TOTAL", "unique_bins", 64),
        ("UNIQUE_SUPPRESSED_TOTAL", "unique_suppressed_bins", 64),
        ("ELIGIBLE_UNIQUE_TOTAL", "eligible_unique_bins", 64),
        ("ELIGIBLE_SUPPRESSED_TOTAL", "eligible_suppressed_bins", 64),
        ("ELIGIBLE_KEPT_MAG2", "eligible_kept_mag2", 128),
        ("ELIGIBLE_TOTAL_MAG2", "eligible_total_mag2", 128),
        ("SUM_ABS_ERR", "sum_abs_err", 128), ("SUM_SQ_ERR", "sum_sq_err", 128),
        ("MAX_ABS_ERR", "max_abs_err", 16), ("ERROR_SAMPLE_COUNT", "error_sample_count", 64)):
        if not 0 <= values[metric] < 1 << width:
            raise ValueError("SV expectation width overflow")
        lines.append(f"  localparam logic [{width-1}:0] TEXP_{label} = {width}'d{values[metric]};")
    hashes = {"X": x_hash, "Y": sha(directory / "y_out.memh"),
              "FRAME": sha(directory / "frame_stats.csv"), "BIN": sha(directory / "bin_stats.csv"),
              "METRICS": sha(directory / "metrics.json")}
    for label, digest in hashes.items():
        lines.append(f'  localparam string TEXP_{label}_SHA256 = "{digest}";')
    lines += ["endpackage : trecap_artifact_expectations_pkg", ""]
    (directory / "trecap_artifact_expectations_pkg.sv").write_text("\n".join(lines), encoding="ascii", newline="\n")


def frozen_records(root: Path, name: str, cfg: dict) -> dict:
    directory = root / "artifacts/reference_outputs" / name
    result = {("Y", i): (v,) for i, v in enumerate(read_memh(directory / "y_out.memh", 12, True, cfg["Ny"]))}
    for filename, fields, kind, split in (("frame_stats.csv", FRAME_FIELDS, "F", 1),
                                         ("bin_stats.csv", BIN_FIELDS, "B", 2)):
        path = directory / filename
        if not path.exists():
            if kind == "B" and name == CASES[0]:
                continue  # This absence is explicit in the V1 report, not silently supplied.
            raise ValueError(f"missing frozen {filename}")
        with path.open(newline="", encoding="ascii") as stream:
            reader = csv.reader(stream)
            if tuple(next(reader)) != fields:
                raise ValueError(f"unexpected {filename} header")
            for row in reader:
                if len(row) != len(fields):
                    raise ValueError(f"{filename} arity")
                v = tuple(map(int, row))
                key = (kind,) + v[:split]
                if key in result:
                    raise ValueError(f"duplicate frozen record: {key}")
                result[key] = v[split:]
    metrics = json.loads((directory / "metrics.json").read_text())
    for section, names in (("suppression_totals", METRIC_NAMES[:4]),
                           ("spectral_totals", METRIC_NAMES[4:6]),
                           ("time_domain_errors", METRIC_NAMES[6:])):
        if set(metrics[section]) != set(names):
            raise ValueError(f"frozen metric schema: {section}")
        result.update({("M", n): (int(metrics[section][n]),) for n in names})
    return result


def checked_path(root: Path, path: Path, area: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to((root / area).resolve()) or resolved == (root / area).resolve():
        raise ValueError(f"output must be inside {area}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--generator", default=None)
    args = parser.parse_args()
    root = args.repo.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = checked_path(root, args.run_dir or root / "runs/verification" / f"reference-v1-{stamp}", "runs/verification")
    build = checked_path(root, args.build_dir or root / "build/verification" / f"reference-v1-{stamp}", "build/verification")
    evidence.mkdir(parents=True, exist_ok=False)
    report = {"schema": "trecap_reference_qualification_v1", "started_utc": stamp,
              "status": "RUNNING", "baseline_scope": "selected static vectors; shifts 0,1,2,15",
              "all_V1_qualified": False, "checks": [], "public_api_findings": [],
              "limitations": ["No RTL, board, dynamic THR/epochs or quality-bound qualification",
                              "Frozen coefficient bytes shared; transcendental table generation not independently proved",
                              "Only two selected nonzero vectors, not the full normative suite",
                              "Impulse frozen bin_stats is absent; bins compare independent oracle to fresh C++ API output"],
              "python": platform.python_version(), "platform": platform.system()}
    inputs = list((root / "artifacts").rglob("*")) + list((root / "sw/reference_model/src").glob("*.cpp"))
    inputs += list((root / "sw/reference_model/include").rglob("*.hpp"))
    inputs += [Path(__file__).resolve(), Path(__file__).with_name("reference_integer_oracle.py").resolve(),
               root / "sim/verification/reference_adapter/reference_api_adapter.cpp",
               root / "sim/verification/reference_adapter/CMakeLists.txt", root / "sw/reference_model/CMakeLists.txt",
               root / "spec/generated/core_config.json"]
    inputs += [root / "sw/reference_model/tests/cpp" / f"{n}.cpp" for n in SELF_TESTS]
    inputs = sorted({p.resolve() for p in inputs if p.is_file()})
    before = {p.relative_to(root).as_posix(): sha(p) for p in inputs}
    write_json(evidence / "input_identities.json", before)
    report["input_identities_sha256"] = sha(evidence / "input_identities.json")
    qualification_paths = (
        "scripts/verification/reference_qualification.py",
        "scripts/verification/reference_integer_oracle.py",
        "sim/verification/reference_adapter/reference_api_adapter.cpp",
        "sim/verification/reference_adapter/CMakeLists.txt",
    )
    report["qualification_sources"] = {name: before[name] for name in qualification_paths}

    def execute(command, logname, stdin=None, timeout=300):
        completed = subprocess.run([str(v) for v in command], cwd=root, input=stdin,
                                   text=True, encoding="utf-8", errors="strict",
                                   capture_output=True, timeout=timeout, check=False)
        (evidence / (logname + ".stdout.log")).write_text(completed.stdout, encoding="utf-8", newline="\n")
        (evidence / (logname + ".stderr.log")).write_text(completed.stderr, encoding="utf-8", newline="\n")
        if completed.returncode:
            raise RuntimeError(f"{logname}: child exit {completed.returncode}; see retained logs")
        return completed.stdout

    def passed(name, count, **more):
        report["checks"].append({"name": name, "status": "PASS", "records": count, **more})
        print(f"PASS {name}: {count}", flush=True)

    try:
        cmd = ["cmake", "-S", root / "sim/verification/reference_adapter", "-B", build]
        if args.generator:
            cmd += ["-G", args.generator]
        execute(cmd, "configure")
        execute(["cmake", "--build", build, "--config", "Release", "--parallel", "2"], "build", timeout=600)
        exes = list(build.glob("reference_api_adapter*")) + list((build / "Release").glob("reference_api_adapter*"))
        exes = [p for p in exes if p.is_file() and p.name in ("reference_api_adapter", "reference_api_adapter.exe")]
        if len(exes) != 1:
            raise RuntimeError("adapter executable is missing or ambiguous")
        exe = exes[0]
        report["adapter_sha256"] = sha(exe)
        report["build_cache_sha256"] = sha(build / "CMakeCache.txt")
        ct = execute(["ctest", "--test-dir", build, "-C", "Release", "--output-on-failure",
                      "--no-tests=error", "-R", "^(" + "|".join(SELF_TESTS) + ")$"], "selected_cpp_tests")
        observed_tests = re.findall(r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(\w+)\s+\.+\s+Passed", ct, re.MULTILINE)
        if len(observed_tests) != len(SELF_TESTS) or set(observed_tests) != set(SELF_TESTS):
            raise RuntimeError("CTest selected test names/count did not match inventory")
        passed("existing_cpp_self_tests_supplementary", len(SELF_TESTS))
        coeff = root / "artifacts/coefficients"
        tables = {name: read_memh(coeff / f"{name}.memh", 16 if name == "window_qw" else 17,
                                  name != "window_qw", 256)
                  for name in ("window_qw", "twiddle_re", "twiddle_im", "twiddle_inv_re", "twiddle_inv_im")}
        window = tables["window_qw"]
        forward = list(zip(tables["twiddle_re"], tables["twiddle_im"]))
        inverse = list(zip(tables["twiddle_inv_re"], tables["twiddle_inv_im"]))
        if window[0] != 0 or window[128] != 32768:
            raise ValueError("window anchor mismatch")
        for k, value in {0: (32768, 0), 64: (0, -32768), 128: (-32768, 0), 192: (0, 32768)}.items():
            if forward[k] != value or inverse[k] != (value[0], -value[1]):
                raise ValueError("twiddle axis anchor mismatch")
        passed("frozen_coefficient_integer_anchors", 10)

        def adapter(mode, input_text, tag, extra=()):
            return parse_records(execute([exe, mode, coeff, *extra], tag, input_text, timeout=90))

        hand = [(-5, 1, -3), (-3, 1, -2), (-1, 1, -1), (0, 1, 0),
                (1, 1, 1), (3, 1, 2), (5, 1, 3), (-16384, 15, -1),
                (16383, 15, 0), (16384, 15, 1), (-16383, 15, 0)]
        if any(rounded(v, s) != expected for v, s, expected in hand):
            raise ValueError("independent rounding hand anchors failed")
        probes = [("round", v, s) for s in (0, 1, 2, 15) for v in range(-2048, 2049)]
        for bits in (27, 28, 36, 37, 47, 53, 55, 64):
            edge = 1 << (bits - 1)
            probes += [("round", v, s) for v in (-edge, -edge + 1, edge - 2, edge - 1)
                       for s in (0, 1, 2, 15)]
        probes += [("sat", v, w) for w in (12, 16, 28, 36)
                   for v in (-(1 << (w - 1)) - 1, -(1 << (w - 1)), -1, 0,
                             (1 << (w - 1)) - 1, 1 << (w - 1))]
        expected = {("R", i): ((rounded(v, p) if op == "round" else saturated(v, p)),)
                    for i, (op, v, p) in enumerate(probes)}
        actual = adapter("primitives", "".join(f"{op} {v} {p}\n" for op, v, p in probes), "primitives")
        passed("independent_baseline_primitive_comparison", compare(expected, actual, "primitives"))
        wide = [(-(1 << 63), 63), (1 << 62, 63), ((1 << 63) - 1, 63)]
        observed = adapter("primitives", "".join(f"round {v} {s}\n" for v, s in wide), "public_api_shift63")
        for i, (v, s) in enumerate(wide):
            if observed[("R", i)][0] != rounded(v, s):
                report["public_api_findings"].append({"operation": "rnd_shr", "value": str(v), "shift": s,
                    "expected": rounded(v, s), "actual": observed[("R", i)][0], "status": "UNRESOLVED_DEFECT",
                    "source": "sw/reference_model/include/trecap_golden/rounding.hpp",
                    "baseline_impact": "not exercised by baseline shifts 0/1/15"})
        report["public_api_scope_status"] = "FAIL" if report["public_api_findings"] else "PASS_SELECTED_PROBES"

        def check_transform(name, mode, data, anchor=None):
            predicted = transform(data, inverse if mode == "ifft" else forward, mode == "ifft")
            if anchor is not None and predicted != anchor:
                raise ValueError(f"independent transform hand anchor failed: {name}")
            expected = {("S", 0, mode, k): v for k, v in enumerate(predicted)}
            actual = adapter(mode, "".join(f"{re} {im}\n" for re, im in data), name)
            passed(name, compare(expected, actual, name), hand_derived=anchor is not None)

        zero = [(0, 0)] * 256
        delta = [(32768, 0)] + zero[1:]
        constant = [(32768, 0)] * 256
        alternating = [(32768 if n % 2 == 0 else -32768, 0) for n in range(256)]
        check_transform("fft_zero", "fft", zero, zero)
        check_transform("fft_delta", "fft", delta, [(128, 0)] * 256)
        check_transform("fft_constant", "fft", constant, delta)
        check_transform("fft_nyquist", "fft", alternating, zero[:128] + [(32768, 0)] + zero[129:])
        check_transform("ifft_dc", "ifft", delta, constant)
        # +j DC proves complex direction without a floating transform.
        check_transform("ifft_imaginary_dc", "ifft", [(0, 32768)] + zero[1:], [(0, 32768)] * 256)
        k64 = zero.copy()
        k64[64] = (32768, 0)
        check_transform("ifft_positive_quarter_rate", "ifft", k64,
                        [(32768, 0), (0, 32768), (-32768, 0), (0, -32768)] * 64)
        # Fixed local LCG provides reproducible odd signed inputs, independent of any production PRNG.
        seed, real = 0x13579BDF, []
        for _ in range(256):
            seed = (1664525 * seed + 1013904223) & 0xFFFFFFFF
            real.append(((seed >> 12) % 200001 - 100000, 0))
        check_transform("fft_mixed_signed_rounding", "fft", real)
        check_transform("ifft_mixed_complex_rounding", "ifft", [(re, -real[-i-1][0]) for i, (re, _) in enumerate(real)])
        pairs = zero.copy()
        pairs[0], pairs[128], pairs[1], pairs[255], pairs[2], pairs[254] = (7, 9), (-8, 13), (4, -2), (-1, 1), (-4, 2), (1, -1)
        can = canonical(pairs)
        if can[1] != (2, -2) or can[255] != (2, 2) or can[2] != (-2, 2):
            raise ValueError("canonical signed tie anchor")
        actual = adapter("canonical", "".join(f"{r} {i}\n" for r, i in pairs), "canonical_ties")
        passed("canonical_ties", compare({("S", 0, "canonical", k): v for k, v in enumerate(can)}, actual, "canonical"))
        canonical_input = zero.copy()
        canonical_input[0] = (1, 0)
        canonical_input[1], canonical_input[255] = (3, 4), (3, -4)
        canonical_input[128] = (5, 0)
        for threshold in (0, 24, 25, 26, (1 << 56) - 1):
            bins, stats, _ = mask(canonical_input, threshold, 0)
            expected = {("B", b[0], b[1]): b[2:] for b in bins}
            expected[("F", 0)] = stats[1:]
            actual = adapter("mask", "".join(f"{r} {i}\n" for r, i in canonical_input), f"mask_{threshold}", [threshold])
            passed(f"mask_{threshold}", compare(expected, actual, "mask"))

        vectors = json.loads((root / "artifacts/test_vectors/test_vectors.json").read_text())["vectors"]
        core = json.loads((root / "spec/generated/core_config.json").read_text())
        required_baseline = dict(N=12, L=256, P=8, H=128, F=15, G=128, D=384, PROTECT_DC=1, PROTECT_NYQ=0)
        if any(core["configuration"].get(k) != v for k, v in required_baseline.items()):
            raise ValueError("V1 driver only qualifies the declared baseline geometry")
        final_records = None
        for name in CASES:
            directory = evidence / name
            directory.mkdir()
            vector = next(v for v in vectors if v["name"] == name)
            source = root / "artifacts/test_vectors" / name
            config_doc = json.loads((source / "config.json").read_text())
            cfg = config_doc["configuration"]
            for field in ("N", "L", "P", "H", "F", "G", "D", "PROTECT_DC", "PROTECT_NYQ"):
                if cfg[field] != core["configuration"][field]:
                    raise ValueError(f"unsupported configuration: {name}.{field}")
            if config_doc["widths"] != core["widths"]:
                raise ValueError("width contract mismatch")
            if any(config_doc["contract"].get(k) != v for k, v in core["contract"].items()):
                raise ValueError("arithmetic contract mismatch")
            threshold = int(cfg["THR2"])
            if threshold != int(vector["THR2"]) or cfg["Ns"] != vector["Ns"]:
                raise ValueError("vector threshold/count mismatch")
            for table in tables:
                if sha(coeff / f"{table}.memh") != config_doc["hashes"][table + "_sha256"]:
                    raise ValueError("coefficient hash mismatch")
            if sha(source / "x_in.memh") != config_doc["stream_hashes"]["x_in_sha256"]:
                raise ValueError("input hash mismatch")
            samples = read_memh(source / "x_in.memh", 12, True, cfg["Ns"])
            expected = run(samples, threshold, window, forward, inverse)
            if expected[("G",)] != (cfg["Ns"], cfg["frames"], cfg["frames"] * 128, cfg["Ny"]):
                raise ValueError("independent active-window geometry disagrees with config")
            emit_oracle(directory / "oracle", expected)
            emitted_y = read_memh(directory / "oracle/y_out.memh", 12, True, cfg["Ny"])
            if emitted_y != [expected[("Y", n)][0] for n in range(cfg["Ny"])]:
                raise ValueError("oracle MEMH serialization round trip")
            # Round-trip the exported complex boundary before handing it to RTL.
            with (directory / "oracle/ifft_output.csv").open(newline="", encoding="ascii") as stream:
                reader = csv.reader(stream)
                if next(reader) != ["frame_idx", "offset", "re", "im"]:
                    raise ValueError("IFFT export header")
                exported_ifft = [tuple(map(int, row)) for row in reader]
            expected_ifft = [(f, i) + expected[("S", f, "ifft", i)]
                             for f in range(cfg["frames"]) for i in range(256)]
            if exported_ifft != expected_ifft:
                raise ValueError("IFFT export serialization round trip")
            emit_sv_header(directory / "oracle", expected, name, threshold, sha(source / "x_in.memh"))
            emitted_names = {"y_out.memh", "frame_stats.csv", "bin_stats.csv", "metrics.json",
                             "ifft_output.csv", "trecap_artifact_expectations_pkg.sv"}
            emitted_paths = list((directory / "oracle").iterdir())
            if {p.name for p in emitted_paths} != emitted_names or any(not p.is_file() for p in emitted_paths):
                raise ValueError("unexpected oracle bundle inventory")
            oracle_artifact_sha256 = {p.name: sha(p) for p in sorted(emitted_paths)}
            output = execute([exe, "run", coeff, source / "x_in.memh", threshold], name + "/adapter", timeout=90)
            actual = parse_records(output)
            count = compare(expected, actual, name)
            frozen = frozen_records(root, name, cfg)
            kinds = {k[0] for k in frozen}
            selected = {k: v for k, v in expected.items() if k[0] in kinds}
            frozen_count = compare(selected, frozen, name + " frozen outputs")
            passed(name, count, frozen_records=frozen_count, frames=cfg["frames"], outputs=cfg["Ny"],
                   bins=cfg["frames"] * 129, intermediate_complex_words=cfg["frames"] * 256 * 6,
                   ifft_export_rows=len(exported_ifft), ifft_export_sha256=sha(directory / "oracle/ifft_output.csv"),
                   oracle_artifact_sha256=oracle_artifact_sha256,
                   threshold=str(threshold), frozen_bin_artifact=("B" in kinds))
            final_records = expected
        # Negative checker witnesses are deliberate transcript corruptions, not DUT failures.
        corruption_count = 0
        for kind in ("Y", "F", "B", "M", "S", "G"):
            key = next(k for k in final_records if k[0] == kind)
            corrupt = dict(final_records)
            value = corrupt[key]
            corrupt[key] = (value[0] + 1,) + value[1:]
            try:
                compare(final_records, corrupt, "injected " + kind)
            except ValueError:
                corruption_count += 1
            else:
                raise ValueError("checker missed deliberate value corruption")
        for change in ("missing", "extra"):
            corrupt = dict(final_records)
            if change == "missing":
                del corrupt[("Y", 0)]
            else:
                corrupt[("Y", 999999)] = (0,)
            try:
                compare(final_records, corrupt, change)
            except ValueError:
                corruption_count += 1
            else:
                raise ValueError("checker missed cardinality corruption")
        for bad in ("", "Y\t0\t0", "Y\t0\t0\nY\t0\t0\n", "Y\t1\t0\n", "BAD\t0\n"):
            try:
                parse_records(bad)
            except ValueError:
                corruption_count += 1
            else:
                raise ValueError("parser accepted deliberate malformed transcript")
        passed("checker_negative_witnesses", corruption_count)
        compare(final_records, dict(final_records), "checker positive witness")
        report["status"] = "PASS_BOUNDED_BASELINE_WITH_PUBLIC_API_FINDINGS" if report["public_api_findings"] else "PASS_BOUNDED_BASELINE"
    except Exception as error:
        report["status"] = "FAIL"
        report["failure"] = str(error)
        print(f"FAIL {error}", file=sys.stderr, flush=True)
    finally:
        changed = [name for name, digest in before.items() if not (root / name).is_file() or sha(root / name) != digest]
        report["input_identity_unchanged"] = not changed
        if changed:
            report["status"] = "FAIL"
            report["changed_inputs"] = changed
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(evidence / "report.json", report)
        summary = ["# Bounded reference qualification", "", f"Status: {report['status']}", "",
                   "This report qualifies only the selected reference arithmetic scope; it does not qualify RTL or board behavior.", "",
                   "| Check | Result | Records |", "| --- | --- | ---: |"]
        summary += [f"| {c['name']} | {c['status']} | {c['records']} |" for c in report["checks"]]
        summary += ["", "## Unresolved public API findings", ""]
        summary += [f"- rnd_shr({f['value']}, {f['shift']}): expected {f['expected']}, observed {f['actual']}. Outside baseline shifts 0/1/15."
                    for f in report["public_api_findings"]]
        summary += ["", "## Limits", ""] + [f"- {v}" for v in report["limitations"]]
        if "failure" in report:
            summary += ["", "Failure: " + report["failure"]]
        summary += ["", f"Frozen/input identities unchanged: {report['input_identity_unchanged']}",
                    "All V1 requirements qualified: false", ""]
        (evidence / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8", newline="\n")
    print(f"Evidence: {evidence}", flush=True)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())