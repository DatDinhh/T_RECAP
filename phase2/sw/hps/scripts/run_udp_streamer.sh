#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 HPS UDP streamer launcher.
# File class: [1] hand-written HPS bring-up script.
#
# This script orchestrates the HPS userspace streamer binary. It reads the same
# runtime config used by sw/hps/src/config.c and keeps the safe bring-up default:
# STATUS-only first, then full-demo packets only after CSR/ring/UDP/parser sanity
# checks are already proven.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
HPS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd "${HPS_DIR}/../.." && pwd -P)"
DEFAULT_CONFIG="${HPS_DIR}/config/trecap_hps_config.json"
DEFAULT_BINARY="${REPO_ROOT}/build/hps/bin/trecap_udp_streamer"

CONFIG="${DEFAULT_CONFIG}"
CONFIG_EXPLICIT=0
BUILD_PROFILE=""
PROFILE_JSON=""
BINARY="${DEFAULT_BINARY}"
BUILD_MODE="auto"
DRY_RUN=0
PRE_FLIGHT_ONLY=0
CHECK_CONFIG=1
SETUP_IP=0
IFACE=""
SUDO_MODE="auto"
LOG_DIR=""
QUIET=0
SKIP_DDR_CHECK=0
DUMMY_UDP_COUNTER=0

STREAM_ARGS=()
STREAM_PROFILE_SET=0
EXTRA_ARGS=()

log() {
  if [[ "${QUIET}" -eq 0 ]]; then
    printf '[run_udp_streamer] %s\n' "$*"
  fi
}

warn() {
  printf '[run_udp_streamer] WARNING: %s\n' "$*" >&2
}

die() {
  printf '[run_udp_streamer] ERROR: %s\n' "$*" >&2
  exit 2
}

usage() {
  cat <<'USAGE_TEXT'
Usage: run_udp_streamer.sh [options]

Build/check and launch the T-RECAP Phase 2 HPS userspace UDP streamer.
Default behavior is safe STATUS-only bring-up.

Options:
  --profile <path>               Apply selected build profile and its telemetry preset.
  --config <path>                Runtime config JSON. Default: sw/hps/config/trecap_hps_config.json
  --binary <path>                Streamer binary. Default: build/hps/bin/trecap_udp_streamer
  --build                        Always run make -C sw/hps build first.
  --no-build                     Do not build; require --binary path to already exist.
  --dry-run                      Print the build/setup/run plan and exit.
  --preflight-only               Run checks only; do not launch the streamer.
  --no-check-config              Skip make -C sw/hps check-config.
  --setup-ip                     Apply sw/hps/scripts/setup_static_ip.sh before launching.
  --iface <name>                 Interface passed to setup_static_ip.sh, e.g. eth0.
  --sudo <auto|yes|no>           How to run the binary. Default: auto.
  --log-dir <path>               Log directory. Default: runs/hps/<UTC timestamp>.
  --skip-ddr-check               Skip /proc/iomem reserved-ring sanity check.

Streamer profile/options forwarded to trecap_udp_streamer:
  --status-only                  Enable STATUS only. Default.
  --full-demo                    Enable WAVE, SPEC, METRICS, and STATUS.
  --no-enable                    Configure but leave FPGA telemetry disabled.
  --once                         Exit after the first non-empty service pass.
  --max-records <n>              Exit after consuming n normal records.
  --poll-us <n>                  Idle sleep between polls.
  --no-commands                  Do not open the command UDP listener.
  --allow-any-command-source     Lab mode: pin first fully valid PING endpoint.
  --stop-on-malformed            Stop process after malformed-record handling.
  --dummy-udp-counter            M0 UDP-only diagnostic STATUS counter; no CSR/DDR/root.
  --packet-enable <mask>         Override PACKET_ENABLE.
  --wave-decim <n>               Set WAVE_DECIM.
  --spec-mode <0|1|2>            0 disabled, 1 SPEC64, 2 SPEC129.
  --spec-shift <n>               Set SPEC_SHIFT.
  --source-mode <0..3>           Set source-mode shadow/commit.
  --thr2 <n>                     Set 56-bit THR2 through shadow/commit.
  --sample-rate-hz <n>           Diagnostic STATUS sample-rate field.
  --streamer-arg <arg>           Forward one raw argument to trecap_udp_streamer.
  --quiet                        Reduce launcher output and pass --quiet to streamer.
  --verbose                      More launcher output and pass --verbose to streamer.
  --help                         Show this help.

Examples:
  # Host-side dry-run:
  sw/hps/scripts/run_udp_streamer.sh --dry-run

  # HPS STATUS-only bring-up after FPGA bitstream is loaded:
  sudo sw/hps/scripts/run_udp_streamer.sh --setup-ip --iface eth0 --status-only

  # Full demo after STATUS-only path is verified:
  sudo sw/hps/scripts/run_udp_streamer.sh --full-demo --wave-decim 2 --spec-mode 1 --spec-shift 16
USAGE_TEXT
}

require_file() {
  [[ -f "$1" ]] || die "missing file: $1"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

json_value() {
  local key="$1"
  python3 - "${CONFIG}" "${key}" <<'PY_JSON'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
key = sys.argv[2]
with path.open("r", encoding="utf-8") as f:
    data = json.load(f)
value = data.get(key, "")
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(value)
PY_JSON
}

append_arg_with_value() {
  local opt="$1"
  local value="$2"
  STREAM_ARGS+=("${opt}" "${value}")
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      [[ $# -ge 2 ]] || die "--profile requires a path"
      BUILD_PROFILE="$2"
      shift 2
      ;;
    --config)
      [[ $# -ge 2 ]] || die "--config requires a path"
      CONFIG="$2"
      CONFIG_EXPLICIT=1
      shift 2
      ;;
    --binary)
      [[ $# -ge 2 ]] || die "--binary requires a path"
      BINARY="$2"
      shift 2
      ;;
    --build)
      BUILD_MODE="always"
      shift
      ;;
    --no-build)
      BUILD_MODE="never"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --preflight-only)
      PRE_FLIGHT_ONLY=1
      shift
      ;;
    --no-check-config)
      CHECK_CONFIG=0
      shift
      ;;
    --setup-ip)
      SETUP_IP=1
      shift
      ;;
    --iface)
      [[ $# -ge 2 ]] || die "--iface requires a name"
      IFACE="$2"
      shift 2
      ;;
    --sudo)
      [[ $# -ge 2 ]] || die "--sudo requires auto, yes, or no"
      SUDO_MODE="$2"
      [[ "${SUDO_MODE}" == "auto" || "${SUDO_MODE}" == "yes" || "${SUDO_MODE}" == "no" ]] || die "invalid --sudo mode: ${SUDO_MODE}"
      shift 2
      ;;
    --log-dir)
      [[ $# -ge 2 ]] || die "--log-dir requires a path"
      LOG_DIR="$2"
      shift 2
      ;;
    --skip-ddr-check)
      SKIP_DDR_CHECK=1
      shift
      ;;
    --status-only)
      STREAM_ARGS+=("--status-only")
      STREAM_PROFILE_SET=1
      shift
      ;;
    --full-demo)
      STREAM_ARGS+=("--full-demo")
      STREAM_PROFILE_SET=1
      shift
      ;;
    --dummy-udp-counter)
      DUMMY_UDP_COUNTER=1
      STREAM_ARGS+=("--dummy-udp-counter")
      shift
      ;;
    --no-enable|--once|--no-commands|--allow-any-command-source|--stop-on-malformed)
      STREAM_ARGS+=("$1")
      shift
      ;;
    --max-records|--poll-us|--packet-enable|--wave-decim|--spec-mode|--spec-shift|--source-mode|--thr2|--sample-rate-hz)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      append_arg_with_value "$1" "$2"
      shift 2
      ;;
    --streamer-arg)
      [[ $# -ge 2 ]] || die "--streamer-arg requires a raw argument"
      EXTRA_ARGS+=("$2")
      shift 2
      ;;
    --quiet)
      QUIET=1
      STREAM_ARGS+=("--quiet")
      shift
      ;;
    --verbose)
      STREAM_ARGS+=("--verbose")
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

if [[ "${SKIP_DDR_CHECK}" -eq 1 && "${DRY_RUN}" -eq 0 && "${PRE_FLIGHT_ONLY}" -eq 0 ]]; then
  die "--skip-ddr-check is permitted only with --dry-run or --preflight-only"
fi

require_cmd python3
if [[ -n "${BUILD_PROFILE}" ]]; then
  resolver="${REPO_ROOT}/scripts/resolve_runtime_profile.py"
  require_file "${resolver}"
  PROFILE_JSON="$(python3 "${resolver}" --root "${REPO_ROOT}" --profile "${BUILD_PROFILE}")" || die "profile resolution failed"
  profile_args_text="$(python3 "${resolver}" --root "${REPO_ROOT}" --profile "${BUILD_PROFILE}" --format hps-args)" || die "profile argument resolution failed"
  readarray -t profile_args <<< "${profile_args_text}"
  # Explicit CLI controls follow the profile and are recorded in the launch manifest.
  STREAM_ARGS=("${profile_args[@]}" "${STREAM_ARGS[@]}")
  STREAM_PROFILE_SET=1
  if [[ "${CONFIG_EXPLICIT}" -eq 0 ]]; then
    CONFIG="$(python3 "${resolver}" --root "${REPO_ROOT}" --profile "${BUILD_PROFILE}" --format hps-config)" || die "profile runtime config resolution failed"
  fi
fi
require_file "${CONFIG}"

if [[ "${STREAM_PROFILE_SET}" -eq 0 && "${DUMMY_UDP_COUNTER}" -eq 0 ]]; then
  STREAM_ARGS=("--status-only" "${STREAM_ARGS[@]}")
fi

if [[ -z "${LOG_DIR}" ]]; then
  LOG_DIR="${REPO_ROOT}/runs/hps/$(date -u +%Y%m%dT%H%M%SZ)"
fi

build_needed=0
case "${BUILD_MODE}" in
  always)
    build_needed=1
    ;;
  auto)
    [[ -x "${BINARY}" ]] || build_needed=1
    ;;
  never)
    build_needed=0
    ;;
esac

run_or_print() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[run_udp_streamer] DRY-RUN: '
    printf '%q ' "$@"
    printf '\n'
  else
    log "+ $*"
    "$@"
  fi
}

check_config() {
  if [[ "${CHECK_CONFIG}" -eq 1 ]]; then
    if [[ -f "${HPS_DIR}/Makefile" ]]; then
      run_or_print make -C "${HPS_DIR}" CONFIG="${CONFIG}" check-config
    else
      warn "sw/hps/Makefile not found; skipped check-config"
    fi
  fi
}

check_ddr_reservation() {
  if [[ "${DUMMY_UDP_COUNTER}" -eq 1 ]]; then
    log "dummy UDP mode: CSR/DDR reservation check is not applicable"
    return 0
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "dry-run: live DDR reservation proof is deferred to target execution"
    return 0
  fi
  if [[ "${SKIP_DDR_CHECK}" -eq 1 ]]; then
    warn "skipped DDR ring /proc/iomem overlap check"
    return 0
  fi
  local start_hex size_dec dt_node
  local -a proof_cmd=(python3)
  start_hex="$(json_value ring_base_hps_phys)"
  size_dec="$(json_value ring_size_bytes)"
  [[ -n "${start_hex}" && -n "${size_dec}" ]] || die "config missing ring_base_hps_phys or ring_size_bytes"
  dt_node="/sys/firmware/devicetree/base/reserved-memory/trecap-ring@3e000000"

  if [[ "$(id -u)" -ne 0 && "${SUDO_MODE}" != no ]]; then
    command -v sudo >/dev/null 2>&1 || die "sudo is required to prove the live DDR reservation"
    proof_cmd=(sudo -E python3)
  fi

  if "${proof_cmd[@]}" - "${start_hex}" "${size_dec}" "${dt_node}" /proc/iomem <<'PY_IOMEM'
import re
import sys
from pathlib import Path
start = int(str(sys.argv[1]), 0)
size = int(str(sys.argv[2]), 0)
end = start + size
node = Path(sys.argv[3])
path = sys.argv[4]
reg = node / "reg"
no_map = node / "no-map"
reusable = node / "reusable"
if not reg.is_file() or not no_map.exists() or reusable.exists():
    raise SystemExit(f"live DT reservation invalid: {node} requires exact reg + no-map and no reusable")
raw = reg.read_bytes()
expected = start.to_bytes(4, "big") + size.to_bytes(4, "big")
if raw != expected:
    raise SystemExit(f"live DT reg mismatch: got={raw.hex()} expected={expected.hex()}")
intersections = []
unmasked_system_ram_ranges = 0
with open(path, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        m = re.match(r"\s*([0-9a-fA-F]+)-([0-9a-fA-F]+)\s*:\s*(.*)", line)
        if not m:
            continue
        lo = int(m.group(1), 16)
        hi = int(m.group(2), 16) + 1
        label = m.group(3).strip()
        if "System RAM" in label:
            if lo != 0 or hi != 1:
                unmasked_system_ram_ranges += 1
        if max(start, lo) < min(end, hi) and "System RAM" in label:
            intersections.append((lo, hi, label))
if unmasked_system_ram_ranges == 0:
    raise SystemExit("/proc/iomem is empty, masked, or lacks System RAM evidence")
if intersections:
    print(f"ring [0x{start:08x},0x{end:08x}) overlaps System RAM:")
    for lo, hi, label in intersections:
        print(f"  0x{lo:08x}-0x{hi - 1:08x}: {label}")
    raise SystemExit(1)
print(f"ring [0x{start:08x},0x{end:08x}) does not overlap /proc/iomem System RAM entries")
PY_IOMEM
  then
    log "DDR ring reservation check passed"
  else
    die "live DDR reservation proof failed (invalid DT node, masked/unreadable iomem, or System RAM overlap). See reserve_ddr_region_notes.md."
  fi
}

log "repo root: ${REPO_ROOT}"
log "HPS dir:   ${HPS_DIR}"
log "config:    ${CONFIG}"
[[ -z "${BUILD_PROFILE}" ]] || log "profile:   ${BUILD_PROFILE}"
log "binary:    ${BINARY}"
log "log dir:   ${LOG_DIR}"

if [[ "${build_needed}" -eq 1 ]]; then
  run_or_print make -C "${HPS_DIR}" CONFIG="${CONFIG}" build
fi

check_config

if [[ "${SETUP_IP}" -eq 1 ]]; then
  setup_cmd=("${SCRIPT_DIR}/setup_static_ip.sh" --config "${CONFIG}" --apply)
  if [[ -n "${IFACE}" ]]; then
    setup_cmd+=(--iface "${IFACE}")
  fi
  run_or_print "${setup_cmd[@]}"
fi

check_ddr_reservation

if [[ "${PRE_FLIGHT_ONLY}" -eq 1 ]]; then
  log "preflight-only requested; not launching streamer"
  exit 0
fi

if [[ "${DRY_RUN}" -eq 0 ]]; then
  require_file "${BINARY}"
  [[ -x "${BINARY}" ]] || die "binary is not executable: ${BINARY}"
  mkdir -p "${LOG_DIR}"
  if [[ -n "${PROFILE_JSON}" ]]; then
    printf '%s\n' "${PROFILE_JSON}" >"${LOG_DIR}/effective_runtime.json"
  fi
fi

cmd=("${BINARY}" --config "${CONFIG}" "${STREAM_ARGS[@]}" "${EXTRA_ARGS[@]}")
case "${SUDO_MODE}" in
  yes)
    command -v sudo >/dev/null 2>&1 || die "sudo requested but sudo is not installed"
    cmd=(sudo -E "${cmd[@]}")
    ;;
  auto)
    if [[ "${DUMMY_UDP_COUNTER}" -eq 0 && "$(id -u)" -ne 0 ]]; then
      if command -v sudo >/dev/null 2>&1; then
        cmd=(sudo -E "${cmd[@]}")
      else
        warn "not root and sudo not found; /dev/mem mapping will likely fail"
      fi
    fi
    ;;
  no)
    ;;
esac

if [[ "${DRY_RUN}" -eq 1 ]]; then
  printf '[run_udp_streamer] DRY-RUN launch: '
  printf '%q ' "${cmd[@]}"
  printf '\n'
  exit 0
fi

log_file="${LOG_DIR}/trecap_udp_streamer.log"
manifest_file="${LOG_DIR}/launch_manifest.txt"
{
  printf 'repo_root=%s\n' "${REPO_ROOT}"
  printf 'hps_dir=%s\n' "${HPS_DIR}"
  printf 'config=%s\n' "${CONFIG}"
  printf 'profile=%s\n' "${BUILD_PROFILE}"
  printf 'binary=%s\n' "${BINARY}"
  printf 'command='
  printf '%q ' "${cmd[@]}"
  printf '\n'
} >"${manifest_file}"

log "launching streamer; log: ${log_file}"
set +e
"${cmd[@]}" 2>&1 | tee -a "${log_file}"
status=${PIPESTATUS[0]}
set -e
log "streamer exited with status ${status}"
exit "${status}"
