#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# CI entrypoint for deterministic golden-model repository checks.

set -Eeuo pipefail
IFS=$'\n\t'

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null 2>&1 && pwd)"
mode="${1:-quick}"
if [[ $# -gt 0 ]]; then shift; fi

cd "${repo_root}"
export PYTHONPATH="${repo_root}/python${PYTHONPATH:+:${PYTHONPATH}}"

case "${mode}" in
  quick|smoke)
    scripts/lint.sh
    ;;
  python)
    for test_file in tests/python/test_*.py; do
      [[ -e "${test_file}" ]] || continue
      PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest "${test_file}" -q
    done
    ;;
  cpp)
    build_dir="${BUILD_DIR:-build/ci_cpp}"
    cmake -S . -B "${build_dir}" -DTRECAP_BUILD_TESTS=ON -DTRECAP_BUILD_TOOLS=ON -DTRECAP_ENABLE_WARNINGS_AS_ERRORS=ON
    cmake --build "${build_dir}" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
    ctest --test-dir "${build_dir}" --output-on-failure
    ;;
  artifacts)
    scripts/regenerate_all.sh "$@"
    ;;
  reproducible)
    scripts/check_reproducible.sh --quick "$@"
    ;;
  all)
    scripts/lint.sh
    "${BASH_SOURCE[0]}" python
    "${BASH_SOURCE[0]}" cpp
    ;;
  *)
    echo "ERROR: unknown CI mode: ${mode}" >&2
    echo "valid modes: quick, smoke, python, cpp, artifacts, reproducible, all" >&2
    exit 2
    ;;
esac

echo "[ci_entrypoint] ${mode}: OK"
