#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Format or check formatting for Python, C++, shell, and metadata files.

set -Eeuo pipefail
IFS=$'\n\t'

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null 2>&1 && pwd)"
check_only=0
strict_tools="${STRICT_FORMAT_TOOLS:-0}"

usage() {
  cat <<USAGE
Usage: scripts/format.sh [--check]

Without --check, applies available formatters. With --check, verifies formatting.
Set STRICT_FORMAT_TOOLS=1 to fail when optional formatters are missing.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) check_only=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "${repo_root}"

missing_tool() {
  local tool="$1"
  if [[ "${strict_tools}" == "1" ]]; then
    echo "ERROR: required formatter missing: ${tool}" >&2
    exit 2
  fi
  echo "[format] ${tool} not found; skipping" >&2
}

if command -v ruff >/dev/null 2>&1; then
  if [[ "${check_only}" -eq 1 ]]; then
    ruff check python tools scripts tests/python
  else
    ruff check --fix python tools scripts tests/python
  fi
else
  missing_tool ruff
fi

if command -v black >/dev/null 2>&1; then
  if [[ "${check_only}" -eq 1 ]]; then
    black --check python tools scripts tests/python
  else
    black python tools scripts tests/python
  fi
else
  missing_tool black
fi

if command -v clang-format >/dev/null 2>&1; then
  mapfile -t cpp_files < <(find include src tools tests/cpp -type f \( -name '*.hpp' -o -name '*.cpp' -o -name '*.h' -o -name '*.cc' \) | sort)
  if [[ ${#cpp_files[@]} -gt 0 ]]; then
    if [[ "${check_only}" -eq 1 ]]; then
      clang-format --dry-run --Werror "${cpp_files[@]}"
    else
      clang-format -i "${cpp_files[@]}"
    fi
  fi
else
  missing_tool clang-format
fi

for sh_file in scripts/*.sh; do
  [[ -e "${sh_file}" ]] || continue
  bash -n "${sh_file}"
done

echo "[format] OK"
