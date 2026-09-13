#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 source lint and syntax hygiene.
# File class: [1] hand-written repository infrastructure.
#
# This script is intentionally a hygiene gate, not a functional verification
# target. It checks active implementation source, hand-written contracts, and
# infrastructure scripts. It does not compile RTL or prove algorithm correctness.

set -euo pipefail
IFS=$'\n\t'

usage() {
  cat <<'USAGE'
Usage: scripts/lint.sh [options]

Options:
  --basic          Fast pre-commit mode: syntax and structural checks only.
  --strict         Also run optional style tools and generated-contract checks.
  --generated      Run generated drift checks even outside --strict.
  --no-generated   Skip generated drift checks.
  --quiet          Reduce progress output.
  -h, --help       Show this help.

Checks performed:
  - Python syntax for hand-written Python scripts and tools.
  - Bash syntax for shell scripts.
  - JSON parse checks for source-of-truth contracts and configs.
  - Runtime/build profile inventory and semantic validation.
  - Frozen DE1-SoC Platform Designer/HPS snapshot and source-contract parity.
  - Step-4 source-frozen address map, semantic fingerprint, and source mirrors.
  - Step-5 Avalon-MM CSR adapter source contract and top-chain integration.
  - Step-6 Platform Designer wrapper, board binding, and typed Qsys graph contract.
  - Step-7 source-to-core mux, finite-replay tail, board, and safe-boundary contract.
  - Step-8 real core plus non-stalling telemetry composition and filelist contract.
  - Step-9 real DE1-SoC board-top source-integration and filelist contract.
  - Step-10 single-domain clock/reset, tick-enable, reset-owner, and SDC contract.
  - Step-11 BRAM replay-to-core-to-DDR source-path contract.
  - Step-12 DDR-ring ownership, WRAP, reset, and Linux-reservation source contract.
  - Step-13 HPS record-validation, UDP, malformed-latch, and dummy-STATUS contract.
  - Step-14 versioned PC-command, result, lifecycle, replay, CSR, and non-native RTL structural/model source gates.
  - Step-16 DE1-SoC LINE-IN PLL, WM8731 I2C, I2S/CDC, counter, profile, and dependency-free model source gates.
  - Step-17 DE1-SoC LTC2308 SPI timing, channel/format/rate, CDC, source-mux, profile, and dependency-free model gates.
  - Optional ruff, black --check, shellcheck, and clang-format checks when tools
    are installed and --strict is requested.
  - Optional generated-contract drift checks through scripts/check_generated.py.

Excluded by design:
  generated headers, generated filelists, frozen/reference outputs, telemetry
  captures, local runs, local build outputs, and quarantined historical material.
USAGE
}

BASIC=0
STRICT=0
GENERATED=0
NO_GENERATED=0
QUIET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --basic) BASIC=1 ;;
    --strict) STRICT=1 ;;
    --generated) GENERATED=1 ;;
    --no-generated) NO_GENERATED=1 ;;
    --quiet) QUIET=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if [[ ! -f Makefile || ! -d spec/generated || ! -d scripts ]]; then
  echo "ERROR: ${repo_root} does not look like the T_RECAP_Phase2 repository root" >&2
  exit 2
fi

log() {
  if [[ ${QUIET} -eq 0 ]]; then
    printf '%s\n' "$*"
  fi
}

status=0
record_fail() {
  status=1
}

find_active_files() {
  find "$@" \
    -path './.git' -prune -o \
    -path './legacy' -prune -o \
    -path './runs' -prune -o \
    -path './build' -prune -o \
    -path './out' -prune -o \
    -path './artifacts/reference_outputs' -prune -o \
    -path './artifacts/telemetry_captures' -prune -o \
    -path './rtl/include/generated' -prune -o \
    -path './sw/hps/include/generated' -prune -o \
    -path './sw/pc_dashboard/generated' -prune -o \
    -path './sw/reference_model/generated' -prune -o \
    -path './sw/golden/generated' -prune -o \
    -path './sw/reference_model/.venv' -prune -o \
    -path './sw/reference_model/build' -prune -o \
    -path './sw/reference_model/out' -prune -o \
    -path './sw/reference_model/runs' -prune -o \
    -path './sw/golden/.venv' -prune -o \
    -path './sw/golden/build' -prune -o \
    -path './sw/golden/out' -prune -o \
    -path './sw/golden/runs' -prune -o \
    -type f
}

mapfile -d '' python_files < <(
  find_active_files ./scripts ./sw 2>/dev/null \
    \( -name '*.py' \) -print0
)

mapfile -d '' shell_files < <(
  find_active_files ./scripts 2>/dev/null \
    \( -name '*.sh' \) -print0
)

mapfile -d '' json_files < <(
  find_active_files ./spec ./config ./sw ./artifacts 2>/dev/null \
    \( -name '*.json' \) -print0
)

mapfile -d '' c_files < <(
  find_active_files ./scripts ./sw 2>/dev/null \
    \( -name '*.c' -o -name '*.h' -o -name '*.cc' -o -name '*.cpp' -o -name '*.cxx' -o -name '*.hh' -o -name '*.hpp' -o -name '*.hxx' \) -print0
)

log "lint: Python syntax files=${#python_files[@]}"
if [[ ${#python_files[@]} -gt 0 ]]; then
  python3 -m py_compile "${python_files[@]}" || record_fail
fi

log "lint: shell syntax files=${#shell_files[@]}"
for f in "${shell_files[@]}"; do
  bash -n "${f}" || record_fail
done

log "lint: JSON parse files=${#json_files[@]}"
if [[ ${#json_files[@]} -gt 0 ]]; then
  python3 - "${json_files[@]}" <<'PY_JSON_LINT' || record_fail
import json
import sys
from pathlib import Path

failed = False
for name in sys.argv[1:]:
    path = Path(name)
    try:
        with path.open("r", encoding="utf-8") as handle:
            json.load(handle)
    except Exception as exc:  # noqa: BLE001 - lint script reports all JSON parse failures.
        print(f"ERROR: JSON parse failed: {path}: {exc}", file=sys.stderr)
        failed = True
if failed:
    raise SystemExit(1)
PY_JSON_LINT
fi

if [[ -x scripts/check_profiles.py ]]; then
  log "lint: runtime/build profiles"
  python3 scripts/check_profiles.py --all --quiet || record_fail
else
  echo "ERROR: profile validator missing or not executable: scripts/check_profiles.py" >&2
  record_fail
fi

if [[ -x scripts/check_hps_platform.py ]]; then
  log "lint: frozen Platform Designer/HPS source contract"
  python3 scripts/check_hps_platform.py --quiet || record_fail
else
  echo "ERROR: HPS platform validator missing or not executable: scripts/check_hps_platform.py" >&2
  record_fail
fi

if [[ -x scripts/check_address_map.py ]]; then
  log "lint: Step-4 source-frozen address map"
  python3 scripts/check_address_map.py --quiet || record_fail
else
  echo "ERROR: address-map validator missing or not executable: scripts/check_address_map.py" >&2
  record_fail
fi

if [[ -x scripts/check_csr_adapter.py ]]; then
  log "lint: Step-5 Avalon-MM CSR adapter source contract"
  python3 scripts/check_csr_adapter.py --quiet || record_fail
else
  echo "ERROR: CSR-adapter validator missing or not executable: scripts/check_csr_adapter.py" >&2
  record_fail
fi

if [[ -x scripts/check_platform_designer_wrapper.py ]]; then
  log "lint: Step-6 Platform Designer wrapper source contract"
  python3 scripts/check_platform_designer_wrapper.py --quiet || record_fail
else
  echo "ERROR: platform-wrapper validator missing or not executable: scripts/check_platform_designer_wrapper.py" >&2
  record_fail
fi

if [[ -x scripts/check_source_core_integration.py ]]; then
  log "lint: Step-7 source-to-core integration source contract"
  python3 scripts/check_source_core_integration.py --quiet || record_fail
else
  echo "ERROR: source-core integration validator missing or not executable: scripts/check_source_core_integration.py" >&2
  record_fail
fi

if [[ -x scripts/check_core_telemetry_composition.py ]]; then
  log "lint: Step-8 core plus telemetry composition source contract"
  python3 scripts/check_core_telemetry_composition.py --quiet || record_fail
else
  echo "ERROR: core-telemetry composition validator missing or not executable: scripts/check_core_telemetry_composition.py" >&2
  record_fail
fi

if [[ -x scripts/check_de1soc_board_top.py ]]; then
  log "lint: Step-9 DE1-SoC board-top source-integration contract"
  python3 scripts/check_de1soc_board_top.py --quiet || record_fail
else
  echo "ERROR: board-top validator missing or not executable: scripts/check_de1soc_board_top.py" >&2
  record_fail
fi

if [[ -x scripts/check_de1soc_clock_reset.py ]]; then
  log "lint: Step-10 DE1-SoC clock/reset source architecture"
  python3 scripts/check_de1soc_clock_reset.py --quiet || record_fail
else
  echo "ERROR: clock/reset validator missing or not executable: scripts/check_de1soc_clock_reset.py" >&2
  record_fail
fi

if [[ -x scripts/check_bram_replay_path.py ]]; then
  log "lint: Step-11 DE1-SoC BRAM replay path source contract"
  python3 scripts/check_bram_replay_path.py --quiet || record_fail
else
  echo "ERROR: BRAM-replay path validator missing or not executable: scripts/check_bram_replay_path.py" >&2
  record_fail
fi

if [[ -x scripts/check_ddr_ring_ownership.py ]]; then
  log "lint: Step-12 DDR-ring ownership source contract"
  python3 scripts/check_ddr_ring_ownership.py || record_fail
else
  echo "ERROR: DDR-ring ownership validator missing or not executable: scripts/check_ddr_ring_ownership.py" >&2
  record_fail
fi

if [[ -x scripts/check_hps_transport.py ]]; then
  log "lint: Step-13 HPS transport source contract"
  python3 scripts/check_hps_transport.py || record_fail
else
  echo "ERROR: HPS transport validator missing or not executable: scripts/check_hps_transport.py" >&2
  record_fail
fi

if [[ -x scripts/check_command_path.py ]]; then
  log "lint: Step-14 PC-to-FPGA command-path source contract"
  python3 scripts/check_command_path.py --quiet || record_fail
else
  echo "ERROR: command-path validator missing or not executable: scripts/check_command_path.py" >&2
  record_fail
fi

if [[ -f sim/check_step14_command_rtl.py ]]; then
  log "lint: Step-14 RTL structural/model source gate (not native simulation)"
  python3 sim/check_step14_command_rtl.py || record_fail
else
  echo "ERROR: Step-14 RTL structural/model checker missing: sim/check_step14_command_rtl.py" >&2
  record_fail
fi

if [[ -x scripts/check_de1soc_audio_path.py ]]; then
  log "lint: Step-16 DE1-SoC LINE-IN source contract"
  python3 scripts/check_de1soc_audio_path.py --quiet || record_fail
else
  echo "ERROR: Step-16 audio-path validator missing or not executable: scripts/check_de1soc_audio_path.py" >&2
  record_fail
fi

if [[ -x scripts/sim/check_step16_audio_model.py ]]; then
  log "lint: Step-16 dependency-free audio architecture model (not RTL simulation)"
  python3 scripts/sim/check_step16_audio_model.py || record_fail
else
  echo "ERROR: Step-16 audio architecture model missing or not executable: scripts/sim/check_step16_audio_model.py" >&2
  record_fail
fi

if [[ -x scripts/check_de1soc_adc_path.py ]]; then
  log "lint: Step-17 DE1-SoC ADC source contract"
  python3 scripts/check_de1soc_adc_path.py --quiet || record_fail
else
  echo "ERROR: Step-17 ADC-path validator missing or not executable: scripts/check_de1soc_adc_path.py" >&2
  record_fail
fi

if [[ -x scripts/sim/check_step17_adc_model.py ]]; then
  log "lint: Step-17 dependency-free ADC protocol/CDC model (not RTL simulation)"
  python3 scripts/sim/check_step17_adc_model.py || record_fail
else
  echo "ERROR: Step-17 ADC model missing or not executable: scripts/sim/check_step17_adc_model.py" >&2
  record_fail
fi

# Required generated-language outputs shall carry the no-edit banner. This is a
# cheap check, so keep it in --basic as well.
for f in \
  rtl/include/generated/trecap_core_pkg.sv \
  rtl/include/generated/trecap_csr_pkg.sv \
  rtl/include/generated/trecap_packet_pkg.sv \
  rtl/include/generated/trecap_iface_pkg.sv \
  sw/hps/include/generated/trecap_csr.h \
  sw/hps/include/generated/trecap_packet.h \
  sw/pc_dashboard/generated/trecap_packet.py \
  sw/reference_model/generated/trecap_config.py; do
  if [[ -f "${f}" ]] && ! head -n 8 "${f}" | grep -q 'AUTO-GENERATED - DO NOT EDIT'; then
    echo "ERROR: generated file missing no-edit banner: ${f}" >&2
    record_fail
  fi
done

if [[ ${STRICT} -eq 1 ]]; then
  if command -v ruff >/dev/null 2>&1 && [[ ${#python_files[@]} -gt 0 ]]; then
    log "lint: ruff strict syntax/safety"
    ruff check --select=E9,F63,F7,F82 "${python_files[@]}" || record_fail
  else
    log "lint: ruff unavailable or no Python files; skipped"
  fi

  if command -v black >/dev/null 2>&1 && [[ ${#python_files[@]} -gt 0 ]]; then
    log "lint: black --check"
    black --check --line-length 100 "${python_files[@]}" || record_fail
  else
    log "lint: black unavailable or no Python files; skipped"
  fi

  if command -v shellcheck >/dev/null 2>&1 && [[ ${#shell_files[@]} -gt 0 ]]; then
    log "lint: shellcheck"
    shellcheck "${shell_files[@]}" || record_fail
  else
    log "lint: shellcheck unavailable or no shell files; skipped"
  fi

  if command -v clang-format >/dev/null 2>&1 && [[ ${#c_files[@]} -gt 0 ]]; then
    log "lint: clang-format C/C++ check"
    tmp_status=0
    for f in "${c_files[@]}"; do
      tmp="$(mktemp)"
      clang-format --style=file --fallback-style=none "${f}" > "${tmp}" || tmp_status=1
      if ! cmp -s "${f}" "${tmp}"; then
        echo "format drift: ${f}" >&2
        tmp_status=1
      fi
      rm -f "${tmp}"
    done
    [[ ${tmp_status} -eq 0 ]] || record_fail
  else
    log "lint: clang-format unavailable or no C/C++ files; skipped"
  fi
fi

if [[ ${NO_GENERATED} -eq 0 && ( ${STRICT} -eq 1 || ${GENERATED} -eq 1 ) ]]; then
  if [[ -f scripts/check_generated.py ]]; then
    log "lint: generated-contract drift check"
    python3 scripts/check_generated.py --quiet || record_fail
  else
    echo "ERROR: scripts/check_generated.py missing" >&2
    record_fail
  fi
fi

if [[ ${status} -ne 0 ]]; then
  echo "lint: FAIL" >&2
  exit "${status}"
fi

echo "lint: OK"
