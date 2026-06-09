#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Regenerate the artifact tree from reviewed configs and the compiled golden model.

set -Eeuo pipefail
IFS=$'\n\t'

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null 2>&1 && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
CMAKE_BIN="${CMAKE:-cmake}"
BUILD_DIR="${BUILD_DIR:-build/release}"
SUITE_PATH="${SUITE:-configs/suites/smoke.json}"
RELEASE_CONFIG_PATH="${RELEASE_CONFIG:-configs/releases/phase2_revJ_dev.json}"
clean_first=0
skip_build=0

usage() {
  cat <<USAGE
Usage: scripts/regenerate_all.sh [--suite PATH] [--release-config PATH] [--clean-first] [--skip-build]

Regenerates coefficients, vectors, golden outputs, quality bounds, and release manifests.
This script writes generated payloads under artifacts/.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite) SUITE_PATH="$2"; shift ;;
    --release-config) RELEASE_CONFIG_PATH="$2"; shift ;;
    --clean-first) clean_first=1 ;;
    --skip-build) skip_build=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "${repo_root}"
export PYTHONPATH="${repo_root}/python${PYTHONPATH:+:${PYTHONPATH}}"

if [[ "${clean_first}" -eq 1 ]]; then
  scripts/clean_outputs.sh --artifacts
fi

if [[ "${skip_build}" -eq 0 ]]; then
  "${CMAKE_BIN}" -S . -B "${BUILD_DIR}" -DTRECAP_BUILD_TOOLS=ON -DTRECAP_BUILD_TESTS=OFF -DTRECAP_ENABLE_WARNINGS_AS_ERRORS=ON
  "${CMAKE_BIN}" --build "${BUILD_DIR}" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
fi

golden_exe="${BUILD_DIR}/phase2_golden_model"
if [[ ! -x "${golden_exe}" ]]; then
  echo "ERROR: golden executable missing: ${golden_exe}" >&2
  exit 2
fi

"${PYTHON_BIN}" -m trecap_golden.cli.gen_coeffs --out artifacts/coefficients
"${PYTHON_BIN}" -m trecap_golden.cli.gen_vectors --configs configs/vectors --out artifacts/test_vectors --coefficients artifacts/coefficients --suite "${SUITE_PATH}"
"${PYTHON_BIN}" -m trecap_golden.cli.run_suite --vectors artifacts/test_vectors --out artifacts/golden --golden-exe "${golden_exe}" --suite "${SUITE_PATH}"
"${PYTHON_BIN}" tools/make_quality_bounds.py --artifacts artifacts --out artifacts/manifests/quality_bounds.json
"${PYTHON_BIN}" -m trecap_golden.cli.freeze_release --release-config "${RELEASE_CONFIG_PATH}" --artifacts artifacts --out artifacts/manifests/frozen_release_manifest.json
"${PYTHON_BIN}" -m trecap_golden.cli.artifact_check --artifacts artifacts

echo "[regenerate_all] OK"
