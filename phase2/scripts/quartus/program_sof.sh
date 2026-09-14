#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 DE1-SoC SOF programming helper.
# File class: [1] hand-written repository infrastructure.
#
# Programs a selected .sof through Quartus Programmer and records a run manifest.
# This script refuses legacy paths and does not infer correctness from a live
# board image; BRAM replay remains the correctness signoff path.

set -euo pipefail
IFS=$'\n\t'

usage() {
  cat <<'USAGE'
Usage: scripts/quartus/program_sof.sh [options]

Options:
  --sof PATH          Explicit nonempty SOF file to program (required).
  --build-manifest PATH
                      Completed build manifest matching this fresh SOF and its
                      passed fitted-pin/timing reports (required).
  --cable NAME        Exact selected Quartus cable name (required).
  --device-index N    FPGA device index; only 2 is accepted (default: 2).
  --mode MODE         Programming mode; only JTAG is accepted.
  --operation OP      Operation prefix; only volatile p is accepted.
  --run-dir PATH      Programming run directory. Default: runs/quartus/program/<timestamp>
  --list-cables       Run jtagconfig before programming.
  --dry-run           Print commands without programming.
  -h, --help          Show this help.

Environment overrides:
  QUARTUS_PGM         Quartus programmer executable. Default: quartus_pgm
  JTAGCONFIG          JTAG cable listing executable. Default: jtagconfig
  PYTHON              Python executable. Default: python3
USAGE
}

QUARTUS_PGM_BIN="${QUARTUS_PGM:-quartus_pgm}"
JTAGCONFIG_BIN="${JTAGCONFIG:-jtagconfig}"
PYTHON_BIN="${PYTHON:-python3}"
SOF=""
BUILD_MANIFEST=""
CABLE=""
DEVICE_INDEX="2"
MODE="JTAG"
OPERATION="p"
RUN_DIR=""
LIST_CABLES=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sof) SOF="${2:?missing value for --sof}"; shift ;;
    --build-manifest) BUILD_MANIFEST="${2:?missing value for --build-manifest}"; shift ;;
    --cable) CABLE="${2:?missing value for --cable}"; shift ;;
    --device-index) DEVICE_INDEX="${2:?missing value for --device-index}"; shift ;;
    --mode) MODE="${2:?missing value for --mode}"; shift ;;
    --operation) OPERATION="${2:?missing value for --operation}"; shift ;;
    --run-dir) RUN_DIR="${2:?missing value for --run-dir}"; shift ;;
    --list-cables) LIST_CABLES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [[ ! -f Makefile || ! -d runs || ! -d platform/de1soc ]]; then
  echo "ERROR: ${repo_root} does not look like the T_RECAP_Phase2 repository root" >&2
  exit 2
fi

if [[ -z "${RUN_DIR}" ]]; then
  RUN_DIR="runs/quartus/program/$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "${RUN_DIR}"
log_file="${RUN_DIR}/program.log"
manifest_file="${RUN_DIR}/program_manifest.json"

say_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
}

run_cmd() {
  say_cmd "$@" | tee -a "${log_file}"
  if [[ ${DRY_RUN} -eq 0 ]]; then
    "$@" 2>&1 | tee -a "${log_file}"
  fi
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ -n "${SOF}" ]] || fail "--sof is required; no image is selected automatically"
[[ -n "${BUILD_MANIFEST}" ]] || fail "--build-manifest is required"
[[ -n "${CABLE}" ]] || fail "--cable is required"
[[ "${DEVICE_INDEX}" == 2 ]] || fail "DE1-SoC volatile FPGA programming requires device index 2"
[[ -s "${SOF}" ]] || fail "SOF file is missing or empty: ${SOF}"
[[ "${SOF,,}" == *.sof ]] || fail "--sof must name a .sof image"
[[ "${MODE}" == JTAG && "${OPERATION}" == p ]] || fail "only volatile JTAG programming (mode JTAG, operation p) is supported"
case "${SOF}" in
  *';'*|*'@'*|*$'\n'*|*$'\r'*) fail "SOF path contains a reserved programming delimiter" ;;
  legacy/*|*/legacy/*) fail "refusing to program SOF from legacy path: ${SOF}" ;;
esac

# This read-only provenance check runs before cable inventory or programming.
# Collected artifacts and images left by unsuccessful builds are not eligible.
"${PYTHON_BIN}" - "${SOF}" "${BUILD_MANIFEST}" "${RUN_DIR}/build_provenance.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

try:
    image, manifest_path, result_path = (Path(value).resolve() for value in sys.argv[1:])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["status"] != "completed" or manifest["assembler_image"]["status"] != "present" or manifest["assembler_image"]["fresh"] is not True:
        raise ValueError("Manifest must describe a completed build with a fresh nonempty SOF")
    image_hash = sha256(image)
    if image.stat().st_size == 0 or image_hash != manifest["sof"]["sha256"] or image.stat().st_size != manifest["sof"]["size_bytes"]:
        raise ValueError("Selected SOF does not match the completed build manifest")
    for name in ("fitted_pins", "fitted_timing"):
        gate = manifest[name]
        report = Path(gate["report"])
        if gate["status"] != "passed" or sha256(report) != gate["sha256"]:
            raise ValueError(f"Build gate failed or its report changed: {name}")
    pins = json.loads(Path(manifest["fitted_pins"]["report"]).read_text(encoding="utf-8"))
    if pins["status"] != "PASS" or pins["checked_pin_count"] != 209:
        raise ValueError("Fitted-pin report does not establish the 209-signal board contract")
    timing = [line.split("\t") for line in Path(manifest["fitted_timing"]["report"]).read_text(encoding="utf-8").splitlines()]
    if sum(row[:4] == ["all", "gate", "completed", "PASS"] for row in timing) != 1 or any(len(row) >= 4 and row[3] == "FAIL" for row in timing):
        raise ValueError("Fitted timing report lacks a unique successful completion or contains failures")
    provenance = {"build_manifest": str(manifest_path), "build_manifest_sha256": sha256(manifest_path),
                  "sof": str(image), "sof_sha256": image_hash,
                  "fitted_pins_sha256": manifest["fitted_pins"]["sha256"],
                  "fitted_timing_sha256": manifest["fitted_timing"]["sha256"]}
    result_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
except (OSError, ValueError, KeyError, TypeError) as error:
    raise SystemExit(f"Programming provenance rejected: {error}")
PY

if [[ ${LIST_CABLES} -eq 1 ]]; then
  if command -v "${JTAGCONFIG_BIN}" >/dev/null 2>&1; then
    run_cmd "${JTAGCONFIG_BIN}"
  elif [[ ${DRY_RUN} -eq 1 ]]; then
    say_cmd "${JTAGCONFIG_BIN}" | tee -a "${log_file}"
  else
    fail "${JTAGCONFIG_BIN} not found in PATH"
  fi
fi

if [[ ${DRY_RUN} -eq 0 ]] && ! command -v "${QUARTUS_PGM_BIN}" >/dev/null 2>&1; then
  fail "${QUARTUS_PGM_BIN} not found in PATH. Set QUARTUS_PGM or source Intel FPGA environment."
fi

operation_arg="${OPERATION};${SOF}"
if [[ -n "${DEVICE_INDEX}" ]]; then
  operation_arg="${operation_arg}@${DEVICE_INDEX}"
fi

cmd=("${QUARTUS_PGM_BIN}" -m "${MODE}")
if [[ -n "${CABLE}" ]]; then
  cmd+=(-c "${CABLE}")
fi
cmd+=(-o "${operation_arg}")

{
  echo "program_sof: repository root ${repo_root}"
  echo "program_sof: sof ${SOF}"
  echo "program_sof: run_dir ${RUN_DIR}"
} | tee -a "${log_file}"

# Inventory can take time; recheck the selected bytes immediately before use.
"${PYTHON_BIN}" - "${SOF}" "${RUN_DIR}/build_provenance.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
expected = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["sof_sha256"]
if hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest() != expected:
    raise SystemExit("SOF changed after provenance check; no programming command was issued")
PY
run_cmd "${cmd[@]}"

if [[ ${DRY_RUN} -eq 0 ]]; then
  export TRECAP_PROGRAM_RUN_DIR="${RUN_DIR}"
  export TRECAP_PROGRAM_SOF="${SOF}"
  export TRECAP_PROGRAM_MODE="${MODE}"
  export TRECAP_PROGRAM_CABLE="${CABLE}"
  export TRECAP_PROGRAM_OPERATION="${operation_arg}"
  "${PYTHON_BIN}" - <<'PY'
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
run_dir = Path(os.environ["TRECAP_PROGRAM_RUN_DIR"])
sof = Path(os.environ["TRECAP_PROGRAM_SOF"])
manifest = {
    "schema": "trecap_phase2_program_sof_manifest_v1",
    "file_class": "[2] generated programming-run manifest - do not edit by hand",
    "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "sof": sof.as_posix(),
    "sof_size_bytes": sof.stat().st_size,
    "sof_sha256": hashlib.sha256(sof.read_bytes()).hexdigest(),
    "mode": os.environ["TRECAP_PROGRAM_MODE"],
    "cable": os.environ["TRECAP_PROGRAM_CABLE"] or None,
    "operation": os.environ["TRECAP_PROGRAM_OPERATION"],
    "build_provenance": json.loads((run_dir / "build_provenance.json").read_text(encoding="utf-8")),
}
(run_dir / "program_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
else
  echo "DRY-RUN would write ${manifest_file}" | tee -a "${log_file}"
fi

echo "program_sof: OK run_dir=${RUN_DIR}" | tee -a "${log_file}"
