#!/usr/bin/env python3
"""Reproduce the finite measurement-shell simulation with native ModelSim.

Only the new run directory is written. The repository remains the simulation
working directory so that the checked-in relative ROM paths resolve unchanged.
Use --dry-run to inspect commands and input hashes without launching tools.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


FILELIST = "filelists/rtl_core_plus_fft.f"
ENGINE = "platform/de1soc/measurement/trecap_measurement_engine.sv"
TESTBENCH = "sim/verification/measurement_engine_tb.sv"
BUILD_PACKAGE = "rtl/include/trecap_build_pkg.sv"
MINIMUM_CHECKS = 101
RECIPE = "onerror {quit -code 1}; run -all; quit -code 0"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()


def require_file(path):
    if not path.is_file():
        raise ValueError("Required file is missing: " + str(path))
    return path


def relative(path, repo):
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_filelist(repo):
    """Preserve canonical source order and expand the documented incdir syntax."""
    arguments, sources, include_dirs = [], [], []
    for raw in require_file(repo/FILELIST).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if line.startswith("+incdir+"):
            for entry in line[len("+incdir+"):].split("+"):
                directory = (repo/entry.strip('"')).resolve()
                if not directory.is_dir():
                    raise ValueError("Missing include directory: " + str(directory))
                include_dirs.append(directory)
                arguments.append("+incdir+" + directory.as_posix())
        elif line.startswith(("+", "-")):
            raise ValueError("Unsupported filelist directive; review before extending runner: " + line)
        else:
            source = require_file((repo/line.strip('"')).resolve())
            sources.append(source)
            arguments.append(source.as_posix())
    for name in (ENGINE, TESTBENCH):
        source = require_file(repo/name)
        sources.append(source)
        arguments.append(source.as_posix())
    return arguments, sources, include_dirs


def source_roms(repo):
    paths = []
    groups = (
        (ENGINE, ("X_FILE", "DENSE_FILE", "MASKED_FILE")),
        (BUILD_PACKAGE, ("TBUILD_WINDOW_QW_MEMH", "TBUILD_TWIDDLE_RE_MEMH",
                         "TBUILD_TWIDDLE_IM_MEMH", "TBUILD_TWIDDLE_INV_RE_MEMH",
                         "TBUILD_TWIDDLE_INV_IM_MEMH")),
    )
    for filename, names in groups:
        content = require_file(repo/filename).read_text(encoding="utf-8-sig")
        for name in names:
            match = re.search(r"\b" + re.escape(name) + r'\s*=\s*"([^"\r\n]+)"', content)
            if not match:
                raise ValueError("Cannot resolve literal ROM binding " + name + " in " + filename)
            paths.append(require_file((repo/match.group(1)).resolve()))
    return paths


def input_inventory(repo, sources, includes):
    by_path = {}
    def add(path, role):
        key = relative(path, repo)
        entry = by_path.setdefault(key, {"path": key, "roles": [],
                                         "bytes": path.stat().st_size, "sha256": digest(path)})
        if role not in entry["roles"]:
            entry["roles"].append(role)
    add(repo/FILELIST, "filelist")
    for source in sources:
        add(source, "compiled_source")
    for directory in includes:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in (".sv", ".svh", ".v", ".vh"):
                add(path.resolve(), "include_directory_source")
    for path in source_roms(repo):
        add(path, "simulation_rom")
    return list(by_path.values())


def error_summary(log):
    counts = [int(value) for value in re.findall(r"\bErrors:\s*(\d+)", log)]
    diagnostics = re.findall(r"(?im)^\s*(?:#\s*)?\*\*\s*(?:Error|Fatal)\b.*$", log)
    return {"error_summary_counts": counts, "error_diagnostics": diagnostics,
            "warning_summary_counts": [int(v) for v in re.findall(r"\bWarnings:\s*(\d+)", log)]}


def validate_log(stage, log):
    result = error_summary(log)
    if result["error_diagnostics"] or any(result["error_summary_counts"]):
        raise ValueError(stage + " contains simulator errors")
    if stage in ("compile", "simulate") and not result["error_summary_counts"]:
        raise ValueError(stage + " is missing the required zero-error summary")
    if stage == "simulate":
        if re.search(r"MEASUREMENT_(?:FAIL|TEST_TIMEOUT)", log):
            raise ValueError("Testbench reported failure or timeout")
        checks = [int(v) for v in re.findall(r"MEASUREMENT_ENGINE_PASS\s+checks=(\d+)", log)]
        if len(checks) != 1 or checks[0] < MINIMUM_CHECKS:
            raise ValueError("Expected one MEASUREMENT_ENGINE_PASS banner with at least 101 checks")
        result["measurement_engine_checks"] = checks[0]
        result["batch_pass_lines"] = [line.strip() for line in log.splitlines()
                                      if "MEASUREMENT_BATCH_PASS" in line]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--simulator-dir", type=Path, required=True,
                        help="Native ModelSim directory containing vlib/vmap/vlog/vsim")
    parser.add_argument("--run-dir", type=Path, required=True, help="Must not already exist")
    parser.add_argument("--timeout-s", type=float, default=300,
                        help="Timeout for each tool invocation (default: 300 seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Write plan/hashes only; launch no tools")
    args = parser.parse_args()
    repo, run, simulator = args.repo.resolve(), args.run_dir.resolve(), args.simulator_dir.resolve()
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be positive")
    if run.exists():
        parser.error("--run-dir already exists; choose a new directory")
    try:
        compile_args, sources, includes = resolve_filelist(repo)
        inputs = input_inventory(repo, sources, includes)
        tools = {}
        for name in ("vlib", "vmap", "vlog", "vsim"):
            candidate = simulator/(name+".exe")
            tools[name] = require_file(candidate if candidate.is_file() else simulator/name)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    run.mkdir(parents=True, exist_ok=False)
    ini, library = (run/"modelsim.ini").as_posix(), (run/"work").as_posix()
    planned = [
        ("vlib", [tools["vlib"].as_posix(), library], run),
        ("vmap", [tools["vmap"].as_posix(), "-c"], run),
        ("compile", [tools["vlog"].as_posix(), "-sv", "-warning", "2892",
                     "-modelsimini", ini, "-work", library, *compile_args], repo),
        ("simulate", [tools["vsim"].as_posix(), "-c", "-modelsimini", ini, "-lib", library,
                      "measurement_engine_tb", "-onfinish", "stop", "-l", (run/"transcript.log").as_posix(),
                      "-wlf", (run/"simulation.wlf").as_posix(), "-do", RECIPE], repo),
    ]
    manifest = {"schema": "measurement-shell-native-simulation-1", "started_utc": utc_now(),
                "status": "planned" if args.dry_run else "running", "repo": repo.as_posix(),
                "run_dir": run.as_posix(), "dry_run": args.dry_run,
                "runner_sha256": digest(Path(__file__).resolve()), "inputs": inputs,
                "tools": [{"name": name, "path": path.as_posix(), "sha256": digest(path),
                           "bytes": path.stat().st_size} for name, path in tools.items()],
                "required_banner": "MEASUREMENT_ENGINE_PASS checks>=101",
                "scope": "Native numerical engine/TB only; no JTAG IP, board programming, or physical measurement.",
                "commands": [{"stage": stage, "argv": argv, "cwd": cwd.as_posix(),
                              "returncode": None, "stdout_log": stage+".stdout.log"}
                             for stage, argv, cwd in planned]}
    def save():
        (run/"manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        (run/"commands.json").write_text(json.dumps(manifest["commands"], indent=2)+"\n", encoding="utf-8")
    (run/"run.do").write_text(RECIPE+"\n", encoding="utf-8")
    save()
    if args.dry_run:
        print(json.dumps({"status": "dry_run_only", "manifest": (run/"manifest.json").as_posix(),
                          "compiled_sources": len(sources), "roms": len(source_roms(repo))}))
        return 0
    try:
        for record, (stage, argv, cwd) in zip(manifest["commands"], planned):
            record["started_utc"] = utc_now()
            beginning = time.monotonic()
            try:
                with (run/record["stdout_log"]).open("w", encoding="utf-8") as handle:
                    completed = subprocess.run(argv, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT,
                                               timeout=args.timeout_s, check=False)
                record["returncode"] = completed.returncode
            finally:
                record["elapsed_s"] = time.monotonic()-beginning
                record["finished_utc"] = utc_now()
                save()
            log = (run/record["stdout_log"]).read_text(encoding="utf-8", errors="replace")
            record["diagnostics"] = error_summary(log)
            if record["returncode"] != 0:
                raise ValueError(stage + " returned " + str(record["returncode"]))
            record["validation"] = validate_log(stage, log)
            save()
            print(stage + " passed", flush=True)
        changed = [entry["path"] for entry in inputs
                   if digest(repo/entry["path"]) != entry["sha256"]]
        manifest["inputs_unchanged_after_run"] = not changed
        if changed:
            raise ValueError("Input files changed during simulation: " + ", ".join(changed))
        manifest["status"] = "passed"
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
    finally:
        manifest["finished_utc"] = utc_now()
        save()
    print(json.dumps({"status": manifest["status"], "manifest": (run/"manifest.json").as_posix(),
                      "error": manifest.get("error")}))
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
