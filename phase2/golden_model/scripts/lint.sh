#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Repository hygiene checks that do not require pre-existing generated artifacts.

set -Eeuo pipefail
IFS=$'\n\t'

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null 2>&1 && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
include_cpp=0

usage() {
  cat <<USAGE
Usage: scripts/lint.sh [--include-cpp]

Runs layout/schema/config/Python/shell hygiene checks. By default it avoids a
full C++ build. Use --include-cpp for a CMake configure/build/CTest pass.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --include-cpp) include_cpp=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "${repo_root}"

make check-layout
make check-schemas

PYTHONPATH=python "${PYTHON_BIN}" - <<'PY'
from pathlib import Path
from trecap_golden.contracts.schema_loader import schema_inventory
assert len(schema_inventory()) >= 8
for path in [
    Path("configs/suites/smoke.json"),
    Path("configs/releases/phase2_revJ_dev.json"),
    Path("tests/golden_selfcheck/smoke_suite_expected_manifest.json"),
    Path("spec/generated"),
    Path("python/trecap_golden/generated"),
]:
    assert path.exists(), path
print("python contract import: OK; generated directories are present")
PY

"${PYTHON_BIN}" -m py_compile tools/*.py python/trecap_golden/**/*.py tests/python/test_*.py
for sh_file in scripts/*.sh; do
  [[ -e "${sh_file}" ]] || continue
  bash -n "${sh_file}"
done

if [[ "${include_cpp}" -eq 1 ]]; then
  build_dir="${BUILD_DIR:-build/lint}"
  cmake -S . -B "${build_dir}" -DTRECAP_BUILD_TESTS=ON -DTRECAP_BUILD_TOOLS=ON -DTRECAP_ENABLE_WARNINGS_AS_ERRORS=ON
  cmake --build "${build_dir}" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
  ctest --test-dir "${build_dir}" --output-on-failure
fi

echo "[lint] OK"
