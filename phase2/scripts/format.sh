#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 source formatter.
# File class: [1] hand-written repository infrastructure.
#
# This script formats only hand-written source files. It deliberately excludes
# generated contracts, generated filelists, frozen/reference artifacts, captures,
# local runs, local build output, and quarantined historical material.

set -euo pipefail
IFS=$'\n\t'

usage() {
  cat <<'USAGE'
Usage: scripts/format.sh [options]

Options:
  --check          Check formatting without modifying files.
  --dry-run        Print actions without modifying files.
  --python-only    Run only Python formatting/checks.
  --c-only         Run only C/C++ formatting/checks.
  --shell-only     Run only shell formatting/checks.
  --sv             Also format hand-written SystemVerilog with clang-format.
                  This is off by default because local clang-format versions
                  differ in SystemVerilog support.
  --all            Same as default plus --sv.
  --verbose        Print selected files.
  -h, --help       Show this help.

Default behavior formats hand-written Python, C/C++, and shell scripts when the
corresponding local tools are installed. Missing optional formatters are reported
and skipped; syntax checks still run where possible.

Generated files are never formatted by this script. Change the schema or the
relevant generator, then regenerate.
USAGE
}

CHECK=0
DRY_RUN=0
PYTHON_ONLY=0
C_ONLY=0
SHELL_ONLY=0
INCLUDE_SV=0
VERBOSE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --python-only) PYTHON_ONLY=1 ;;
    --c-only) C_ONLY=1 ;;
    --shell-only) SHELL_ONLY=1 ;;
    --sv) INCLUDE_SV=1 ;;
    --all) INCLUDE_SV=1 ;;
    --verbose) VERBOSE=1 ;;
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

want_python=1
want_c=1
want_shell=1
if [[ ${PYTHON_ONLY} -eq 1 || ${C_ONLY} -eq 1 || ${SHELL_ONLY} -eq 1 ]]; then
  want_python=${PYTHON_ONLY}
  want_c=${C_ONLY}
  want_shell=${SHELL_ONLY}
fi

say() { printf '%s\n' "$*"; }

run_or_print() {
  if [[ ${DRY_RUN} -eq 1 ]]; then
    printf 'DRY-RUN'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

# Common pruning rule. Keep this conservative: format only active source areas.
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

mapfile -d '' c_files < <(
  find_active_files ./scripts ./sw 2>/dev/null \
    \( -name '*.c' -o -name '*.h' -o -name '*.cc' -o -name '*.cpp' -o -name '*.cxx' -o -name '*.hh' -o -name '*.hpp' -o -name '*.hxx' \) -print0
)

mapfile -d '' sh_files < <(
  find_active_files ./scripts 2>/dev/null \
    \( -name '*.sh' \) -print0
)

mapfile -d '' sv_files < <(
  find_active_files ./rtl ./constraints ./platform 2>/dev/null \
    \( -name '*.sv' -o -name '*.v' -o -name '*.vh' -o -name '*.tcl' \) -print0
)

if [[ ${VERBOSE} -eq 1 ]]; then
  say "format: python files=${#python_files[@]}"
  printf '  %s\n' "${python_files[@]}" || true
  say "format: c/c++ files=${#c_files[@]}"
  printf '  %s\n' "${c_files[@]}" || true
  say "format: shell files=${#sh_files[@]}"
  printf '  %s\n' "${sh_files[@]}" || true
  if [[ ${INCLUDE_SV} -eq 1 ]]; then
    say "format: sv/tcl files=${#sv_files[@]}"
    printf '  %s\n' "${sv_files[@]}" || true
  fi
fi

status=0

if [[ ${want_python} -eq 1 && ${#python_files[@]} -gt 0 ]]; then
  if command -v black >/dev/null 2>&1; then
    if [[ ${CHECK} -eq 1 ]]; then
      run_or_print black --check --diff --line-length 100 "${python_files[@]}" || status=$?
    else
      run_or_print black --line-length 100 "${python_files[@]}" || status=$?
    fi
  else
    say "format: black not found; skipped Python auto-format"
    if [[ ${CHECK} -eq 1 || ${DRY_RUN} -eq 0 ]]; then
      run_or_print python3 -m py_compile "${python_files[@]}" || status=$?
    fi
  fi
fi

clang_check_file() {
  local file="$1"
  local tmp
  tmp="$(mktemp)"
  clang-format --style=file --fallback-style=none "${file}" > "${tmp}"
  if ! cmp -s "${file}" "${tmp}"; then
    echo "format drift: ${file}" >&2
    rm -f "${tmp}"
    return 1
  fi
  rm -f "${tmp}"
}

if [[ ${want_c} -eq 1 && ${#c_files[@]} -gt 0 ]]; then
  if command -v clang-format >/dev/null 2>&1; then
    if [[ ${CHECK} -eq 1 ]]; then
      if [[ ${DRY_RUN} -eq 1 ]]; then
        printf 'DRY-RUN clang-format check'
        printf ' %q' "${c_files[@]}"
        printf '\n'
      else
        for f in "${c_files[@]}"; do clang_check_file "${f}" || status=1; done
      fi
    else
      run_or_print clang-format -i --style=file --fallback-style=none "${c_files[@]}" || status=$?
    fi
  else
    say "format: clang-format not found; skipped C/C++ auto-format"
  fi
fi

if [[ ${INCLUDE_SV} -eq 1 && ${#sv_files[@]} -gt 0 ]]; then
  if command -v clang-format >/dev/null 2>&1; then
    if [[ ${CHECK} -eq 1 ]]; then
      if [[ ${DRY_RUN} -eq 1 ]]; then
        printf 'DRY-RUN clang-format SV/Tcl check'
        printf ' %q' "${sv_files[@]}"
        printf '\n'
      else
        for f in "${sv_files[@]}"; do clang_check_file "${f}" || status=1; done
      fi
    else
      run_or_print clang-format -i --style=file --fallback-style=none "${sv_files[@]}" || status=$?
    fi
  else
    say "format: clang-format not found; skipped SystemVerilog/Tcl auto-format"
  fi
fi

if [[ ${want_shell} -eq 1 && ${#sh_files[@]} -gt 0 ]]; then
  if command -v shfmt >/dev/null 2>&1; then
    if [[ ${CHECK} -eq 1 ]]; then
      run_or_print shfmt -d -i 2 -ci -bn "${sh_files[@]}" || status=$?
    else
      run_or_print shfmt -w -i 2 -ci -bn "${sh_files[@]}" || status=$?
    fi
  else
    say "format: shfmt not found; running bash syntax checks instead"
    for f in "${sh_files[@]}"; do
      run_or_print bash -n "${f}" || status=$?
    done
  fi
fi

if [[ ${status} -ne 0 ]]; then
  echo "format: FAIL" >&2
  exit "${status}"
fi

echo "format: OK"
