#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Bootstrap the T-RECAP golden repository without generating signoff artifacts.

set -Eeuo pipefail
IFS=$'\n\t'

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null 2>&1 && pwd)"

PYTHON_BIN="${PYTHON:-python3}"
PIP_BIN="${PIP:-${PYTHON_BIN} -m pip}"
CMAKE_BIN="${CMAKE:-cmake}"
BUILD_DIR="${BUILD_DIR:-build/bootstrap}"
install_python_deps=0
configure_cmake=0

usage() {
  cat <<USAGE
Usage: scripts/bootstrap.sh [--install-python-deps] [--configure-cmake]

Creates/validates the standard repository skeleton and checks that the Python
package can import. This script does not generate artifacts under artifacts/.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-python-deps) install_python_deps=1 ;;
    --configure-cmake) configure_cmake=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "${repo_root}"

echo "[bootstrap] repo root: ${repo_root}"
"${PYTHON_BIN}" --version

if [[ "${install_python_deps}" -eq 1 ]]; then
  echo "[bootstrap] installing Python dependencies from requirements.lock"
  ${PIP_BIN} install -r requirements.lock
fi

echo "[bootstrap] creating missing skeleton directories"
make bootstrap-tree >/dev/null

echo "[bootstrap] checking layout and schemas"
make check-layout
make check-schemas

echo "[bootstrap] checking Python package imports"
PYTHONPATH=python "${PYTHON_BIN}" - <<'PY'
from pathlib import Path
import trecap_golden
from trecap_golden.contracts.contract_paths import find_repo_root
assert Path("spec/generated").is_dir()
assert Path("python/trecap_golden/generated").is_dir()
print("python package: OK", trecap_golden.__version__, find_repo_root())
print("generated directories: present, contents generated later")
PY

if [[ "${configure_cmake}" -eq 1 ]]; then
  echo "[bootstrap] configuring CMake at ${BUILD_DIR}"
  "${CMAKE_BIN}" -S . -B "${BUILD_DIR}" -DTRECAP_BUILD_TESTS=OFF -DTRECAP_BUILD_TOOLS=ON
fi

echo "[bootstrap] OK"
