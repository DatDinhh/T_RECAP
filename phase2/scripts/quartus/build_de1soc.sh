#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 DE1-SoC Quartus build wrapper.
# File class: [1] hand-written repository infrastructure.
#
# This wrapper preserves the repository contract: generated headers and filelists
# are checked before a board build, Quartus paths are not hard-coded, and every
# build emits a run directory with logs and a small manifest. It does not create
# a fake board project; missing Platform Designer/QSF/constraint inputs are real
# build blockers unless explicitly skipped for dry-run inspection.

set -euo pipefail
IFS=$'\n\t'

usage() {
  cat <<'USAGE'
Usage: scripts/quartus/build_de1soc.sh [options]

Options:
  --project PATH        Quartus project base, .qpf path, or .qsf path.
                        Default: platform/de1soc/quartus/trecap_de1soc
  --revision NAME       Quartus revision. Default: basename of --project.
  --top NAME            Expected full-board top. Default: de1_soc_trecap_top
  --profile PATH        Validated runtime/build profile recorded in the manifest.
                        Default: config/profiles/de1soc_bram_replay.json
  --run-dir PATH        Build run directory. Default: runs/quartus/de1soc/<timestamp>
  --jobs N             Parallel jobs. Exported as QUARTUS_NUM_PARALLEL_PROCESSORS.
  --clean              Remove Quartus db/output_files under the project before build.
  --collect-only        Do not run Quartus; collect existing output_files into run-dir.
  --skip-contract-checks
                        Skip gen/check filelist/header drift checks.
  --skip-platform-generate
                        Do not generate Platform Designer HDL/IP. Use this after
                        an explicit construct/generate run, such as in CI.
  --allow-missing-constraints
                        Do not fail if constraints/de1soc/*.qsf/*.sdc/Tcl are absent.
  --dry-run            Print commands and checks without changing files or running Quartus.
  -h, --help           Show this help.

Environment overrides:
  QUARTUS_SH           Quartus shell executable. Default: quartus_sh
  PYTHON               Python executable. Default: python3
  MAKE_JOBS            Default parallel job count if --jobs is not supplied.
USAGE
}

QUARTUS_SH_BIN="${QUARTUS_SH:-quartus_sh}"
PYTHON_BIN="${PYTHON:-python3}"
PROJECT_IN="platform/de1soc/quartus/trecap_de1soc"
REVISION=""
TOP_NAME="de1_soc_trecap_top"
PROFILE="config/profiles/de1soc_bram_replay.json"
RUN_DIR=""
JOBS="${MAKE_JOBS:-}"
CLEAN=0
COLLECT_ONLY=0
SKIP_CONTRACTS=0
SKIP_PLATFORM_GENERATE=0
ALLOW_MISSING_CONSTRAINTS=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT_IN="${2:?missing value for --project}"; shift ;;
    --revision) REVISION="${2:?missing value for --revision}"; shift ;;
    --top) TOP_NAME="${2:?missing value for --top}"; shift ;;
    --profile) PROFILE="${2:?missing value for --profile}"; shift ;;
    --run-dir) RUN_DIR="${2:?missing value for --run-dir}"; shift ;;
    --jobs) JOBS="${2:?missing value for --jobs}"; shift ;;
    --clean) CLEAN=1 ;;
    --collect-only) COLLECT_ONLY=1 ;;
    --skip-contract-checks) SKIP_CONTRACTS=1 ;;
    --skip-platform-generate) SKIP_PLATFORM_GENERATE=1 ;;
    --allow-missing-constraints) ALLOW_MISSING_CONSTRAINTS=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [[ ! -f Makefile || ! -d rtl || ! -d filelists || ! -d platform/de1soc ]]; then
  echo "ERROR: ${repo_root} does not look like the T_RECAP_Phase2 repository root" >&2
  exit 2
fi

if [[ -z "${RUN_DIR}" ]]; then
  RUN_DIR="runs/quartus/de1soc/$(date -u +%Y%m%dT%H%M%SZ)"
fi

say_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
}

run_cmd() {
  say_cmd "$@"
  if [[ ${DRY_RUN} -eq 0 ]]; then
    "$@"
  fi
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

warn() {
  echo "warning: $*" >&2
}

project_path="${PROJECT_IN}"
case "${project_path}" in
  *.qpf|*.qsf) project_base="${project_path%.*}" ;;
  *) project_base="${project_path}" ;;
esac
project_dir="$(dirname "${project_base}")"
project_name="$(basename "${project_base}")"
[[ -n "${REVISION}" ]] || REVISION="${project_name}"

if [[ "${project_base}" == legacy/* || "${project_base}" == */legacy/* ]]; then
  fail "refusing to build a Quartus project under legacy/: ${project_base}"
fi

[[ -f scripts/check_profiles.py ]] || fail "profile validator is missing: scripts/check_profiles.py"
profile_check=(
  "${PYTHON_BIN}"
  scripts/check_profiles.py
  --profile "${PROFILE}"
  --require-build
  --expect-target de1soc_full
  --expect-top "${TOP_NAME}"
  --expect-platform de1soc
  --expect-project "${project_base}"
  --quiet
)
say_cmd "${profile_check[@]}"
"${profile_check[@]}"
profile_input_kind="$("${PYTHON_BIN}" -c \
  'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["input"]["kind"])' \
  "${PROFILE}")"

mkdir -p "${RUN_DIR}"
log_file="${RUN_DIR}/quartus_build.log"
manifest_file="${RUN_DIR}/build_manifest.json"
artifacts_dir="${RUN_DIR}/artifacts"
mkdir -p "${artifacts_dir}"

{
  echo "build_de1soc: repository root ${repo_root}"
  echo "build_de1soc: project_base ${project_base}"
  echo "build_de1soc: revision ${REVISION}"
  echo "build_de1soc: top ${TOP_NAME}"
  echo "build_de1soc: profile ${PROFILE}"
  echo "build_de1soc: profile_input_kind ${profile_input_kind}"
  echo "build_de1soc: run_dir ${RUN_DIR}"
} | tee "${log_file}"

if [[ ${SKIP_CONTRACTS} -eq 0 ]]; then
  run_cmd "${PYTHON_BIN}" scripts/gen_headers.py --check --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/gen_filelists.py --check --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_generated.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_hps_platform.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_address_map.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_csr_adapter.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_platform_designer_wrapper.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_source_core_integration.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_core_telemetry_composition.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_de1soc_board_top.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_de1soc_clock_reset.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/check_de1soc_audio_path.py --quiet | tee -a "${log_file}"
  run_cmd "${PYTHON_BIN}" scripts/sim/check_step16_audio_model.py | tee -a "${log_file}"
  if [[ "${profile_input_kind}" == "adc_live" ]]; then
    run_cmd "${PYTHON_BIN}" scripts/check_de1soc_adc_path.py --quiet | tee -a "${log_file}"
    run_cmd "${PYTHON_BIN}" scripts/sim/check_step17_adc_model.py | tee -a "${log_file}"
  fi
fi

required_files=(
  filelists/quartus_de1soc.qsf.inc
  filelists/rtl_de1soc_full.f
  rtl/top/trecap_de1soc_full_top.sv
  rtl/top/trecap_source_core_integration.sv
  rtl/platform/de1soc/de1_soc_trecap_top.sv
  rtl/platform/de1soc/platform_designer_wrapper.sv
  rtl/platform/de1soc/audio_pll_wrapper.sv
  rtl/platform/de1soc/audio_codec_i2c_init.sv
  rtl/platform/de1soc/audio_codec_wrapper.sv
  rtl/platform/de1soc/adc_wrapper.sv
  rtl/hps_bridge/trecap_avmm_csr_adapter.sv
  config/boards/de1soc_clock_reset_architecture.json
  spec/schemas/de1soc_clock_reset_architecture.schema.json
  scripts/check_de1soc_clock_reset.py
  config/boards/de1soc_audio_linein.json
  spec/schemas/de1soc_audio_linein.schema.json
  config/profiles/de1soc_linein_demo.json
  scripts/check_de1soc_audio_path.py
  scripts/sim/check_step16_audio_model.py
)
if [[ "${profile_input_kind}" == "adc_live" ]]; then
  required_files+=(
    config/boards/de1soc_adc_live.json
    spec/schemas/de1soc_adc_live.schema.json
    scripts/check_de1soc_adc_path.py
    scripts/sim/check_step17_adc_model.py
  )
fi
for f in "${required_files[@]}"; do
  if [[ ! -f "${f}" ]]; then
    if [[ ${DRY_RUN} -eq 1 ]]; then
      warn "required build input missing: ${f}"
    else
      fail "required build input missing: ${f}"
    fi
  fi
done

constraint_files=(
  constraints/de1soc/de1soc.qsf
  constraints/de1soc/de1soc.sdc
  constraints/de1soc/clocks.sdc
  constraints/de1soc/pin_assignments.tcl
)
missing_constraints=()
for f in "${constraint_files[@]}"; do
  [[ -f "${f}" ]] || missing_constraints+=("${f}")
done
if [[ ${#missing_constraints[@]} -gt 0 ]]; then
  if [[ ${ALLOW_MISSING_CONSTRAINTS} -eq 1 || ${DRY_RUN} -eq 1 ]]; then
    warn "missing constraint inputs: ${missing_constraints[*]}"
  else
    fail "missing constraint inputs: ${missing_constraints[*]}"
  fi
fi

if [[ ! -d "${project_dir}" ]]; then
  if [[ ${DRY_RUN} -eq 1 ]]; then
    warn "project directory does not exist yet: ${project_dir}"
  else
    fail "project directory does not exist: ${project_dir}"
  fi
fi

if [[ ! -f "${project_base}.qpf" && ! -f "${project_base}.qsf" ]]; then
  if [[ ${DRY_RUN} -eq 1 || ${COLLECT_ONLY} -eq 1 ]]; then
    warn "Quartus project files not found: ${project_base}.qpf / ${project_base}.qsf"
  else
    fail "Quartus project files not found: ${project_base}.qpf / ${project_base}.qsf"
  fi
fi

if [[ ${SKIP_PLATFORM_GENERATE} -eq 0 ]]; then
  platform_generator="platform/de1soc/qsys/generate_system.sh"
  [[ -x "${platform_generator}" ]] || fail "Platform Designer generator is missing or not executable: ${platform_generator}"
  platform_generate_args=(
    "${platform_generator}"
    --mode generate
    --run-dir "${RUN_DIR}/platform-designer"
  )
  if [[ ${DRY_RUN} -eq 1 ]]; then
    platform_generate_args+=(--dry-run)
  fi
  if [[ ${SKIP_CONTRACTS} -eq 1 ]]; then
    platform_generate_args+=(--skip-contract-checks)
  fi
  say_cmd "${platform_generate_args[@]}" | tee -a "${log_file}"
  "${platform_generate_args[@]}" 2>&1 | tee -a "${log_file}"
fi

platform_generated_required=(
  platform/de1soc/qsys/system.sopcinfo
  platform/de1soc/qsys/system/synthesis/system.qip
)
for generated_input in "${platform_generated_required[@]}"; do
  if [[ ! -f "${generated_input}" ]]; then
    if [[ ${DRY_RUN} -eq 1 ]]; then
      warn "mandatory generated Platform Designer input not present in dry-run: ${generated_input}"
    else
      fail "mandatory generated Platform Designer input missing: ${generated_input}"
    fi
  fi
done
if [[ ! -f platform/de1soc/qsys/system/synthesis/system.v && \
      ! -f platform/de1soc/qsys/system/synthesis/system.sv ]]; then
  if [[ ${DRY_RUN} -eq 1 ]]; then
    warn "mandatory generated Platform Designer HDL not present in dry-run: system.v/system.sv"
  else
    fail "mandatory generated Platform Designer HDL missing: system/synthesis/system.v or system.sv"
  fi
fi

# A real board build may proceed only when the expected generated SOPCINFO,
# flattened wrapper ABI, and normalized Qsys identities are present. These gates
# do not by themselves prove hardware CSR reachability, Linux DDR reservation,
# or physical-board behavior. A dry-run prints them because vendor outputs are
# absent from source.
if [[ ${SKIP_CONTRACTS} -eq 0 ]]; then
  address_evidence_check=(
    "${PYTHON_BIN}"
    scripts/check_address_map.py
    --require-sopcinfo
    --quiet
  )
  wrapper_evidence_check=(
    "${PYTHON_BIN}"
    scripts/check_platform_designer_wrapper.py
    --require-generated
    --quiet
  )
  if [[ ${DRY_RUN} -eq 1 ]]; then
    say_cmd "${address_evidence_check[@]}" | tee -a "${log_file}"
    say_cmd "${wrapper_evidence_check[@]}" | tee -a "${log_file}"
  else
    "${address_evidence_check[@]}" 2>&1 | tee -a "${log_file}"
    "${wrapper_evidence_check[@]}" 2>&1 | tee -a "${log_file}"
  fi
fi

if [[ ${CLEAN} -eq 1 ]]; then
  for target in "${project_dir}/db" "${project_dir}/incremental_db" "${project_dir}/output_files"; do
    if [[ ${DRY_RUN} -eq 1 ]]; then
      echo "DRY-RUN rm -rf -- ${target}" | tee -a "${log_file}"
    else
      rm -rf -- "${target}"
    fi
  done
fi

if [[ ${COLLECT_ONLY} -eq 0 ]]; then
  if [[ ${DRY_RUN} -eq 1 ]]; then
    say_cmd env QUARTUS_NUM_PARALLEL_PROCESSORS="${JOBS:-}" "${QUARTUS_SH_BIN}" --flow compile "${project_name}" -c "${REVISION}" | tee -a "${log_file}"
  else
    if ! command -v "${QUARTUS_SH_BIN}" >/dev/null 2>&1; then
      fail "${QUARTUS_SH_BIN} not found in PATH. Set QUARTUS_SH or source the Intel FPGA environment."
    fi
    (
      cd "${project_dir}"
      if [[ -n "${JOBS}" ]]; then
        export QUARTUS_NUM_PARALLEL_PROCESSORS="${JOBS}"
      fi
      set -o pipefail
      "${QUARTUS_SH_BIN}" --flow compile "${project_name}" -c "${REVISION}" 2>&1 | tee -a "${repo_root}/${log_file}"
    )
  fi
fi

collect_paths=()
for d in "${project_dir}/output_files" "${project_dir}" output_files; do
  [[ -d "${d}" ]] && collect_paths+=("${d}")
done
if [[ ${DRY_RUN} -eq 0 && ${#collect_paths[@]} -gt 0 ]]; then
  while IFS= read -r -d '' f; do
    cp -a "${f}" "${artifacts_dir}/"
  done < <(find "${collect_paths[@]}" -maxdepth 1 -type f \
    \( -name '*.sof' -o -name '*.pof' -o -name '*.rpt' -o -name '*.summary' -o -name '*.pin' -o -name '*.smsg' -o -name '*.sta.rpt' -o -name '*.fit.rpt' -o -name '*.map.rpt' -o -name '*.asm.rpt' -o -name '*.flow.rpt' \) -print0 2>/dev/null || true)
fi

if [[ ${DRY_RUN} -eq 0 ]]; then
  export TRECAP_RUN_DIR="${RUN_DIR}"
  export TRECAP_PROJECT_BASE="${project_base}"
  export TRECAP_PROJECT_REVISION="${REVISION}"
  export TRECAP_TOP_NAME="${TOP_NAME}"
  export TRECAP_PROFILE="${PROFILE}"
  export TRECAP_LOG_FILE="${log_file}"
  "${PYTHON_BIN}" - <<'PY'
from __future__ import annotations
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

run_dir = Path(os.environ["TRECAP_RUN_DIR"])
artifacts = run_dir / "artifacts"
files = []
for path in sorted(artifacts.glob("*")):
    if path.is_file():
        files.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
try:
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
except Exception:
    git_commit = None
manifest = {
    "schema": "trecap_phase2_quartus_build_manifest_v1",
    "file_class": "[2] generated build-run manifest - do not edit by hand",
    "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "project_base": os.environ["TRECAP_PROJECT_BASE"],
    "revision": os.environ["TRECAP_PROJECT_REVISION"],
    "top": os.environ["TRECAP_TOP_NAME"],
    "profile": os.environ["TRECAP_PROFILE"],
    "log_file": os.environ["TRECAP_LOG_FILE"],
    "git_commit": git_commit,
    "artifacts": files,
}
profile_path = Path(os.environ["TRECAP_PROFILE"])
profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
manifest["profile_sha256"] = hashlib.sha256(profile_path.read_bytes()).hexdigest()
manifest["profile_name"] = profile_data["profile_name"]
manifest["profile_kind"] = profile_data["profile_kind"]
manifest["telemetry_profile"] = profile_data.get("telemetry_profile")
if manifest["telemetry_profile"] is not None:
    telemetry_profile_path = Path(manifest["telemetry_profile"])
    manifest["telemetry_profile_sha256"] = hashlib.sha256(
        telemetry_profile_path.read_bytes()
    ).hexdigest()
else:
    manifest["telemetry_profile_sha256"] = None
address_path = Path("platform/de1soc/address_map/hps_bridge_regions.json")
address_data = json.loads(address_path.read_text(encoding="utf-8"))
freeze = address_data["address_map_freeze"]
manifest["address_map_contract"] = {
    "path": address_path.as_posix(),
    "file_sha256": hashlib.sha256(address_path.read_bytes()).hexdigest(),
    "schema": address_data["schema"],
    "contract_stage": address_data["contract_stage"],
    "status": address_data["status"],
    "freeze_revision": freeze["revision"],
    "canonical_sha256": freeze["canonical_sha256"],
    "hardware_signoff": freeze["hardware_signoff"],
    "pinned_source_sha256": freeze["pinned_source_sha256"],
}
(run_dir / "build_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
else
  echo "DRY-RUN would write ${manifest_file}" | tee -a "${log_file}"
fi

echo "build_de1soc: OK run_dir=${RUN_DIR}" | tee -a "${log_file}"
