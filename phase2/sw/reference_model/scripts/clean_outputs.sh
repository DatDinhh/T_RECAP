#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Remove generated local outputs while preserving the repository skeleton.

set -Eeuo pipefail
IFS=$'\n\t'

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null 2>&1 && pwd)"
clean_artifacts=0
clean_caches=0

usage() {
  cat <<USAGE
Usage: scripts/clean_outputs.sh [--artifacts] [--caches] [--all]

Default: remove build/, out/, and runs/ contents.
--artifacts: also remove generated artifacts under artifacts/ while keeping .gitkeep skeletons.
--caches: remove common Python/tool caches.
--all: enable --artifacts and --caches.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifacts) clean_artifacts=1 ;;
    --caches) clean_caches=1 ;;
    --all) clean_artifacts=1; clean_caches=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "${repo_root}"

rm -rf -- build build_* .cache
mkdir -p out runs
find out runs -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
touch out/.gitkeep runs/.gitkeep

if [[ "${clean_artifacts}" -eq 1 ]]; then
  for d in artifacts artifacts/coefficients artifacts/test_vectors artifacts/golden artifacts/manifests artifacts/telemetry_captures; do
    mkdir -p "${d}"
  done
  for d in artifacts/coefficients artifacts/test_vectors artifacts/golden artifacts/manifests artifacts/telemetry_captures; do
    find "${d}" -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
    touch "${d}/.gitkeep"
  done
  find artifacts -mindepth 1 -maxdepth 1 -type f ! -name .gitkeep -delete
  touch artifacts/.gitkeep
fi

if [[ "${clean_caches}" -eq 1 ]]; then
  rm -rf -- .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
  find . -type d -name __pycache__ -prune -exec rm -rf {} +
fi

echo "[clean_outputs] OK"
