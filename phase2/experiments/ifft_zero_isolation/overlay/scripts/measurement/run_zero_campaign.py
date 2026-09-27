#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compare masked baseline and isolated IFFT in one protocol2 FPGA image.

Experimental runner derived from the qualified dense/masked acquisition protocol.
All timing, serial-capture, output-count and fault admission gates are retained.

This script never programs the FPGA or changes its source/image. Running main
does open the selected Feather serial port and sends finite JTAG batch commands.
UTC-to-QPC conversion has explicit, conditional timing bounds; it is not sensor
calibration. Importing the module performs no hardware or process operations.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def strict_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def jsonl(path, partial=False):
    data = Path(path).read_bytes()
    if partial and not data.endswith(b"\n"):
        data = data[:data.rfind(b"\n") + 1]
    return [strict_json(line) for line in data.decode("utf-8-sig").splitlines() if line.strip()]


def integer(obj, key, minimum=0):
    value = obj[key]
    if type(value) is not int or value < minimum:
        raise ValueError("Invalid integer " + key)
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class WindowsQPC:
    """Raw global Windows QPC, matching .NET Stopwatch.GetTimestamp()."""
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("This campaign runner requires Windows raw QPC")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.counter = kernel.QueryPerformanceCounter
        self.counter.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
        self.counter.restype = ctypes.c_int
        frequency_fn = kernel.QueryPerformanceFrequency
        frequency_fn.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
        frequency_fn.restype = ctypes.c_int
        value = ctypes.c_longlong()
        if not frequency_fn(ctypes.byref(value)) or value.value <= 0:
            raise ctypes.WinError(ctypes.get_last_error())
        self.frequency = value.value

    def read(self):
        value = ctypes.c_longlong()
        if not self.counter(ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.value


def check_anchors(anchors, frequency, step_tolerance_ns=10_000_000, utc_resolution_ns=1):
    if len(anchors) < 2:
        raise ValueError("Need at least two host clock anchors")
    for row in anchors:
        if integer(row, "qpc_frequency", 1) != frequency:
            raise ValueError("Anchor QPC frequency changed")
        if integer(row, "qpc_after") < integer(row, "qpc_before"):
            raise ValueError("Reversed UTC/QPC sampling bracket")
        integer(row, "utc_ns", 1)
    for a, b in zip(anchors, anchors[1:]):
        if b["qpc_before"] <= a["qpc_after"] or b["utc_ns"] <= a["utc_ns"]:
            raise ValueError("Host UTC or QPC moved backwards")
        delta_utc = b["utc_ns"] - a["utc_ns"]
        qlo = (b["qpc_before"] - a["qpc_after"]) * 1_000_000_000 // frequency
        qhi = -(-((b["qpc_after"] - a["qpc_before"]) * 1_000_000_000) // frequency)
        tolerance = step_tolerance_ns + 2 * utc_resolution_ns
        if delta_utc < qlo - tolerance or delta_utc > qhi + tolerance:
            raise ValueError("UTC/QPC clock step exceeds the 10 ms admission limit")


def utc_ms_bounds(value, anchors, frequency, guard_ns=20_000_000,
                  utc_resolution_ns=1, maximum_anchor_distance_ns=5_000_000_000):
    if type(value) is not int or value <= 0:
        raise ValueError("Invalid Tcl UTC milliseconds")
    event_ns = value * 1_000_000
    if not anchors[0]["utc_ns"] - guard_ns <= event_ns <= anchors[-1]["utc_ns"] + guard_ns:
        raise ValueError("Tcl event is outside the anchored host interval")
    index, anchor = min(enumerate(anchors), key=lambda item: abs(item[1]["utc_ns"] - event_ns))
    delta = event_ns - anchor["utc_ns"]
    if abs(delta) > maximum_anchor_distance_ns:
        raise ValueError("No host clock anchor within 5 seconds of Tcl event")
    # Integer floor/ceiling preserve outward rounding even for negative offsets.
    low_offset = delta * frequency // 1_000_000_000
    high_offset = -((-delta * frequency) // 1_000_000_000)
    guard_ticks = -((-(guard_ns + utc_resolution_ns) * frequency) // 1_000_000_000)
    return (anchor["qpc_before"] + low_offset - guard_ticks,
            anchor["qpc_after"] + high_offset + guard_ticks, index)


def build_trials(events, anchors, frequency, epochs, blocks, utc_resolution_ns=1):
    check_anchors(anchors, frequency, utc_resolution_ns=utc_resolution_ns)
    if any(row.get("event") == "campaign_error" for row in events):
        raise ValueError("JTAG recorded a campaign error")
    completed = [row for row in events if row.get("event") == "campaign_complete"]
    if len(completed) != 1 or completed[0].get("completed") is not True:
        raise ValueError("Missing or duplicate successful campaign completion")
    if integer(completed[0], "measured_trials") != blocks * 4 or integer(completed[0], "epochs_per_trial") != epochs:
        raise ValueError("Campaign completion count/configuration mismatch")
    if not events or events[-1] is not completed[0]:
        raise ValueError("Campaign completion is not the final JTAG event")
    measured = [row for row in events if row.get("event") == "trial_complete" and
                str(row.get("trial_id", "")).startswith("trial_")]
    expected_ids = [f"trial_{i:03d}" for i in range(1, blocks * 4 + 1)]
    if [row.get("trial_id") for row in measured] != expected_ids:
        raise ValueError("Measured trials are missing, duplicate, unknown or out of order")
    trials = []
    for index, event in enumerate(measured):
        condition = ("masked_baseline", "masked_isolated", "masked_isolated", "masked_baseline")[index % 4]
        mode = 2 if condition == "masked_baseline" else 3
        threshold = 100_000_000_000
        if event.get("condition") != condition or integer(event, "threshold2") != threshold:
            raise ValueError("Trial condition/threshold does not match the ABBA plan")
        if integer(event, "pair_id", 1) != index // 2 + 1:
            raise ValueError("Incorrect paired-trial identity")
        if event.get("completed") is not True:
            raise ValueError("Trial did not complete")
        for key, wanted in (("epochs", epochs), ("outputs", epochs * 1536),
                            ("useful_inputs", epochs * 1024), ("frames", epochs * 9),
                            ("mismatch_count", 0), ("fault_flags", 0), ("last_epoch_outputs", 1536)):
            if integer(event, key) != wanted:
                raise ValueError("Unexpected trial " + key)
        cycles = integer(event, "cycles", 1)
        if cycles > (epochs + 1) * 1_000_000:
            raise ValueError("Elapsed cycles exceed the finite watchdog allocation")
        raw = event.get("probe_hex", "")
        if not isinstance(raw, str) or not re.fullmatch(r"[0-9a-fA-F]{120}", raw):
            raise ValueError("Missing exact 480-bit terminal probe")
        words = [(int(raw, 16) >> (32 * i)) & 0xffffffff for i in range(15)]
        status = words[1]
        if words[0] != 0x54524350 or status >> 24 != 2 or status & 0x44d or status & 0x82 != 0x82:
            raise ValueError("Terminal probe is busy, faulty, pending or has wrong protocol")
        if status & 0x30 != 0x20 or bool(status & 0x800) != (mode == 3):
            raise ValueError("Terminal probe mode flags disagree")
        if words[2] & 0xffff0003 != (epochs << 16) | mode:
            raise ValueError("Terminal probe command disagrees")
        expected_words = {3: epochs, 4: epochs*1536, 5: 0, 6: epochs*1024,
                          7: epochs*9, 10: 0xffffffff, 11: 0, 12: 1536}
        if any(words[i] != wanted for i, wanted in expected_words.items()) or (words[9] << 32 | words[8]) != cycles:
            raise ValueError("Terminal probe counters disagree with trial event")
        if words[13] != integer(event, "last_epoch_cycles", 1) or words[14] != integer(event, "rolling_checksum"):
            raise ValueError("Terminal probe last-epoch/checksum fields disagree")
        trial = {"trial_id": event["trial_id"], "pair_id": event["pair_id"],
                 "condition": condition, "threshold2": threshold, "cycles": cycles,
                 "clock_hz": 50_000_000, "epochs": epochs, "inputs_per_epoch": 1024,
                 "outputs_per_epoch": 1536, "frames_per_epoch": 9,
                 "input_count": event["useful_inputs"], "output_count": event["outputs"],
                 "frame_count": event["frames"], "mismatch_count": 0, "fault_flags": 0,
                 "completed": True, "source_event": event, "anchor_indices": {}}
        for key in ("launch_before", "launch_after", "completion_before", "completion_after"):
            bounds = utc_ms_bounds(integer(event, key + "_ms", 1), anchors, frequency,
                                   utc_resolution_ns=utc_resolution_ns)
            trial[key + "_qpc"] = bounds[0] if key.endswith("before") else bounds[1]
            trial["anchor_indices"][key] = bounds[2]
        if event["launch_before_ms"] > event["launch_after_ms"] or event["completion_before_ms"] > event["completion_after_ms"]:
            raise ValueError("Reversed source JTAG timestamp bracket")
        if event["completion_after_ms"] < event["launch_after_ms"]:
            raise ValueError("Completion precedes launch")
        if index and event["launch_before_ms"] < measured[index-1]["completion_after_ms"]:
            raise ValueError("Sequential trials overlap in source timestamps")
        trials.append(trial)
    if integer(completed[0], "utc_ms", 1) < measured[-1]["completion_after_ms"]:
        raise ValueError("Campaign completion precedes the last trial")
    if len({trial["cycles"] for trial in trials}) != 1:
        raise ValueError("Isolation experiment changed cycle count across conditions")
    return {"schema": "trecap_measured_trials_v1", "qpc_frequency": frequency,
            "scope": "Same-image finite core computation, not HPS/DDR end-to-end runtime",
            "clock_mapping": {"method": "nearest bracketed UTC/raw-QPC anchor",
                "tcl_timestamp_guard_ms": 20, "utc_step_rejection_ms": 10,
                "python_time_resolution_ns": utc_resolution_ns, "maximum_anchor_distance_s": 5,
                "assumptions": ["Windows Tcl millisecond timestamps lie within +/-20 ms of physical host time",
                    "No undetected UTC jump-and-return between one-second anchor samples",
                    "QPC is the same raw global clock used by .NET Stopwatch in meter capture",
                    "These bounds exclude sensor calibration and oscillator tolerance"]}, "trials": trials}


def under(path, directory):
    path = Path(path).resolve()
    try:
        path.relative_to(directory.resolve())
    except ValueError:
        raise ValueError("Capture result path is outside this run: " + str(path)) from None
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Missing or empty capture artifact: " + str(path))
    return path


def validate_capture(summary, directory, frequency):
    if summary.get("ok") is not True or summary.get("error") is not None:
        raise ValueError("Meter capture did not report clean completion")
    if summary.get("stopped_by_file") is not True:
        raise ValueError("Meter did not acknowledge the requested clean StopFile shutdown")
    if integer(summary, "qpc_frequency", 1) != frequency:
        raise ValueError("Raw QPC frequency differs from meter Stopwatch frequency")
    if integer(summary, "rows", 1) < 3 or integer(summary, "sync_replies", 2) < 2:
        raise ValueError("Insufficient meter rows/clock exchanges")
    if integer(summary, "capture_end_qpc") <= integer(summary, "capture_start_qpc"):
        raise ValueError("Invalid meter capture time interval")
    sessions = summary.get("sessions")
    if not isinstance(sessions, list) or len(sessions) != 1:
        raise ValueError("Campaign requires one continuous meter CSV session")
    if integer(sessions[0], "rows", 1) != summary["rows"]:
        raise ValueError("Session rows differ from capture total")
    paths = {key: under(summary[key], directory) for key in
             ("raw_log", "metadata_jsonl", "host_receipts_jsonl", "sync_jsonl")}
    paths["csv"] = under(sessions[0]["csv"], directory)
    replies = [r for r in jsonl(paths["sync_jsonl"]) if r.get("event") == "sync_reply"]
    if len(replies) != summary["sync_replies"] or len({r["device_session"] for r in replies}) != 1:
        raise ValueError("Meter sync replies span sessions or disagree with summary")
    for row in replies:
        if (integer(row, "qpc_frequency", 1) != frequency or
                not integer(row, "send_before_qpc") <= integer(row, "send_after_qpc") <= integer(row, "receive_qpc")):
            raise ValueError("Invalid meter synchronization bracket")
    return paths, replies[0]["device_session"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--quartus-root", type=Path, required=True)
    parser.add_argument("--hardware", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--port", default="COM7")
    parser.add_argument("--epochs", type=int, default=16384)
    parser.add_argument("--blocks", type=int, default=3)
    parser.add_argument("--idle-ms", type=int, default=2000)
    parser.add_argument("--timeout-ms", type=int, default=120000)
    parser.add_argument("--capture-seconds", type=int, default=600)
    parser.add_argument("--powershell", default=shutil.which("pwsh") or shutil.which("powershell"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--program-manifest", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.epochs <= 65535 or not 1 <= args.blocks <= 16 or not 0 <= args.idle_ms <= 60000 or not 1000 <= args.timeout_ms <= 600000:
        parser.error("Epoch/block/idle/timeout arguments exceed finite JTAG limits")
    if not 60 <= args.capture_seconds <= 86400 or not re.fullmatch(r"COM[1-9][0-9]*", args.port, re.I):
        parser.error("Invalid capture duration or COM port")
    repo = args.repo.resolve()
    run = args.run_dir.resolve()
    if run.exists():
        parser.error("Run directory already exists; choose a new immutable evidence directory")
    capture_script = repo / "sw/measurement/ina228/capture_sync.ps1"
    jtag_script = repo / "platform/de1soc/measurement/jtag_zero_control.tcl"
    analyzer = repo / "scripts/measurement/analyze_board_measurement.py"
    candidates = [args.quartus_root / "bin64/quartus_stp.exe",
                  args.quartus_root / "quartus/bin64/quartus_stp.exe",
                  args.quartus_root / "quartusfpga/quartus/bin64/quartus_stp.exe"]
    stp = next((p.resolve() for p in candidates if p.is_file()), None)
    if stp is None or not args.powershell:
        parser.error("Quartus STP or PowerShell executable is unavailable")
    powershell_path = Path(shutil.which(args.powershell) or args.powershell).resolve()
    if not powershell_path.is_file():
        parser.error("PowerShell executable is unavailable: " + str(powershell_path))
    required = [capture_script, jtag_script, analyzer,
                repo / "sw/measurement/ina228/device_code_sync.py",
                repo / "platform/de1soc/measurement/trecap_measurement_engine.sv",
                repo / "platform/de1soc/measurement/trecap_measurement_top.sv",
                repo / "artifacts/measurement/multitone/manifest.json",
                repo / "artifacts/measurement/multitone/y_dense.memh",
                repo / "artifacts/measurement/multitone/y_masked.memh",
                repo / "artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh"]
    if args.program_manifest:
        required.append(args.program_manifest.resolve())
    for path in required:
        if not path.is_file() or not path.stat().st_size:
            parser.error("Required source/evidence file is absent or empty: " + str(path))
    if not re.search(r"\$StopFile\b", capture_script.read_text(encoding="utf-8-sig")):
        parser.error("Capture script lacks the required StopFile clean-shutdown contract")
    # A planning estimate catches obviously overlong CLI configurations. Actual
    # capture/process exit is still monitored; this is not a timing guarantee.
    estimated_seconds = (4 * args.blocks * args.epochs + 8195) * 110000 / 50_000_000 + 40 + args.blocks * 4 * args.idle_ms / 1000 + 65
    if estimated_seconds >= args.capture_seconds:
        parser.error("Requested campaign is too long for capture duration with startup/padding allowance")
    qpc = WindowsQPC()
    utc_resolution = max(1, math.ceil(time.get_clock_info("time").resolution * 1e9))
    run.mkdir(parents=True, exist_ok=False)
    meter_dir = run / "meter"
    meter_dir.mkdir()
    stop_file = run / "capture.stop"
    manifest_path = run / "campaign_manifest.json"
    sources = {str(p): digest(p) for p in required + [Path(__file__).resolve()]}
    manifest = {"schema": "trecap_zero_isolation_campaign_v1", "status": "starting", "repo": str(repo),
                "run": str(run), "started_utc_ns": time.time_ns(), "qpc_frequency": qpc.frequency,
                "python_time_clock": vars(time.get_clock_info("time")), "sources_sha256": sources,
                "program_manifest_provided": args.program_manifest is not None,
                "requested": vars(args).copy(), "commands": [], "phases": [],
                "scope": "Already-programmed image; finite JTAG control plus serial meter capture; no FPGA programming"}
    manifest["requested"] = {k: str(v) if isinstance(v, Path) else v for k, v in manifest["requested"].items()}
    anchors = []
    children = []
    handles = []
    anchor_file = (run / "host_clock_anchors.jsonl").open("x", encoding="utf-8", buffering=1)
    capture_process = jtag_process = None
    last_anchor = last_progress = 0

    def save():
        manifest["updated_utc_ns"] = time.time_ns()
        write_json(manifest_path, manifest)

    def phase(name):
        manifest["phases"].append({"phase": name, "utc_ns": time.time_ns(), "qpc": qpc.read()})
        print(name, flush=True)
        save()

    def anchor():
        nonlocal last_anchor
        before = qpc.read()
        utc = time.time_ns()
        after = qpc.read()
        item = {"index": len(anchors), "qpc_before": before, "utc_ns": utc,
                "qpc_after": after, "qpc_frequency": qpc.frequency}
        anchors.append(item)
        anchor_file.write(json.dumps(item) + "\n")
        last_anchor = after
        if len(anchors) > 1:
            check_anchors(anchors[-2:], qpc.frequency, utc_resolution_ns=utc_resolution)

    def tick(label):
        nonlocal last_progress
        now = qpc.read()
        if now - last_anchor >= qpc.frequency:
            anchor()
        if now - last_progress >= 30 * qpc.frequency:
            print(label + "; elapsed %.1f s" % ((now - anchors[0]["qpc_before"]) / qpc.frequency), flush=True)
            last_progress = now
        time.sleep(.2)

    def start(name, command):
        stdout = (run / (name + ".stdout.log")).open("xb")
        stderr = (run / (name + ".stderr.log")).open("xb")
        handles.extend([stdout, stderr])
        record = {"name": name, "argv": command, "cwd": str(repo),
                  "executable_sha256": digest(Path(command[0])), "before_qpc": qpc.read()}
        manifest["commands"].append(record)
        save()
        process = subprocess.Popen(command, cwd=repo, stdin=subprocess.DEVNULL, stdout=stdout,
                                   stderr=stderr, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        record.update(pid=process.pid, after_qpc=qpc.read())
        children.append((name, process, record))
        save()
        return process

    def request_stop():
        if not stop_file.exists():
            with stop_file.open("x", encoding="ascii") as stream:
                stream.write("Host requests clean serial capture completion.\n")

    try:
        anchor()
        last_progress = qpc.read()
        phase("Starting meter capture")
        capture_process = start("capture", [str(powershell_path), "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(capture_script), "-Port", args.port.upper(),
            "-OutputDirectory", str(meter_dir), "-Seconds", str(args.capture_seconds), "-Restart", "-StopFile", str(stop_file)])
        ready_deadline = qpc.read() + 60 * qpc.frequency
        while True:
            if capture_process.poll() is not None:
                raise RuntimeError("Meter capture exited before synchronization readiness")
            receipts = list(meter_dir.glob("*.host_receipts.jsonl"))
            syncs = list(meter_dir.glob("*.sync.jsonl"))
            if len(receipts) > 1 or len(syncs) > 1:
                raise ValueError("Multiple fresh capture roots appeared")
            if receipts and syncs:
                samples = [r for r in jsonl(receipts[0], partial=True) if r.get("event") == "sample_received"]
                replies = [r for r in jsonl(syncs[0], partial=True) if r.get("event") == "sync_reply"]
                if samples and len(replies) >= 2:
                    for row in [samples[-1], *replies]:
                        if integer(row, "qpc_frequency", 1) != qpc.frequency or integer(row, "receive_qpc") < anchors[0]["qpc_before"]:
                            raise ValueError("Capture files have stale or incompatible clock records")
                    if len({r["device_session"] for r in [samples[-1], *replies]}) != 1:
                        raise ValueError("Meter restarted during capture readiness")
                    break
            if qpc.read() >= ready_deadline:
                raise TimeoutError("No fresh sample receipt and two clock replies within 60 seconds")
            tick("Waiting for meter clock synchronization")
        manifest["ready_meter_files"] = {"receipts": str(receipts[0]), "sync": str(syncs[0])}
        phase("Meter ready; starting finite FPGA campaign")
        jtag_process = start("jtag", [str(stp), "-t", jtag_script.as_posix(), "campaign", args.hardware, args.device,
            (run / "jtag.jsonl").as_posix(), str(args.epochs), str(args.blocks), str(args.idle_ms), str(args.timeout_ms)])
        deadline = anchors[0]["qpc_before"] + (args.capture_seconds + 30) * qpc.frequency
        while jtag_process.poll() is None:
            if capture_process.poll() is not None:
                raise RuntimeError("Meter ended while FPGA campaign was active")
            if qpc.read() >= deadline:
                raise TimeoutError("Campaign exceeded its bounded host capture window")
            tick("Capturing FPGA trials and meter data")
        if jtag_process.returncode != 0:
            raise RuntimeError("Quartus STP campaign returned " + str(jtag_process.returncode))
        phase("FPGA campaign exited; collecting five seconds of meter padding")
        padding_end = qpc.read() + 5 * qpc.frequency
        while qpc.read() < padding_end:
            if capture_process.poll() is not None:
                raise RuntimeError("Meter ended before final padding")
            tick("Collecting final meter padding")
        request_stop()
        phase("Requested clean meter shutdown")
        stop_deadline = qpc.read() + 30 * qpc.frequency
        while capture_process.poll() is None:
            if qpc.read() > stop_deadline:
                raise TimeoutError("Meter did not honor StopFile within 30 seconds")
            tick("Waiting for meter summary")
        anchor()
        if capture_process.returncode != 0:
            raise RuntimeError("Meter capture returned " + str(capture_process.returncode))
        # Strictly parse the complete stdout object; banners or extra JSON reject.
        summary = strict_json((run / "capture.stdout.log").read_text(encoding="utf-8-sig"))
        paths, device_session = validate_capture(summary, meter_dir, qpc.frequency)
        if Path(summary["stop_file"]).resolve() != stop_file:
            raise ValueError("Meter acknowledged a different StopFile path")
        write_json(run / "capture.summary.json", summary)
        trials = build_trials(jsonl(run / "jtag.jsonl"), anchors, qpc.frequency, args.epochs, args.blocks, utc_resolution)
        trials["host_clock_anchors_sha256"] = digest(run / "host_clock_anchors.jsonl")
        trials["source_jtag_sha256"] = digest(run / "jtag.jsonl")
        write_json(run / "trials.json", trials)
        changed = [p for p, expected in sources.items() if digest(p) != expected]
        if changed:
            raise RuntimeError("Campaign source/artifact changed during acquisition: " + repr(changed))
        manifest["analysis_argv"] = [args.python, str(analyzer), "--csv", str(paths["csv"]),
            "--sync", str(paths["sync_jsonl"]), "--trials", str(run / "trials.json"),
            "--session", str(device_session), "--out", str(run / "analysis"),
            "--baseline", "masked_baseline", "--candidate", "masked_isolated"]
        manifest["outputs_sha256"] = {str(p): digest(p) for p in
            [run / "capture.summary.json", run / "trials.json", run / "jtag.jsonl", run / "host_clock_anchors.jsonl", *paths.values()]}
        manifest["status"] = "PASS_CAPTURE_AND_TRIAL_ADMISSION"
        manifest["trial_count"] = len(trials["trials"])
        manifest["analysis_executed"] = False
        phase("Captured and admitted all finite trials; energy analysis remains separate")
    except BaseException as exc:
        manifest["status"] = "FAILED"
        manifest["error"] = type(exc).__name__ + ": " + str(exc)
        manifest["hardware_note"] = "Host failure does not cancel an already launched finite FPGA batch; it may complete naturally. No new FPGA command is sent during cleanup."
        print("FAILED: " + manifest["error"], file=sys.stderr, flush=True)
    finally:
        # Cleanup may fail independently (for example an externally killed
        # process). Preserve the primary failure and still close other handles.
        for name, process in (("jtag", jtag_process), ("capture", capture_process)):
            if process is None or process.poll() is not None:
                continue
            try:
                if name == "capture":
                    request_stop()
                    try:
                        process.wait(timeout=30)
                        continue
                    except subprocess.TimeoutExpired:
                        manifest["capture_forced_termination"] = True
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            except Exception as cleanup_error:
                manifest.setdefault("cleanup_errors", []).append(name + ": " + repr(cleanup_error))
                manifest["status"] = "FAILED"
        for _, process, record in children:
            record["exit_code"] = process.poll()
        for handle in handles:
            handle.close()
        anchor_file.close()
        manifest["finished_utc_ns"] = time.time_ns()
        save()
    return 0 if manifest["status"] == "PASS_CAPTURE_AND_TRIAL_ADMISSION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
