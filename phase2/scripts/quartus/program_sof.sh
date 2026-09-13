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
  --sof PATH          SOF file to program. If omitted, the newest SOF under
                      runs/quartus/de1soc or platform/de1soc/quartus/output_files
                      is selected.
  --cable NAME        Quartus cable name passed to quartus_pgm -c.
  --device-index N    Append @N to the programming operation for a JTAG chain.
  --mode MODE         Programming mode. Default: JTAG.
  --operation OP      Operation prefix. Default: p.
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
CABLE=""
DEVICE_INDEX=""
MODE="JTAG"
OPERATION="p"
RUN_DIR=""
LIST_CABLES=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sof) SOF="${2:?missing value for --sof}"; shift ;;
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

if [[ -z "${SOF}" ]]; then
  SOF="$(${PYTHON_BIN} - <<'PY'
from pathlib import Path
roots = [Path("runs/quartus/de1soc"), Path("platform/de1soc/quartus/output_files"), Path("output_files")]
files = []
for root in roots:
    if root.exists():
        files.extend(p for p in root.rglob("*.sof") if p.is_file())
if not files:
    raise SystemExit(1)
newest = max(files, key=lambda p: p.stat().st_mtime)
print(newest.as_posix())
PY
  )" || fail "no .sof found; pass --sof path/to/file.sof"
fi

[[ -f "${SOF}" ]] || fail "SOF file not found: ${SOF}"
case "${SOF}" in
  legacy/*|*/legacy/*) fail "refusing to program SOF from legacy path: ${SOF}" ;;
esac

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
}
(run_dir / "program_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
else
  echo "DRY-RUN would write ${manifest_file}" | tee -a "${log_file}"
fi

echo "program_sof: OK run_dir=${RUN_DIR}" | tee -a "${log_file}"
