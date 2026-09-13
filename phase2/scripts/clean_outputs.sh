#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 source-preserving cleanup helper.
# File class: [1] hand-written repository infrastructure.
#
# This script removes local build/run/simulator/tool scratch output. It does not
# remove spec/generated contracts, generated headers, generated filelists,
# coefficient/vector/reference artifacts, or source files.

set -euo pipefail
IFS=$'\n\t'

usage() {
  cat <<'EOF'
Usage: scripts/clean_outputs.sh [options]

Options:
  --dry-run       Print what would be removed without deleting anything.
  --dist          Also remove Quartus/Platform Designer scratch directories.
  --captures      Remove artifacts/telemetry_captures contents except .gitkeep.
  --packages      Remove package outputs under out/artifacts as well.
  --yes           Do not ask before deleting large optional groups.
  -h, --help      Show this help.

Default cleanup is source-preserving and removes only local outputs such as
build/, out/tmp/, out/logs/, runs/*, simulator waves/logs, Python caches,
CMake scratch, dashboard/matplotlib caches, and common ModelSim/Questa work
libraries.

Preserved by design:
  spec/generated/*.json
  spec/schemas/*.json
  rtl/include/generated/*.sv
  sw/hps/include/generated/*.h
  sw/pc_dashboard/generated/*.py
  sw/reference_model/generated/*.py
  filelists/*.f and filelists/*.inc
  artifacts/coefficients, artifacts/test_vectors, artifacts/reference_outputs,
  artifacts/manifests, and source documentation.
EOF
}

DRY_RUN=0
DIST=0
CAPTURES=0
PACKAGES=0
YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --dist) DIST=1 ;;
    --captures) CAPTURES=1 ;;
    --packages) PACKAGES=1 ;;
    --yes) YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if [[ ! -f Makefile || ! -d spec/generated || ! -d rtl ]]; then
  echo "ERROR: ${repo_root} does not look like the T_RECAP_Phase2 repository root" >&2
  exit 2
fi
if [[ "${repo_root}" == "/" ]]; then
  echo "ERROR: refusing to clean filesystem root" >&2
  exit 2
fi

say_rm() {
  local target="$1"
  if [[ ${DRY_RUN} -eq 1 ]]; then
    echo "DRY-RUN rm -rf -- ${target}"
  else
    rm -rf -- "${target}"
  fi
}

confirm() {
  local prompt="$1"
  if [[ ${YES} -eq 1 || ${DRY_RUN} -eq 1 ]]; then
    return 0
  fi
  local answer
  read -r -p "${prompt} Type 'yes': " answer
  [[ "${answer}" == "yes" ]]
}

clean_dir_contents_preserve_gitkeep() {
  local dir="$1"
  if [[ ${DRY_RUN} -eq 1 ]]; then
    if [[ ! -d "${dir}" ]]; then
      echo "DRY-RUN mkdir -p -- ${dir}"
      echo "DRY-RUN touch -- ${dir}/.gitkeep"
      return 0
    fi
    find "${dir}" -mindepth 1 ! -name '.gitkeep' -print | sed 's/^/DRY-RUN rm -rf -- /'
  else
    [[ -d "${dir}" ]] || mkdir -p "${dir}"
    find "${dir}" -mindepth 1 ! -name '.gitkeep' -exec rm -rf -- {} + 2>/dev/null || true
    touch "${dir}/.gitkeep"
  fi
}

remove_matches() {
  local label="$1"
  shift
  mapfile -d '' matches < <(find "$@" 2>/dev/null || true)
  if [[ ${#matches[@]} -eq 0 ]]; then
    return 0
  fi
  echo "clean ${label}: ${#matches[@]} path(s)"
  local p
  for p in "${matches[@]}"; do
    # Strip leading ./ for cleaner dry-run output.
    p="${p#./}"
    say_rm "${p}"
  done
}

echo "clean_outputs: repository root ${repo_root}"

# Root-level local build output. Keep out/artifacts unless --packages is set.
for target in build cmake-build-debug cmake-build-release cmake-build-relwithdebinfo; do
  [[ -e "${target}" ]] && say_rm "${target}"
done
for target in out/tmp out/logs out/test out/package_tmp; do
  [[ -e "${target}" ]] && say_rm "${target}"
done
if [[ ${PACKAGES} -eq 1 ]]; then
  [[ -e out/artifacts ]] && say_rm out/artifacts
fi

clean_dir_contents_preserve_gitkeep runs

# Python, test, and dashboard display caches. Do not traverse quarantined
# historical material.
remove_matches "Python/dashboard caches" . \
  -path './.git' -prune -o \
  -path './legacy' -prune -o \
  \( -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.mypy_cache' -o -name '.ruff_cache' -o -name '.dash_cache' -o -name '.matplotlib' -o -name '.mplconfig' \) -o \
     -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.dash_cache' -o -name '.matplotlib' -o -name '.mplconfig' \) \) -print0

# CMake and host-build scratch.
remove_matches "CMake scratch" . \
  -path './.git' -prune -o \
  -path './legacy' -prune -o \
  \( -type d -name 'CMakeFiles' -o \
     -type f \( -name 'CMakeCache.txt' -o -name 'cmake_install.cmake' \) \) -print0

# ModelSim/Questa/Icarus/VCD scratch. Do not touch checked-in filelists or generated headers.
remove_matches "simulator scratch" . \
  -path './.git' -prune -o \
  -path './legacy' -prune -o \
  \( -type d \( -name 'work' -o -name 'audio_work' -o -name 'adc_work' \) -o \
     -type f \( -name 'transcript' -o -name 'vsim.wlf' -o -name '*.wlf' -o -name '*.vcd' -o -name '*.fst' -o -name '*.ghw' -o -name '*.ucdb' -o -name '*.vvp' -o -name 'simv' -o -name 'modelsim.ini' \) \) -print0

if [[ ${CAPTURES} -eq 1 ]]; then
  if confirm "Remove artifacts/telemetry_captures contents?"; then
    clean_dir_contents_preserve_gitkeep artifacts/telemetry_captures
  else
    echo "skipped telemetry captures"
  fi
fi

if [[ ${DIST} -eq 1 ]]; then
  if confirm "Remove Quartus/Platform Designer scratch outputs?"; then
    for target in db incremental_db output_files qdb simulation hps_isw_handoff; do
      [[ -e "${target}" ]] && say_rm "${target}"
    done
    remove_matches "Quartus/Platform Designer scratch" . \
      -path './.git' -prune -o \
      -path './legacy' -prune -o \
      \( -type d \( -name 'incremental_db' -o -name 'db' -o -name 'output_files' -o -name 'qdb' -o -name 'greybox_tmp' -o -name 'synthesis' -o -name 'simulation' -o -name 'testbench' -o -name 'submodules' \) -o \
         -type f \( -name '*.qar' -o -name '*.rpt' -o -name '*.summary' -o -name '*.jdi' -o -name '*.pin' -o -name '*.sof' -o -name '*.pof' -o -name '*.smsg' -o -name '*.qws' \) \) -print0
  else
    echo "skipped --dist cleanup"
  fi
fi

# Preserve only the repository-owned runs placeholder. Telemetry captures are a
# structural empty directory in architecture snapshots; adding a placeholder
# there would be an untracked promoted artifact and make the provenance gate fail.
if [[ ${DRY_RUN} -eq 1 ]]; then
  [[ -d runs ]] || echo "DRY-RUN mkdir -p -- runs"
  [[ -d artifacts/telemetry_captures ]] || \
    echo "DRY-RUN mkdir -p -- artifacts/telemetry_captures"
  [[ -f runs/.gitkeep ]] || echo "DRY-RUN touch -- runs/.gitkeep"
  [[ ! -f artifacts/telemetry_captures/.gitkeep ]] || \
    echo "DRY-RUN rm -f -- artifacts/telemetry_captures/.gitkeep"
else
  mkdir -p runs artifacts/telemetry_captures
  [[ -f runs/.gitkeep ]] || touch runs/.gitkeep
  [[ ! -f artifacts/telemetry_captures/.gitkeep ]] || \
    rm -f -- artifacts/telemetry_captures/.gitkeep
fi

echo "clean_outputs: OK"
