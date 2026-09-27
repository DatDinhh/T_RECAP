#!/usr/bin/env python3
"""Compare production RTL rounding with independently generated integer cases."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import uuid

from simulator_qualification import DIAGNOSTIC, digest, execute


def expected(value: int, shift: int) -> tuple[int, int]:
    # Python integers avoid both minimum-negative abs overflow and narrow bias sums.
    magnitude = abs(value)
    if shift:
        quotient, remainder = divmod(magnitude, 1 << shift)
        magnitude = quotient + int(2 * remainder >= (1 << shift))
    rounded = -magnitude if value < 0 else magnitude
    flags = 1 if rounded > 2047 else (2 if rounded < -2048 else 0)
    return min(2047, max(-2048, rounded)), flags


def cases() -> list[int]:
    values = set(range(-4096, 4097))
    values.update([-(1 << 63), (1 << 63)-1, -(1 << 62), 1 << 62])
    for shift in (1, 4, 15):
        half = 1 << (shift-1)
        for integer in (0, 1, 2, 2046, 2047, 2048, 2049):
            for delta in (-1, 0, 1):
                for sign in (-1, 1):
                    values.add(sign * ((integer << shift) + half + delta))
        for limit in (-2048, 2047):
            for delta in (-1, 0, 1):
                values.add((limit << shift) + delta)
    return sorted(values, key=lambda value: (abs(value), value))


def run(repo: Path, simulator: Path, timeout: float) -> tuple[Path, dict]:
    identity = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8]
    folder = repo/"runs/verification"/("rounding-"+identity)
    folder.mkdir(parents=True, exist_ok=False)
    rows = []
    for value in cases():
        parts = [f"{value & ((1 << 64)-1):016x}"]
        for shift in (0, 1, 4, 15):
            result, flags = expected(value, shift)
            parts += [f"{result & 4095:03x}", str(flags)]
        rows.append(" ".join(parts))
    vectors = folder/"vectors.txt"
    vectors.write_text(str(len(rows))+"\n"+"\n".join(rows)+"\n", encoding="ascii")
    source = repo/"rtl/common/round_sat.sv"
    tb = repo/"sim/verification/arithmetic_rounding_tb.sv"
    packages = [repo/"rtl/include/generated/trecap_core_pkg.sv", repo/"rtl/include/trecap_math_pkg.sv"]
    summary = {"schema_version": 1, "run_id": folder.name, "test_family": "T-AR-01",
               "scope": {"package_helpers": ["sgn", "abs_mag", "asr >=128", "rnd_shr then sat_signed"], "input_width": 64, "output_width": 12, "shifts": [0, 1, 4, 15],
                         "input_cases": len(rows), "comparisons": len(rows)*4,
                         "no_full_parameter_coverage_claim": True},
               "source_sha256": {p.relative_to(repo).as_posix(): digest(p) for p in (source,tb,*packages,Path(__file__).resolve(),repo/"scripts/verification/simulator_qualification.py")},
               "vectors_sha256": digest(vectors), "cases": [], "overall": "NOT_RUN",
               "compile_options": ["-sv", "-warning", "2892", "-work", "work"],
               "defines": []}
    tool = lambda name: str(simulator/(name+".exe"))
    try:
        for name, args in (
            ("library", [tool("vlib"), "work"]),
            ("configuration", [tool("vmap"), "-c"]),
            ("compile", [tool("vlog"), *summary["compile_options"], *(p.as_posix() for p in packages), source.as_posix(), tb.as_posix()]),
        ):
            result = execute(args, folder, folder/(name+".log"), timeout)
            if result["exit_code"] or result["timed_out"] or DIAGNOSTIC.search(result["text"]):
                raise RuntimeError(name+" failed")
        do = folder/"run.do"
        do.write_text("onerror {quit -code 2}\nrun -all\nquit -code 0\n", encoding="ascii")
        for case in ("positive", "corrupt_expectation", "corrupt_helper"):
            capture = folder/(case+".trace")
            selected = vectors
            if case == "corrupt_expectation":
                bad = rows.copy()
                parts = bad[0].split()
                parts[1] = "001"  # The first input is zero; its expected output must not become +1.
                bad[0] = " ".join(parts)
                selected = folder/"corrupt_vectors.txt"
                selected.write_text(str(len(bad))+"\n"+"\n".join(bad)+"\n", encoding="ascii")
            args = [tool("vsim"), "-c", "-onfinish", "stop", "-voptargs=+acc",
                    "work.arithmetic_rounding_tb", "+VECTORS="+selected.as_posix(),
                    "+TRACE="+capture.as_posix(), "-do", do.as_posix()]
            if case == "corrupt_helper":
                args.insert(-2, "+INJECT_HELPER_ERROR")
            result = execute(args, folder, folder/(case+".log"), timeout)
            if case == "positive":
                expected_trace = [f"TRECAP_ROUND_TRACE_V1 {len(rows)}", *rows, f"complete {len(rows)}"]
                trace_ok = capture.is_file() and capture.read_text(encoding="ascii").splitlines() == expected_trace
                passed = (not result["timed_out"] and result["exit_code"] == 0
                          and not DIAGNOSTIC.search(result["text"]) and trace_ok
                          and f"TRECAP_ROUND_COMPLETED rows={len(rows)}" in result["text"])
            else:
                marker = "ROUND_HELPER_MISMATCH" if case == "corrupt_helper" else "ROUND_MISMATCH"
                passed = (not result["timed_out"] and marker+" row=0 shift_slot=0" in result["text"]
                          and "TRECAP_ROUND_COMPLETED" not in result["text"])
            summary["cases"].append({"case": case, "outcome": "PASS" if passed else "FAIL",
                                     **{k:v for k,v in result.items() if k != "text"},
                                     "capture_sha256": digest(capture) if capture.exists() else None})
        summary["overall"] = "PASS" if all(c["outcome"] == "PASS" for c in summary["cases"]) else "FAIL"
    except (OSError, RuntimeError) as exc:
        summary["overall"] = "FAIL_INFRASTRUCTURE"
        summary["failure"] = str(exc)
    (folder/"summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    return folder, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument("--simulator-dir",type=Path)
    parser.add_argument("--timeout",type=float,default=90)
    args=parser.parse_args()
    candidate=shutil.which("vsim")
    simulator=args.simulator_dir or (Path(candidate).parent if candidate else None)
    if simulator is None: parser.error("Pass --simulator-dir or put vsim on PATH")
    folder,result=run(args.repo.resolve(),simulator.resolve(),args.timeout)
    print(json.dumps({"run":folder.relative_to(args.repo.resolve()).as_posix(),
                      "overall":result["overall"],"scope":result["scope"],
                      "failure":result.get("failure")},indent=2))
    return 0 if result["overall"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
