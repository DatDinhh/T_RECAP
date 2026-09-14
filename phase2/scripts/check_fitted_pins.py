#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compare a completed Quartus .pin report with the DE1-SoC source contracts.

Reads artifacts and source files only; writes the explicitly requested JSON report.
This establishes package-pin and I/O-standard agreement, not timing, OCT calibration,
board revision, programming availability, or live peripheral operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Quartus reports these dedicated package functions even though they are not
# programmable board-top ports. Preserve their rows for review, without counting
# them as checked peripheral signals or accepting arbitrary extra HPS ports.
DEDICATED_HPS_FUNCTIONS = {
    "HPS_CLK1", "HPS_CLK2", "HPS_PORSEL", "HPS_TCK", "HPS_TDI", "HPS_TDO",
    "HPS_TMS", "HPS_TRST", "HPS_nPOR", "HPS_nRST",
}


def file_info(path: Path, root: Path) -> dict[str, str]:
    try:
        name = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        name = path.resolve().as_posix()
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def add_unique(values: dict[str, Any], name: str, value: Any) -> None:
    if name in values:
        raise ValueError(f"Duplicate source assignment for {name}")
    values[name] = value


def expected_pins(root: Path) -> tuple[dict[str, dict[str, Any]], list[Path], str]:
    ledger_path = root / "config/boards/de1soc_hps_ddr_pins.json"
    fpga_path = root / "constraints/de1soc/pin_assignments.tcl"
    hps_path = root / "constraints/de1soc/hps_peripheral_io.tcl"
    qsf_path = root / "constraints/de1soc/de1soc.qsf"
    top_path = root / "rtl/platform/de1soc/de1_soc_trecap_top.sv"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    pins = ledger["pins"]
    if ledger.get("expected_pin_count") != 72 or len(pins) != 72:
        raise ValueError("DDR ledger must contain exactly 72 signal locations")
    expected: dict[str, dict[str, Any]] = {}
    for signal, pin in pins.items():
        if not re.fullmatch(r"HPS_DDR3_\w+(?:\[\d+\])?", signal):
            raise ValueError(f"Invalid DDR signal in ledger: {signal}")
        if not re.fullmatch(r"PIN_[A-Z]+\d+", pin):
            raise ValueError(f"Invalid package pin in ledger: {pin}")
        differential = bool(re.fullmatch(r"HPS_DDR3_(?:CK_[NP]|DQS_[NP]\[\d+\])", signal))
        standard = "Differential 1.5-V SSTL Class I" if differential else "SSTL-15 Class I"
        add_unique(expected, signal, {"group": "hps_ddr", "location": pin, "io_standard": standard})

    hps_count = 0
    for line in hps_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r'set_instance_assignment -name IO_STANDARD "([^"]+)" -to \{([^{}]+)\}', line.strip())
        if not match or match[1] != "3.3-V LVTTL" or not match[2].startswith("HPS_"):
            raise ValueError(f"Unsupported HPS I/O assignment syntax: {line}")
        add_unique(expected, match[2], {"group": "hps_peripheral", "io_standard": match[1]})
        hps_count += 1
    if hps_count != 55:
        raise ValueError(f"Expected 55 explicit HPS peripheral standards, found {hps_count}")

    fpga_count = 0
    for line in fpga_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("trecap_pin "):
            continue
        match = re.fullmatch(r'trecap_pin\s+(PIN_[A-Z]+\d+)\s+(?:\{([^{}]+)\}|([A-Za-z0-9_]+))(?:\s+"([^"]+)")?\s*', line)
        if not match:
            raise ValueError(f"Unsupported FPGA pin assignment syntax: {line}")
        signal = match[2] or match[3]
        add_unique(expected, signal, {"group": "fpga", "location": match[1], "io_standard": match[4] or "3.3-V LVTTL"})
        fpga_count += 1
    if not fpga_count:
        raise ValueError("No explicit FPGA pin assignments found")
    locations = [entry["location"] for entry in expected.values() if "location" in entry]
    if len(set(locations)) != len(locations):
        raise ValueError("Source contracts assign multiple signals to one package pin")

    top = top_path.read_text(encoding="utf-8").split("\n);", 1)[0]
    ports: set[str] = set()
    for msb, lsb, signal in re.findall(r"^\s*(?:input|output|inout)\s+(?:logic|wire)\s+(?:\[(\d+):(\d+)\]\s*)?(\w+)\s*,?\s*$", top, re.M):
        if msb:
            ports.update(f"{signal}[{index}]" for index in range(int(lsb), int(msb) + 1))
        else:
            ports.add(signal)
    if ports != set(expected):
        raise ValueError(f"Top-level pin coverage differs: missing={sorted(ports-set(expected))}, extra={sorted(set(expected)-ports)}")
    devices = re.findall(r"^set_global_assignment -name DEVICE\s+(\S+)\s*$", qsf_path.read_text(encoding="utf-8"), re.M)
    if len(devices) != 1:
        raise ValueError("Expected exactly one source-owned Quartus DEVICE assignment")
    return expected, [ledger_path, fpga_path, hps_path, qsf_path, top_path], devices[0]


def fitted_rows(path: Path) -> tuple[dict[str, list[dict[str, Any]]], str, str]:
    rows: dict[str, list[dict[str, Any]]] = {}
    device = ""
    version = ""
    in_table = False
    seen_locations: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.startswith("Quartus Prime Version "):
            version = line.strip()
        match = re.fullmatch(r'CHIP\s+"[^"]+"\s+ASSIGNED TO AN:\s+(\S+)\s*', line)
        if match:
            device = match[1]
        if line.startswith("Pin Name/Usage"):
            if in_table:
                raise ValueError("Multiple pin tables in report")
            columns = [part.strip() for part in line.split(":")]
            if columns != ["Pin Name/Usage", "Location", "Dir.", "I/O Standard", "Voltage", "I/O Bank", "User Assignment"]:
                raise ValueError(f"Unsupported Quartus pin-table header: {line}")
            in_table = True
            continue
        if not in_table or not line.strip() or set(line.strip()) == {"-"}:
            continue
        fields = [part.strip() for part in line.split(":")]
        if len(fields) != 7 or not re.fullmatch(r"[A-Z]+\d+", fields[1]):
            raise ValueError(f"Malformed fitted-pin row at line {number}: {line}")
        signal, location, direction, standard, voltage, bank, assigned = fields
        if location in seen_locations:
            raise ValueError(f"Duplicate fitted package location {location}")
        seen_locations.add(location)
        rows.setdefault(signal, []).append({"location": f"PIN_{location}", "direction": direction, "io_standard": standard, "voltage": voltage, "io_bank": bank, "user_assignment": assigned, "line": number})
    if not in_table or not rows or not device or not version:
        raise ValueError("Incomplete Quartus .pin report: table, device, or version is missing")
    return rows, device, version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin-file", "--pin", required=True, type=Path, help="Existing completed Quartus .pin report")
    parser.add_argument("--report", required=True, type=Path, help="JSON result file to write")
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="Repository containing source pin contracts")
    args = parser.parse_args()
    report: dict[str, Any] = {"schema_version": 1, "status": "FAIL", "scope": "Fitted package locations and I/O standards only", "failures": [], "pins": []}
    try:
        expected, sources, expected_device = expected_pins(args.repo_root)
        protected = [args.pin_file, *sources, Path(__file__)]
        if args.report.resolve() in {path.resolve() for path in protected}:
            raise ValueError("Report path must not overwrite an input or checker source")
        actual, device, version = fitted_rows(args.pin_file)
        report.update({"artifact": file_info(args.pin_file, args.repo_root), "sources": [file_info(path, args.repo_root) for path in sources], "quartus_version": version, "device": device, "expected_device": expected_device})
        if device != expected_device:
            report["failures"].append(f"Device mismatch: expected {expected_device}, found {device}")
        groups: dict[str, dict[str, int]] = {}
        for signal, entry in expected.items():
            group = groups.setdefault(entry["group"], {"expected": 0, "passed": 0, "failed": 0})
            group["expected"] += 1
            found = actual.get(signal, [])
            errors = []
            if len(found) != 1:
                errors.append(f"Expected exactly one fitted row, found {len(found)}")
            else:
                if "location" in entry and found[0]["location"] != entry["location"]:
                    errors.append(f"Location mismatch: {found[0]['location']} != {entry['location']}")
                if found[0]["io_standard"].casefold() != entry["io_standard"].casefold():
                    errors.append(f"I/O standard mismatch: {found[0]['io_standard']} != {entry['io_standard']}")
            status = "FAIL" if errors else "PASS"
            group["failed" if errors else "passed"] += 1
            report["pins"].append({"signal": signal, "status": status, "expected": entry, "actual": found, "failures": errors})
            report["failures"].extend(f"{signal}: {error}" for error in errors)
        report["dedicated_hps_functions_not_compared"] = {
            signal: actual[signal] for signal in sorted(DEDICATED_HPS_FUNCTIONS) if signal in actual
        }
        unexpected_hps = sorted(
            signal for signal in actual
            if signal.startswith("HPS_") and signal not in expected and signal not in DEDICATED_HPS_FUNCTIONS
        )
        if unexpected_hps:
            report["failures"].append(f"Unexpected fitted HPS signals: {unexpected_hps}")
        report["groups"] = groups
        report["checked_pin_count"] = len(expected)
        report["status"] = "FAIL" if report["failures"] else "PASS"
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["failures"].append(str(error))
    # Do not let an input error bypass the report-overwrite guard.
    protected_paths = [args.pin_file.resolve(), Path(__file__).resolve()]
    if args.report.resolve() in protected_paths or args.report.resolve().is_relative_to(args.repo_root.resolve() / "config") or args.report.resolve().is_relative_to(args.repo_root.resolve() / "constraints") or args.report.resolve().is_relative_to(args.repo_root.resolve() / "rtl"):
        print("check_fitted_pins: ERROR: report must not replace a source/input file", file=sys.stderr)
        return 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"check_fitted_pins: {report['status']} ({report.get('checked_pin_count', 0)} pins); report={args.report}")
    for error in report["failures"]:
        print(f"ERROR: {error}", file=sys.stderr)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
