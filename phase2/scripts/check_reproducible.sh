#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Check smoke-suite reproducibility and selfcheck expectations.

set -Eeuo pipefail
IFS=$'\n\t'

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null 2>&1 && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
CMAKE_BIN="${CMAKE:-cmake}"
BUILD_DIR="${BUILD_DIR:-build/repro}"
SUITE_PATH="${SUITE:-configs/suites/smoke.json}"
RELEASE_CONFIG_PATH="${RELEASE_CONFIG:-configs/releases/phase2_revJ_dev.json}"
EXPECTED_MANIFEST="${EXPECTED_MANIFEST:-tests/golden_selfcheck/smoke_suite_expected_manifest.json}"
keep_tmp=0
quick=0
compare_current=0

usage() {
  cat <<USAGE
Usage: scripts/check_reproducible.sh [--quick] [--suite PATH] [--release-config PATH] [--expected PATH] [--keep-tmp] [--compare-current]

--quick            Validate configs and golden_selfcheck expectations only. No artifact generation.
--compare-current  Also compare a regenerated temporary artifact tree against current artifacts/.
                   Requires artifacts/ to already contain generated payloads.

Default full mode regenerates two temporary artifact trees and compares them while ignoring volatile JSON metadata.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) quick=1 ;;
    --suite) SUITE_PATH="$2"; shift ;;
    --release-config) RELEASE_CONFIG_PATH="$2"; shift ;;
    --expected) EXPECTED_MANIFEST="$2"; shift ;;
    --keep-tmp) keep_tmp=1 ;;
    --compare-current) compare_current=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "${repo_root}"
export PYTHONPATH="${repo_root}/python${PYTHONPATH:+:${PYTHONPATH}}"

"${PYTHON_BIN}" - <<'PY' "${EXPECTED_MANIFEST}" "${SUITE_PATH}"
import json
import sys
from pathlib import Path
expected = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
suite = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if expected.get("generated") is not False:
    raise SystemExit("selfcheck manifest must be hand-reviewed, not generated")
exp_names = [v["name"] for v in expected["vector_expectations"]]
suite_names = [v["name"] for v in suite["vector_selection"]]
if exp_names != suite_names:
    raise SystemExit(f"smoke suite drift: expected {exp_names}, got {suite_names}")
core = expected["core_config"]
if core["D"] != core["L"] + core["G"]:
    raise SystemExit("selfcheck manifest invalid: D != L + G")
for v in expected["vector_expectations"]:
    frames = (int(v["Ns"]) + core["L"] - 2) // core["H"]
    ny = frames * core["H"] + core["G"] + core["L"]
    if int(v["frames"]) != frames or int(v["Ny"]) != ny:
        raise SystemExit(f"bad full_tail geometry for {v['name']}")
    if int(v["x_in_rows"]) != int(v["Ns"]):
        raise SystemExit(f"bad x_in row count for {v['name']}")
    if int(v["y_out_rows"]) != ny:
        raise SystemExit(f"bad y_out row count for {v['name']}")
print("selfcheck manifest: OK")
PY

make check-layout
make check-schemas

if [[ "${quick}" -eq 1 ]]; then
  echo "[check_reproducible] quick OK"
  exit 0
fi

make check-vector-configs
make check-suite-configs
make check-release-configs
make python-test
"${CMAKE_BIN}" -S . -B "${BUILD_DIR}" -DTRECAP_BUILD_TOOLS=ON -DTRECAP_BUILD_TESTS=OFF -DTRECAP_ENABLE_WARNINGS_AS_ERRORS=ON
"${CMAKE_BIN}" --build "${BUILD_DIR}" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-2}"

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/trecap_repro.XXXXXX")"
trap 'if [[ "${keep_tmp}" -eq 0 ]]; then rm -rf -- "${tmp_root}"; else echo "[check_reproducible] kept ${tmp_root}"; fi' EXIT

run_once() {
  local tag="$1"
  local art="${tmp_root}/${tag}/artifacts"
  mkdir -p "${art}/coefficients" "${art}/test_vectors" "${art}/golden" "${art}/manifests"
  "${PYTHON_BIN}" -m trecap_golden.cli.gen_coeffs --out "${art}/coefficients"
  "${PYTHON_BIN}" -m trecap_golden.cli.gen_vectors --configs configs/vectors --out "${art}/test_vectors" --coefficients "${art}/coefficients" --suite "${SUITE_PATH}"
  "${PYTHON_BIN}" -m trecap_golden.cli.run_suite --vectors "${art}/test_vectors" --out "${art}/golden" --golden-exe "${BUILD_DIR}/phase2_golden_model" --suite "${SUITE_PATH}"
  "${PYTHON_BIN}" tools/make_quality_bounds.py --artifacts "${art}" --out "${art}/manifests/quality_bounds.json"
  "${PYTHON_BIN}" tools/freeze_release.py --release-config "${RELEASE_CONFIG_PATH}" --artifacts "${art}" --out "${art}/manifests/frozen_release_manifest.json"
  "${PYTHON_BIN}" tools/artifact_check.py --artifacts "${art}"
}

run_once a
run_once b
"${PYTHON_BIN}" tools/compare_artifacts.py --left "${tmp_root}/a/artifacts" --right "${tmp_root}/b/artifacts" --ignore-volatile
if [[ "${compare_current}" -eq 1 ]]; then
  if [[ ! -f artifacts/coefficients/coeff_manifest.json || ! -f artifacts/test_vectors/test_vectors.json ]]; then
    echo "ERROR: current artifacts/ tree is incomplete. Run scripts/regenerate_all.sh first." >&2
    exit 2
  fi
  "${PYTHON_BIN}" tools/compare_artifacts.py --left artifacts --right "${tmp_root}/a/artifacts" --ignore-volatile
fi

echo "[check_reproducible] full OK"
