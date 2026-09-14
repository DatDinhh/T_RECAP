#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 DE1-SoC Platform Designer lifecycle runner.
# File class: [1] hand-written platform source.

set -euo pipefail
IFS=$'\n\t'

usage() {
  cat <<'USAGE'
Usage: platform/de1soc/qsys/generate_system.sh [options]

Modes:
  --mode auto          Bootstrap: construct then generate. Normalized Qsys: generate only.
                       Without Intel tools, validate and emit reviewed configs.
  --mode validate      Validate frozen inputs only; no Intel tool or output mutation.
  --mode emit-configs  Validate/preserve HPS runtime and address-map JSON.
  --mode construct     Explicitly construct and normalize system.qsys with qsys-script.
                       Does not run qsys-generate.
  --mode generate      Read an existing normalized system.qsys, capture HPS readbacks,
                       and run qsys-generate. Never reconstructs or rewires the graph.

Options:
  --repo-root PATH       Override repository root. Default: auto-detect.
  --run-dir PATH         Run logs/provenance. Default: runs/platform/de1soc/qsys/<UTC>-<PID>.
  --qsys-script PATH     Default: QSYS_SCRIPT or qsys-script.
  --qsys-generate PATH   Default: QSYS_GENERATE or qsys-generate.
  --quartus-sh PATH      Default: QUARTUS_SH or quartus_sh.
  --qsys-package-version VERSION
                         Frozen Tcl API package. Default: QSYS_PACKAGE_VERSION or 16.0.
  --tclsh PATH           Default: TCLSH or tclsh.
  --python PATH          Default: PYTHON or python3.
  --force                With construct/auto only, intentionally replace even a normalized Qsys.
  --reuse-existing       Compatibility alias selecting generate from auto mode.
  --clean-generated      Remove exact generated output paths before qsys-generate (default).
  --keep-generated       Do not clean first; mandatory postchecks still reject missing outputs.
  --dry-run              Validate source and print lifecycle/tool commands without tool mutation.
  --no-emit-configs      Skip reviewed runtime/address-map config emission.
  --require-qsys         In auto mode, fail instead of falling back when Intel tools are absent.
  --skip-contract-checks Skip generic generated-header/filelist drift checks only.
  --print-summary        Print resolved frozen HPS/Qsys configuration.
  --require-sopcinfo     Compatibility no-op; SOPCINFO is always mandatory for real generation.
  -h, --help             Show this help.

The pinned real flow requires Quartus 20.1, qsys-script API 16.0, a normalized
system.qsys, complete 44-value HPS readback capture, system.sopcinfo,
system/synthesis/system.qip, and system/synthesis/system.v or system.sv.
Generated Platform Designer files shall not be hand-edited.
USAGE
}

MODE="auto"
REPO_ROOT=""
RUN_DIR=""
QSYS_SCRIPT_BIN="${QSYS_SCRIPT:-qsys-script}"
QSYS_GENERATE_BIN="${QSYS_GENERATE:-qsys-generate}"
QUARTUS_SH_BIN="${QUARTUS_SH:-quartus_sh}"
QSYS_PACKAGE_VERSION="${QSYS_PACKAGE_VERSION:-16.0}"
TCLSH_BIN="${TCLSH:-tclsh}"
PYTHON_BIN="${PYTHON:-python3}"
FORCE=0
REUSE_EXISTING=0
DRY_RUN=0
CLEAN_GENERATED=1
EMIT_CONFIGS=1
REQUIRE_QSYS=0
SKIP_CONTRACT_CHECKS=0
PRINT_SUMMARY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:?missing value for --mode}"; shift ;;
    --repo-root) REPO_ROOT="${2:?missing value for --repo-root}"; shift ;;
    --run-dir|--log-dir) RUN_DIR="${2:?missing value for $1}"; shift ;;
    --qsys-script) QSYS_SCRIPT_BIN="${2:?missing value for --qsys-script}"; shift ;;
    --qsys-generate) QSYS_GENERATE_BIN="${2:?missing value for --qsys-generate}"; shift ;;
    --quartus-sh) QUARTUS_SH_BIN="${2:?missing value for --quartus-sh}"; shift ;;
    --qsys-package-version) QSYS_PACKAGE_VERSION="${2:?missing value for --qsys-package-version}"; shift ;;
    --tclsh) TCLSH_BIN="${2:?missing value for --tclsh}"; shift ;;
    --python) PYTHON_BIN="${2:?missing value for --python}"; shift ;;
    --force) FORCE=1 ;;
    --no-force) FORCE=0 ;;
    --reuse-existing) REUSE_EXISTING=1 ;;
    --strict-exports) : ;;
    --dry-run) DRY_RUN=1 ;;
    --clean-generated) CLEAN_GENERATED=1 ;;
    --keep-generated|--no-clean-generated) CLEAN_GENERATED=0 ;;
    --no-emit-configs|--skip-emit-configs) EMIT_CONFIGS=0 ;;
    --require-qsys) REQUIRE_QSYS=1 ;;
    --require-sopcinfo) : ;;
    --skip-contract-checks) SKIP_CONTRACT_CHECKS=1 ;;
    --print-summary) PRINT_SUMMARY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "${MODE}" in
  auto|validate|emit-configs|construct|generate) ;;
  dry-run) MODE="auto"; DRY_RUN=1 ;;
  *) echo "ERROR: invalid --mode '${MODE}'" >&2; exit 2 ;;
esac
if [[ ${REUSE_EXISTING} -eq 1 ]]; then
  if [[ "${MODE}" == "auto" ]]; then MODE="generate"; fi
  [[ "${MODE}" == "generate" ]] || { echo "ERROR: --reuse-existing conflicts with --mode ${MODE}" >&2; exit 2; }
fi
if [[ "${MODE}" == "generate" && ${FORCE} -eq 1 ]]; then
  echo "ERROR: --force is construction-only and is forbidden with --mode generate" >&2
  exit 2
fi
if [[ "${QSYS_PACKAGE_VERSION}" != "16.0" ]]; then
  echo "ERROR: qsys Tcl API is frozen to 16.0; refusing ${QSYS_PACKAGE_VERSION}" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${REPO_ROOT}" ]]; then
  REPO_ROOT="$(cd "${script_dir}/../../.." && pwd)"
else
  REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"
fi
cd "${REPO_ROOT}"
# Keep the standard vendor catalog and add the source-owned CSR bridge.
IP_SEARCH_PATH="${REPO_ROOT}/platform/de1soc/qsys/ip/trecap_csr_bridge/*,$"
if [[ ! -f Makefile || ! -d spec/generated || ! -d platform/de1soc/qsys ]]; then
  echo "ERROR: ${REPO_ROOT} is not the T_RECAP_Phase2 repository root" >&2
  exit 2
fi

if [[ -z "${RUN_DIR}" ]]; then
  RUN_DIR="runs/platform/de1soc/qsys/$(date -u +%Y%m%dT%H%M%SZ)-$$"
fi
if [[ -e "${RUN_DIR}" || -L "${RUN_DIR}" ]]; then
  echo "ERROR: run directory already exists; choose a unique --run-dir: ${RUN_DIR}" >&2
  exit 2
fi
mkdir -p "${RUN_DIR}"
LOG_FILE="${RUN_DIR}/generate_system.log"
MANIFEST_FILE="${RUN_DIR}/generate_system_manifest.json"
READBACK_FILE="${RUN_DIR}/hps_readback.tsv"
VERSION_FILE="${RUN_DIR}/quartus_version.log"
: > "${LOG_FILE}"

say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }
warn() { printf 'warning: %s\n' "$*" | tee -a "${LOG_FILE}" >&2; }
fail() { printf 'ERROR: %s\n' "$*" | tee -a "${LOG_FILE}" >&2; exit 1; }
say_cmd() { printf '+' | tee -a "${LOG_FILE}"; printf ' %q' "$@" | tee -a "${LOG_FILE}"; printf '\n' | tee -a "${LOG_FILE}"; }
run_check() { say_cmd "$@"; "$@" 2>&1 | tee -a "${LOG_FILE}"; }
run_logged() {
  local stage_log="$1"; shift
  say_cmd "$@"
  if [[ ${DRY_RUN} -eq 0 ]]; then
    "$@" 2>&1 | tee "${stage_log}" | tee -a "${LOG_FILE}"
  fi
}
have_cmd() { command -v "$1" >/dev/null 2>&1; }
required_file() { [[ -f "$1" ]] || fail "required file missing: $1"; }
required_dir() { [[ -d "$1" ]] || fail "required directory missing: $1"; }
qsys_tcl_command_for_argv() {
  local encoded="" separator="" argument hex
  for argument in "$@"; do
    hex="$(LC_ALL=C printf '%s' "${argument}" | od -An -v -tx1 | tr -d ' \n')"
    encoded+="${separator}${hex}"
    separator=","
  done
  printf 'set ::trecap_pd_cli_hex {%s}' "${encoded}"
}

PD_TCL="platform/de1soc/qsys/platform_designer.tcl"
HPS_CFG="platform/de1soc/qsys/hps_config.tcl"
BLUEPRINT="platform/de1soc/qsys/system_blueprint.xml"
SYSTEM_QSYS="platform/de1soc/qsys/system.qsys"
GENERATED_DIR="platform/de1soc/qsys/system"
SOPCINFO_FILE="platform/de1soc/qsys/system.sopcinfo"
QIP_FILE="platform/de1soc/qsys/system/synthesis/system.qip"
HDL_V_FILE="platform/de1soc/qsys/system/synthesis/system.v"
HDL_SV_FILE="platform/de1soc/qsys/system/synthesis/system.sv"
MANIFEST_WRITER="scripts/write_platform_generation_manifest.py"
ADDRESS_CHECKER="scripts/check_address_map.py"
CSR_ADAPTER_CHECKER="scripts/check_csr_adapter.py"
PLATFORM_WRAPPER_CHECKER="scripts/check_platform_designer_wrapper.py"

qsys_state() {
  if grep -q 'T_RECAP_BOOTSTRAP_QSYS_SOURCE=1' "${SYSTEM_QSYS}"; then
    printf bootstrap
  else
    printf quartus_normalized
  fi
}

for file in "${PD_TCL}" "${HPS_CFG}" "${BLUEPRINT}" "${SYSTEM_QSYS}" \
  platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv \
  platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json \
  scripts/check_hps_platform.py "${ADDRESS_CHECKER}" "${CSR_ADAPTER_CHECKER}" \
  "${PLATFORM_WRAPPER_CHECKER}" \
  "${MANIFEST_WRITER}"; do
  required_file "${file}"
done
for directory in platform/de1soc/qsys platform/de1soc/address_map platform/de1soc/generated_notes sw/hps/config; do
  required_dir "${directory}"
done

say "generate_system: repository root ${REPO_ROOT}"
say "generate_system: requested mode ${MODE}"
say "generate_system: working Qsys state $(qsys_state)"
say "generate_system: run directory ${RUN_DIR}"

# This source/config gate is mandatory in every mode, including dry-run.
run_check "${PYTHON_BIN}" scripts/check_hps_platform.py --repo-root "${REPO_ROOT}"
run_check "${PYTHON_BIN}" "${ADDRESS_CHECKER}" --repo-root "${REPO_ROOT}"
run_check "${PYTHON_BIN}" "${CSR_ADAPTER_CHECKER}" --repo-root "${REPO_ROOT}"
run_check "${PYTHON_BIN}" "${PLATFORM_WRAPPER_CHECKER}" --repo-root "${REPO_ROOT}"
if [[ ${SKIP_CONTRACT_CHECKS} -eq 0 ]]; then
  # Header generation parity is separate from the optional legacy tests.
  run_check "${PYTHON_BIN}" scripts/gen_headers.py --check --quiet
  [[ -f scripts/gen_filelists.py ]] && run_check "${PYTHON_BIN}" scripts/gen_filelists.py --check --quiet
else
  warn "skipping generic generated-contract checks by request"
fi
validate_args=("${TCLSH_BIN}" "${PD_TCL}" --mode validate --repo-root "${REPO_ROOT}")
[[ ${PRINT_SUMMARY} -eq 1 ]] && validate_args+=(--print-summary)
run_check "${validate_args[@]}"

tools_available=1
for tool in "${QSYS_SCRIPT_BIN}" "${QSYS_GENERATE_BIN}" "${QUARTUS_SH_BIN}"; do
  if ! have_cmd "${tool}"; then tools_available=0; fi
done

case "${MODE}" in
  validate) EFFECTIVE_MODE="validate" ;;
  emit-configs) EFFECTIVE_MODE="emit-configs" ;;
  construct) EFFECTIVE_MODE="construct" ;;
  generate) EFFECTIVE_MODE="generate" ;;
  auto)
    if [[ ${DRY_RUN} -eq 1 || ${tools_available} -eq 1 ]]; then
      if [[ "$(qsys_state)" == "bootstrap" ]]; then
        EFFECTIVE_MODE="construct+generate"
      else
        EFFECTIVE_MODE="generate"
      fi
    else
      [[ ${REQUIRE_QSYS} -eq 0 ]] || fail "Quartus 20.1 qsys-script, qsys-generate, and quartus_sh are required"
      EFFECTIVE_MODE="validate"
      warn "Intel FPGA tools not found; auto mode will validate and emit reviewed configs only"
    fi
    ;;
esac
say "generate_system: effective mode ${EFFECTIVE_MODE}"

if [[ ${EMIT_CONFIGS} -eq 1 && "${EFFECTIVE_MODE}" != "validate" ]]; then
  emit_args=("${TCLSH_BIN}" "${PD_TCL}" --mode emit-configs --repo-root "${REPO_ROOT}" --emit-all-manifests)
  [[ ${DRY_RUN} -eq 1 ]] && emit_args+=(--dry-run)
  run_check "${emit_args[@]}"
fi

if [[ "${EFFECTIVE_MODE}" == "validate" || "${EFFECTIVE_MODE}" == "emit-configs" ]]; then
  CONSTRUCTION_PERFORMED=false
else
  CONSTRUCTION_PERFORMED=false
  if [[ ${DRY_RUN} -eq 0 ]]; then
    have_cmd "${QSYS_SCRIPT_BIN}" || fail "qsys-script is required: ${QSYS_SCRIPT_BIN}"
    have_cmd "${QUARTUS_SH_BIN}" || fail "quartus_sh is required: ${QUARTUS_SH_BIN}"
    if [[ "${EFFECTIVE_MODE}" == "generate" || "${EFFECTIVE_MODE}" == "construct+generate" ]]; then
      have_cmd "${QSYS_GENERATE_BIN}" || fail "qsys-generate is required: ${QSYS_GENERATE_BIN}"
    fi
    run_logged "${VERSION_FILE}" "${QUARTUS_SH_BIN}" --version
    "${PYTHON_BIN}" - "${VERSION_FILE}" <<'PY'
import sys
from pathlib import Path
from scripts.write_platform_generation_manifest import quartus_identity, supported_quartus_identity

version_text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
identity = quartus_identity(version_text)
if not supported_quartus_identity(identity):
    raise SystemExit(
        "This flow requires Quartus Prime 20.1.x Standard or Lite Edition; see " + sys.argv[1]
    )
print("Selected Quartus " + identity["release"] + " " + identity["edition"])
PY
  else
    say_cmd "${QUARTUS_SH_BIN}" --version
  fi

  if [[ "${EFFECTIVE_MODE}" == "construct" || "${EFFECTIVE_MODE}" == "construct+generate" ]]; then
    construct_args=(--mode construct --repo-root "${REPO_ROOT}" --strict-exports --readback-output "${READBACK_FILE}")
    [[ ${FORCE} -eq 1 ]] && construct_args+=(--force)
    [[ ${EMIT_CONFIGS} -eq 1 ]] && construct_args+=(--emit-all-manifests)
    [[ ${PRINT_SUMMARY} -eq 1 ]] && construct_args+=(--print-summary)
    if [[ ${DRY_RUN} -eq 1 ]]; then
      run_check "${TCLSH_BIN}" "${PD_TCL}" "${construct_args[@]}" --dry-run
      qsys_tcl_cmd="$(qsys_tcl_command_for_argv "${construct_args[@]}")"
      say_cmd "${QSYS_SCRIPT_BIN}" "--search-path=${IP_SEARCH_PATH}" "--package-version=${QSYS_PACKAGE_VERSION}" \
        "--cmd=${qsys_tcl_cmd}" "--script=${PD_TCL}"
    else
      qsys_tcl_cmd="$(qsys_tcl_command_for_argv "${construct_args[@]}")"
      run_logged "${RUN_DIR}/qsys_construct.log" "${QSYS_SCRIPT_BIN}" \
        "--search-path=${IP_SEARCH_PATH}" "--package-version=${QSYS_PACKAGE_VERSION}" "--cmd=${qsys_tcl_cmd}" "--script=${PD_TCL}"
      [[ "$(qsys_state)" == "quartus_normalized" ]] || fail "qsys-script did not replace the bootstrap with normalized system.qsys"
      required_file "${READBACK_FILE}"
    fi
    CONSTRUCTION_PERFORMED=true
  fi

  if [[ "${EFFECTIVE_MODE}" == "generate" || "${EFFECTIVE_MODE}" == "construct+generate" ]]; then
    if [[ "$(qsys_state)" == "bootstrap" ]]; then
      if [[ ${DRY_RUN} -eq 1 ]]; then
        warn "dry-run is showing normalized-Qsys reuse, but checked-in system.qsys is still the bootstrap"
      else
        fail "generate requires a Quartus-normalized system.qsys; run --mode construct first"
      fi
    fi

    if [[ "${CONSTRUCTION_PERFORMED}" == "false" ]]; then
      readback_args=(--mode capture-readback --repo-root "${REPO_ROOT}" --readback-output "${READBACK_FILE}")
      qsys_tcl_cmd="$(qsys_tcl_command_for_argv "${readback_args[@]}")"
      if [[ ${DRY_RUN} -eq 1 ]]; then
        say_cmd "${QSYS_SCRIPT_BIN}" "--search-path=${IP_SEARCH_PATH}" "--package-version=${QSYS_PACKAGE_VERSION}" \
          "--cmd=${qsys_tcl_cmd}" "--script=${PD_TCL}"
      else
        run_logged "${RUN_DIR}/qsys_readback.log" "${QSYS_SCRIPT_BIN}" \
          "--search-path=${IP_SEARCH_PATH}" "--package-version=${QSYS_PACKAGE_VERSION}" "--cmd=${qsys_tcl_cmd}" "--script=${PD_TCL}"
        required_file "${READBACK_FILE}"
      fi
    fi

    if [[ ${CLEAN_GENERATED} -eq 1 ]]; then
      [[ ! -L "${GENERATED_DIR}" ]] || fail "refusing to clean symlinked generated directory: ${GENERATED_DIR}"
      if [[ ${DRY_RUN} -eq 1 ]]; then
        say "DRY-RUN: remove exact generated paths ${GENERATED_DIR} and ${SOPCINFO_FILE}"
      else
        rm -rf -- "${GENERATED_DIR}"
        rm -f -- "${SOPCINFO_FILE}"
      fi
    fi
    run_logged "${RUN_DIR}/qsys_generate.log" "${QSYS_GENERATE_BIN}" "${SYSTEM_QSYS}" \
      --synthesis=VERILOG "--search-path=${IP_SEARCH_PATH}" "--output-directory=${GENERATED_DIR}"
    if [[ ${DRY_RUN} -eq 0 ]]; then
      run_check "${PYTHON_BIN}" "${ADDRESS_CHECKER}" \
        --repo-root "${REPO_ROOT}" --require-sopcinfo
      run_check "${PYTHON_BIN}" "${PLATFORM_WRAPPER_CHECKER}" \
        --repo-root "${REPO_ROOT}" --require-generated
    else
      say_cmd "${PYTHON_BIN}" "${ADDRESS_CHECKER}" \
        --repo-root "${REPO_ROOT}" --require-sopcinfo
      say_cmd "${PYTHON_BIN}" "${PLATFORM_WRAPPER_CHECKER}" \
        --repo-root "${REPO_ROOT}" --require-generated
    fi
  fi
fi

if [[ ${DRY_RUN} -eq 0 ]]; then
  manifest_args=(
    "${PYTHON_BIN}" "${MANIFEST_WRITER}"
    --repo-root "${REPO_ROOT}"
    --output "${MANIFEST_FILE}"
    --mode-requested "${MODE}"
    --mode-effective "${EFFECTIVE_MODE}"
    --construction-performed "${CONSTRUCTION_PERFORMED}"
    --qsys-script "${QSYS_SCRIPT_BIN}"
    --qsys-generate "${QSYS_GENERATE_BIN}"
  )
  [[ -f "${VERSION_FILE}" ]] && manifest_args+=(--quartus-version-file "${VERSION_FILE}")
  [[ -f "${READBACK_FILE}" ]] && manifest_args+=(--readback-tsv "${READBACK_FILE}")
  if [[ "${EFFECTIVE_MODE}" == "generate" || "${EFFECTIVE_MODE}" == "construct+generate" ]]; then
    manifest_args+=(--require-generated)
  fi
  run_check "${manifest_args[@]}"
else
  say "DRY-RUN: would write and validate ${MANIFEST_FILE}"
fi

for output in "${SYSTEM_QSYS}" "${SOPCINFO_FILE}" "${QIP_FILE}" "${HDL_V_FILE}" "${HDL_SV_FILE}"; do
  if [[ -f "${output}" ]]; then say "generate_system: output present ${output}"; fi
done
say "generate_system: OK ${EFFECTIVE_MODE}"
