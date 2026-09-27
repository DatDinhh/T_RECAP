#!/usr/bin/env python3
"""Run isolated finite-core replay against a previously qualified oracle bundle."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import uuid

from simulator_qualification import DIAGNOSTIC, digest, execute, resolve_filelist

VECTORS = ("impulse_Ns1024_thr0", "near_threshold_multitone_Ns1024_thr64")
PASS_REFERENCE = {"PASS_BOUNDED_BASELINE", "PASS_BOUNDED_BASELINE_WITH_PUBLIC_API_FINDINGS",
                  "PASS_BOUNDED_BOUNDARY_VECTORS"}


def read_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def selected_vectors(report: dict, requested: list[str] | None) -> list[str]:
    vectors = requested if requested is not None else report.get("default_vectors", list(VECTORS))
    if (not isinstance(vectors, list) or not vectors
            or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name)
                   for name in vectors) or len(set(vectors)) != len(vectors)):
        raise ValueError("Vector selection must contain unique safe case names")
    return vectors


def reference_input(repo: Path, evidence: Path, report: dict, check: dict,
                    identities: dict) -> Path:
    name = check["name"]
    artifact = check.get("input_artifact")
    if artifact is None:
        if report["status"] == "PASS_BOUNDED_BOUNDARY_VECTORS" or name not in VECTORS:
            raise ValueError("Supplemental vector requires a qualified input artifact")
        path = repo/"artifacts/test_vectors"/name/"x_in.memh"
    else:
        if report.get("campaign") != "short_length_boundaries":
            raise ValueError("Unsupported supplemental input campaign")
        relative = Path(artifact["path"])
        if relative.is_absolute():
            raise ValueError("Supplemental input path must be repository relative")
        path = (repo/relative).resolve()
        path.relative_to((evidence/name/"input").resolve())
        cfg = check["configuration"]
        ns = cfg["Ns"]
        if type(ns) is not int or not 1 <= ns <= 65536:
            raise ValueError("Supplemental input needs a supported positive Ns")
        frames = (ns + 254)//128
        if cfg.get("frames") != frames or cfg.get("Ny") != frames*128+384:
            raise ValueError("Supplemental input geometry disagrees with baseline")
        threshold = cfg.get("THR2")
        if isinstance(threshold, str) and re.fullmatch(r"0|[1-9][0-9]*", threshold):
            threshold = int(threshold)
        if type(threshold) is not int or not 0 <= threshold < (1 << 56):
            raise ValueError("Supplemental input threshold is outside unsigned 56-bit domain")
        if artifact.get("rows") != ns or artifact.get("width_bits") != 12 or artifact.get("signed") is not True:
            raise ValueError("Supplemental input encoding disagrees with baseline")
        if artifact.get("sha256") != digest(path):
            raise ValueError("Supplemental input artifact changed")
        if not re.fullmatch(rb"(?:[0-9a-f]{3}\n){"+str(ns).encode()+rb"}", path.read_bytes()):
            raise ValueError("Supplemental input is not canonical signed-12 MEMH")
        package = (evidence/name/"oracle/trecap_artifact_expectations_pkg.sv").read_text(encoding="ascii")
        expected_constants = {"TEXP_VECTOR_NAME": '"'+name+'"', "TEXP_NS": str(ns),
                              "TEXP_NY": str(frames*128+384), "TEXP_FRAMES": str(frames),
                              "TEXP_UNIQUE_BINS": "129", "TEXP_BIN_ROWS": str(frames*129),
                              "TEXP_THR2": "56'd"+str(threshold)}
        for label, expected in expected_constants.items():
            declarations = re.findall(r"^\s*localparam[^;\n]*\b"+label+r"\s*=\s*([^;\n]+);\s*$",
                                      package, flags=re.MULTILINE)
            if len(declarations) != 1 or declarations[0].strip() != expected:
                raise ValueError("Compiled expectation package disagrees with qualified configuration: "+label)
        geometry = read_json(evidence/name/"oracle/metrics.json")["geometry"]
        if geometry != {"Ns": ns, "Nframes": frames, "tau_last": frames*128, "Ny": frames*128+384}:
            raise ValueError("Supplemental configuration and oracle geometry disagree")
    relative_name = path.relative_to(repo).as_posix()
    if identities.get(relative_name) != digest(path):
        raise ValueError("Vector input is absent from qualified input identities")
    return path


def verify_reference(repo: Path, evidence: Path, vectors: list[str]) -> dict:
    selected_vectors({}, vectors)
    evidence.resolve().relative_to((repo/"runs/verification").resolve())
    report = read_json(evidence/"report.json")
    if report.get("status") not in PASS_REFERENCE or report.get("input_identity_unchanged") is not True:
        raise ValueError("Reference evidence is not an accepted bounded numerical qualification")
    identity_path = evidence/"input_identities.json"
    if report.get("input_identities_sha256") != digest(identity_path):
        raise ValueError("Reference input identity manifest changed")
    identities = read_json(identity_path)
    if not isinstance(identities, dict) or not identities:
        raise ValueError("Reference input identities must be a nonempty mapping")
    qualified_sources = report.get("qualification_sources")
    if not isinstance(qualified_sources, dict) or not qualified_sources:
        raise ValueError("Reference qualification source identities are absent")
    if any(identities.get(name) != value for name, value in qualified_sources.items()):
        raise ValueError("Reference qualification source identities disagree")
    for name, expected_hash in identities.items():
        source = (repo/name).resolve()
        source.relative_to(repo)
        if not source.is_file() or digest(source) != expected_hash:
            raise ValueError("Qualified reference input/source identity changed: " + name)
    for name in vectors:
        checks = [c for c in report["checks"] if c["name"] == name]
        if len(checks) != 1 or checks[0]["status"] != "PASS":
            raise ValueError("Vector not uniquely qualified: " + name)
        reference_input(repo, evidence, report, checks[0], identities)
        bundle = evidence/name/"oracle"
        pinned_outputs = checks[0].get("oracle_artifact_sha256", {})
        if not pinned_outputs:
            raise ValueError("Reference report does not pin all emitted oracle artifacts")
        for filename in ("y_out.memh", "frame_stats.csv", "bin_stats.csv",
                         "metrics.json", "ifft_output.csv", "trecap_artifact_expectations_pkg.sv"):
            if not (bundle/filename).is_file():
                raise ValueError("Missing qualified expectation: " + name + "/" + filename)
            if pinned_outputs.get(filename) != digest(bundle/filename):
                raise ValueError("Qualified expectation identity changed: " + name + "/" + filename)
    return report


def run(repo: Path, simulator: Path, reference: Path, environment: Path, vectors: list[str],
        variants: list[str], timeout: float, negative: bool) -> tuple[Path, dict]:
    from core_capture_check import check_capture
    identity = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8]
    folder = repo/"runs/verification"/("core-"+identity)
    folder.mkdir(parents=True, exist_ok=False)
    summary = {"schema_version": 1, "run_id": folder.name,
               "scope": "selected static finite source/core replay, exact complex IFFT and terminal accounting",
               "test_families_partial": ["T-C-01", "T-C-02", "T-C-03", "T-C-08", "T-ENV-02"],
               "reference_run": reference.relative_to(repo).as_posix(),
               "defines": [], "compile_options": ["-sv", "-warning", "2892", "-work", "work"],
               "simulation_options": ["-c", "-onfinish", "stop", "-voptargs=+acc"],
               "cases": [], "overall": "NOT_RUN"}
    tool = lambda name: str(simulator/(name+".exe"))
    try:
        environment.resolve().relative_to((repo/"runs/verification").resolve())
        environment_report = read_json(environment/"summary.json")
        if environment_report.get("overall") != "PASS":
            raise ValueError("Environment qualification is not PASS")
        for name, expected_hash in environment_report["tool_sha256"].items():
            if digest(Path(tool(name))) != expected_hash:
                raise ValueError("Simulator tool changed after qualification: "+name)
        helper_path = "scripts/verification/simulator_qualification.py"
        if environment_report["source_sha256"].get(helper_path) != digest(repo/helper_path):
            raise ValueError("Native process runner changed after environment qualification")
        summary["environment_run"] = environment.relative_to(repo).as_posix()
        summary["environment_report_sha256"] = digest(environment/"summary.json")
        qualified = verify_reference(repo, reference, vectors)
        summary["reference_status"] = qualified["status"]
        summary["reference_campaign"] = qualified.get("campaign", "frozen_baseline")
        input_identities = read_json(reference/"input_identities.json")
        input_paths = {name: reference_input(repo, reference, qualified,
                      next(c for c in qualified["checks"] if c["name"] == name and c["status"] == "PASS"),
                      input_identities) for name in vectors}
        summary["reference_report_sha256"] = digest(reference/"report.json")
        summary["reference_identity_sha256"] = digest(reference/"input_identities.json")
        core_args, sources = resolve_filelist(repo, repo/"filelists/rtl_core_plus_fft.f")
        tb_args, tb_sources = resolve_filelist(repo, repo/"sim/filelists/verification_core.f")
        sources += tb_sources + [repo/"filelists/rtl_core_plus_fft.f", repo/"sim/filelists/verification_core.f",
                                  Path(__file__).resolve(), repo/"scripts/verification/core_capture_check.py",
                                  repo/"scripts/verification/simulator_qualification.py"]
        summary["source_sha256"] = {p.relative_to(repo).as_posix(): digest(p) for p in sources}
        summary["tool_sha256"] = {name: digest(Path(tool(name))) for name in ("vlib", "vmap", "vlog", "vsim")}
        summary["expected_sha256"] = {}
        summary["staged_rom_sha256"] = {}
        for vector in vectors:
            work = folder/vector
            work.mkdir()
            # The DUT retains repository-relative ROM names. Stage exact admitted
            # bytes under the same relative names inside this isolated working dir.
            rom_dir = work/"artifacts/coefficients"
            rom_dir.mkdir(parents=True)
            for rom_name in ("window_qw.memh", "twiddle_re.memh", "twiddle_im.memh",
                             "twiddle_inv_re.memh", "twiddle_inv_im.memh"):
                rom_source = repo/"artifacts/coefficients"/rom_name
                staged = rom_dir/rom_name
                staged.write_bytes(rom_source.read_bytes())
                if digest(staged) != digest(rom_source):
                    raise ValueError("ROM staging changed bytes: "+rom_name)
                summary["staged_rom_sha256"][staged.relative_to(folder).as_posix()] = digest(staged)
            bundle = reference/vector/"oracle"
            x_path = input_paths[vector]
            expected_files = [x_path, *sorted(p for p in bundle.iterdir() if p.is_file())]
            summary["expected_sha256"].update({p.relative_to(repo).as_posix(): digest(p) for p in expected_files})
            setup_ok = True
            for stage, args in (
                ("library", [tool("vlib"), "work"]),
                ("configuration", [tool("vmap"), "-c"]),
                ("compile", [tool("vlog"), *summary["compile_options"], *core_args,
                             (bundle/"trecap_artifact_expectations_pkg.sv").as_posix(), *tb_args]),
            ):
                result = execute(args, work, work/(stage+".log"), timeout)
                if result["timed_out"] or result["exit_code"] or DIAGNOSTIC.search(result["text"]):
                    summary["cases"].append({"vector": vector, "variant": stage,
                                             "outcome": "FAIL_INFRASTRUCTURE",
                                             **{k:v for k,v in result.items() if k != "text"}})
                    setup_ok = False
                    break
            if not setup_ok:
                continue
            do_file = work/"run.do"
            do_file.write_text("onerror {quit -code 2}\nrun -all\nquit -code 0\n", encoding="ascii")
            selected_variants = list(variants)
            if negative and vector == vectors[0]:
                selected_variants.append("reject_wrong_y")
            for variant in selected_variants:
                case_folder = work/variant
                capture = case_folder/"capture"
                capture.mkdir(parents=True)
                y_path = bundle/"y_out.memh"
                if variant == "reject_wrong_y":
                    rows = y_path.read_text(encoding="ascii").splitlines()
                    rows[0] = f"{(int(rows[0],16)^1):03x}"
                    y_path = case_folder/"wrong_y.memh"
                    y_path.write_bytes(("\n".join(rows)+"\n").encode("ascii"))
                params = {"X_FILE": x_path, "Y_FILE": y_path,
                          "FRAME_FILE": bundle/"frame_stats.csv",
                          "BIN_FILE": bundle/"bin_stats.csv",
                          "IFFT_FILE": bundle/"ifft_output.csv"}
                args = [tool("vsim"), *summary["simulation_options"], "work.core_finite_replay_tb"]
                args += ["-g"+name+"="+path.as_posix() for name,path in params.items()]
                args += ["-gFINAL_STALL_CYCLES="+("37" if variant=="stalled" else "0"),
                         "-gSTALL_PATTERN="+("1" if variant=="stalled" else "0"),
                         "+CORE_CAPTURE_DIR="+capture.as_posix(), "-do", do_file.as_posix()]
                result = execute(args, work, case_folder/"simulation.log", timeout)
                case = {"vector": vector, "variant": variant,
                        "capture": capture.relative_to(folder).as_posix(),
                        "stall_lfsr_seed": "0x1ace" if variant=="stalled" else None,
                        **{k:v for k,v in result.items() if k != "text"}}
                if variant == "reject_wrong_y":
                    case["outcome"] = ("PASS_EXPECTED_REJECTION" if not result["timed_out"]
                        and "CORE_MISMATCH" in result["text"] and "CORE_RTL_PASS" not in result["text"]
                        and re.search(r"CORE_MISMATCH[^\n]*(?:y value|y_out|sample tap y)", result["text"])
                        else "FAIL_CHECKER")
                elif result["timed_out"]:
                    case["outcome"] = "TIMEOUT"
                elif result["exit_code"] or DIAGNOSTIC.search(result["text"]):
                    case["outcome"] = "FAIL_DUT"
                elif any(marker not in result["text"] for marker in ("CORE_RTL_PASS", "CORE_COMPLETION_COUNTS", "CORE_IFFT_EXACT")):
                    case["outcome"] = "FAIL_INFRASTRUCTURE"
                    case["reason"] = "Missing explicit completion events"
                else:
                    try:
                        checked = check_capture(capture, bundle, x_path)
                        case["postcheck"] = checked
                        case["outcome"] = "PASS" if checked.get("outcome") == "PASS" else "FAIL_CAPTURE"
                    except (OSError, ValueError, AssertionError) as exc:
                        case["outcome"] = "FAIL_CAPTURE"
                        case["reason"] = str(exc)
                case["capture_sha256"] = {p.name:digest(p) for p in capture.iterdir() if p.is_file()}
                summary["cases"].append(case)
        final_identity = {p.relative_to(repo).as_posix(): digest(p) for p in sources}
        summary["source_identity_unchanged"] = final_identity == summary["source_sha256"]
        expected_unchanged = all((repo/p).is_file() and digest(repo/p) == h for p,h in summary["expected_sha256"].items())
        summary["expected_identity_unchanged"] = expected_unchanged
        summary["staged_rom_identity_unchanged"] = all(
            digest(folder/path) == expected for path,expected in summary["staged_rom_sha256"].items())
        verify_reference(repo, reference, vectors)
        summary["reference_evidence_unchanged"] = (
            digest(reference/"report.json") == summary["reference_report_sha256"]
            and digest(reference/"input_identities.json") == summary["reference_identity_sha256"])
        count = len(vectors)*len(variants)+(1 if negative else 0)
        summary["overall"] = ("PASS_SELECTED_CORE_CASES" if len(summary["cases"])==count
                              and summary["source_identity_unchanged"] and expected_unchanged
                              and summary["staged_rom_identity_unchanged"] and summary["reference_evidence_unchanged"]
                              and all(c["outcome"].startswith("PASS") for c in summary["cases"]) else "FAIL")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        summary["overall"] = "FAIL_INFRASTRUCTURE"
        summary["failure"] = str(exc)
    summary["utc_end"] = datetime.now(timezone.utc).isoformat()
    (folder/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8",newline="\n")
    return folder,summary


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument("--reference-run",type=Path,required=True)
    parser.add_argument("--environment-run",type=Path,required=True)
    parser.add_argument("--simulator-dir",type=Path)
    parser.add_argument("--vector",action="append", help="Qualified case name; repeat to select a subset")
    parser.add_argument("--variant",choices=("static","stalled"),action="append")
    parser.add_argument("--timeout",type=float,default=180)
    parser.add_argument("--skip-negative",action="store_true")
    args=parser.parse_args()
    repo=args.repo.resolve()
    reference=args.reference_run if args.reference_run.is_absolute() else repo/args.reference_run
    environment=args.environment_run if args.environment_run.is_absolute() else repo/args.environment_run
    candidate=shutil.which("vsim")
    simulator=args.simulator_dir or (Path(candidate).parent if candidate else None)
    if simulator is None: parser.error("Pass --simulator-dir or put vsim on PATH")
    try:
        vectors = selected_vectors(read_json(reference/"report.json"), args.vector)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    folder,result=run(repo,simulator.resolve(),reference.resolve(),environment.resolve(),vectors,
                      args.variant or ["static","stalled"],args.timeout,not args.skip_negative)
    print(json.dumps({"run":folder.relative_to(repo).as_posix(),"overall":result["overall"],
                      "cases":[{k:c[k] for k in ("vector","variant","outcome")} for c in result["cases"]],
                      "failure":result.get("failure")},indent=2))
    return 0 if result["overall"]=="PASS_SELECTED_CORE_CASES" else 1


if __name__=="__main__":
    raise SystemExit(main())
