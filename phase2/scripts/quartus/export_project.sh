#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 Quartus project export helper.
# File class: [1] hand-written repository infrastructure.
#
# Creates a portable source export for the DE1-SoC Quartus build inputs. This is
# not a Quartus scratch dump, not a verification database, and not a substitute
# for generated-contract drift checks.

set -euo pipefail
IFS=$'\n\t'

usage() {
  cat <<'USAGE'
Usage: scripts/quartus/export_project.sh [options]

Options:
  --project PATH       Quartus project base, .qpf path, or .qsf path.
                       Default: platform/de1soc/quartus/trecap_de1soc
  --revision NAME      Revision name recorded in the export manifest.
  --output PATH        Output .tar.gz. Default:
                       out/quartus_exports/trecap_de1soc_project_<timestamp>.tar.gz
  --include-reference-outputs
                       Include artifacts/reference_outputs in the archive.
  --include-captures   Include artifacts/telemetry_captures in the archive.
  --include-runs       Include runs/quartus summaries. Default is excluded.
  --quartus-archive    Also run quartus_sh --archive when the Quartus project exists.
  --skip-contract-checks
                       Skip generated-header/filelist drift checks.
  --dry-run           Print planned archive contents without creating an archive.
  -h, --help          Show this help.

Environment overrides:
  PYTHON               Python executable. Default: python3
  QUARTUS_SH           Quartus shell executable. Default: quartus_sh
USAGE
}

PYTHON_BIN="${PYTHON:-python3}"
QUARTUS_SH_BIN="${QUARTUS_SH:-quartus_sh}"
PROJECT_IN="platform/de1soc/quartus/trecap_de1soc"
REVISION=""
OUTPUT=""
INCLUDE_REFERENCE_OUTPUTS=0
INCLUDE_CAPTURES=0
INCLUDE_RUNS=0
QUARTUS_ARCHIVE=0
SKIP_CONTRACTS=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT_IN="${2:?missing value for --project}"; shift ;;
    --revision) REVISION="${2:?missing value for --revision}"; shift ;;
    --output) OUTPUT="${2:?missing value for --output}"; shift ;;
    --include-reference-outputs) INCLUDE_REFERENCE_OUTPUTS=1 ;;
    --include-captures) INCLUDE_CAPTURES=1 ;;
    --include-runs) INCLUDE_RUNS=1 ;;
    --quartus-archive) QUARTUS_ARCHIVE=1 ;;
    --skip-contract-checks) SKIP_CONTRACTS=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [[ ! -f Makefile || ! -d rtl || ! -d platform/de1soc ]]; then
  echo "ERROR: ${repo_root} does not look like the T_RECAP_Phase2 repository root" >&2
  exit 2
fi

case "${PROJECT_IN}" in
  *.qpf|*.qsf) project_base="${PROJECT_IN%.*}" ;;
  *) project_base="${PROJECT_IN}" ;;
esac
[[ -n "${REVISION}" ]] || REVISION="$(basename "${project_base}")"

if [[ "${project_base}" == legacy/* || "${project_base}" == */legacy/* ]]; then
  echo "ERROR: refusing to export a Quartus project under legacy/: ${project_base}" >&2
  exit 1
fi

if [[ -z "${OUTPUT}" ]]; then
  OUTPUT="out/quartus_exports/trecap_de1soc_project_$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
fi

say_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
}

if [[ ${SKIP_CONTRACTS} -eq 0 ]]; then
  say_cmd "${PYTHON_BIN}" scripts/check_generated.py --quiet
  if [[ ${DRY_RUN} -eq 0 ]]; then
    "${PYTHON_BIN}" scripts/check_generated.py --quiet
  fi
fi

mkdir -p "$(dirname "${OUTPUT}")"

if [[ ${QUARTUS_ARCHIVE} -eq 1 ]]; then
  if [[ -f "${project_base}.qpf" ]]; then
    qarchive="${OUTPUT%.tar.gz}.qar"
    say_cmd "${QUARTUS_SH_BIN}" --archive "${project_base}" -c "${REVISION}" "${qarchive}"
    if [[ ${DRY_RUN} -eq 0 ]]; then
      if ! command -v "${QUARTUS_SH_BIN}" >/dev/null 2>&1; then
        echo "ERROR: ${QUARTUS_SH_BIN} not found in PATH" >&2
        exit 1
      fi
      "${QUARTUS_SH_BIN}" --archive "${project_base}" -c "${REVISION}" "${qarchive}"
    fi
  else
    echo "warning: --quartus-archive requested but ${project_base}.qpf is absent" >&2
  fi
fi

export TRECAP_EXPORT_OUTPUT="${OUTPUT}"
export TRECAP_EXPORT_PROJECT_BASE="${project_base}"
export TRECAP_EXPORT_REVISION="${REVISION}"
export TRECAP_EXPORT_INCLUDE_REFERENCE_OUTPUTS="${INCLUDE_REFERENCE_OUTPUTS}"
export TRECAP_EXPORT_INCLUDE_CAPTURES="${INCLUDE_CAPTURES}"
export TRECAP_EXPORT_INCLUDE_RUNS="${INCLUDE_RUNS}"
export TRECAP_EXPORT_DRY_RUN="${DRY_RUN}"

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations
import hashlib
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

output = Path(os.environ["TRECAP_EXPORT_OUTPUT"])
project_base = os.environ["TRECAP_EXPORT_PROJECT_BASE"]
revision = os.environ["TRECAP_EXPORT_REVISION"]
include_reference = os.environ["TRECAP_EXPORT_INCLUDE_REFERENCE_OUTPUTS"] == "1"
include_captures = os.environ["TRECAP_EXPORT_INCLUDE_CAPTURES"] == "1"
include_runs = os.environ["TRECAP_EXPORT_INCLUDE_RUNS"] == "1"
dry_run = os.environ["TRECAP_EXPORT_DRY_RUN"] == "1"

include_roots = [
    "README.md",
    "Makefile",
    "CMakeLists.txt",
    ".gitignore",
    ".editorconfig",
    ".clang-format",
    ".pre-commit-config.yaml",
    "docs/specs",
    "docs/architecture",
    "docs/bringup",
    "spec/generated",
    "spec/schemas",
    "spec/normative",
    "config/boards",
    "config/profiles",
    "scripts/gen_headers.py",
    "scripts/gen_filelists.py",
    "scripts/check_generated.py",
    "scripts/lint_repo_layout.py",
    "scripts/package_artifacts.py",
    "scripts/clean_outputs.sh",
    "scripts/format.sh",
    "scripts/lint.sh",
    "scripts/quartus",
    "filelists",
    "rtl",
    "constraints/de1soc",
    "platform/de1soc/qsys",
    "platform/de1soc/address_map",
    "platform/de1soc/generated_notes",
    "artifacts/coefficients",
    "artifacts/test_vectors",
    "artifacts/manifests",
    "sw/hps/include/generated",
    "sw/pc_dashboard/generated",
]
if include_reference:
    include_roots.append("artifacts/reference_outputs")
if include_captures:
    include_roots.append("artifacts/telemetry_captures")
if include_runs:
    include_roots.append("runs/quartus")

# Include the Quartus project directory if it exists and is not already covered.
project_dir = str(PurePosixPath(project_base).parent)
if project_dir not in {".", ""}:
    include_roots.append(project_dir)

excluded_parts = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "build",
    "out",
    "legacy",
    "db",
    "incremental_db",
    "output_files",
    "simulation",
    "work",
    "greybox_tmp",
    "submodules",
    "testbench",
    "synthesis",
}
excluded_suffixes = {".pyc", ".pyo", ".wlf", ".vcd", ".fst", ".ghw", ".tmp", ".log"}

files: list[Path] = []
seen: set[str] = set()

def is_excluded(path: Path) -> bool:
    rel = PurePosixPath(path.as_posix())
    if any(part in excluded_parts for part in rel.parts):
        return True
    if not include_reference and rel.parts[:2] == ("artifacts", "reference_outputs"):
        return True
    if not include_captures and rel.parts[:2] == ("artifacts", "telemetry_captures"):
        return True
    if not include_runs and rel.parts[:1] == ("runs",):
        return True
    if path.suffix in excluded_suffixes:
        return True
    if path.name == ".gitkeep":
        return True
    return False

for root_name in include_roots:
    root = Path(root_name)
    if not root.exists():
        continue
    candidates = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    for path in candidates:
        rel = path.as_posix()
        if is_excluded(path):
            continue
        if rel not in seen:
            seen.add(rel)
            files.append(path)
files.sort(key=lambda p: p.as_posix())

manifest_files = []
for path in files:
    data = path.read_bytes()
    manifest_files.append({"path": path.as_posix(), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
manifest = {
    "schema": "trecap_phase2_quartus_source_export_manifest_v1",
    "file_class": "[2] generated export manifest - do not edit by hand",
    "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "project_base": project_base,
    "revision": revision,
    "policy": {
        "source_export_only": True,
        "excludes_quartus_scratch": True,
        "excludes_legacy_by_default": True,
        "generated_contracts_included": True,
    },
    "include_reference_outputs": include_reference,
    "include_captures": include_captures,
    "include_runs": include_runs,
    "file_count": len(files),
    "files": manifest_files,
}

if dry_run:
    print(f"DRY-RUN export would create: {output}")
    for item in manifest_files:
        print(item["path"])
    print(f"DRY-RUN file_count={len(files)}")
    raise SystemExit(0)

prefix = output.name[:-7] if output.name.endswith(".tar.gz") else output.stem
output.parent.mkdir(parents=True, exist_ok=True)
with tarfile.open(output, "w:gz") as tar:
    for path in files:
        info = tar.gettarinfo(path, arcname=f"{prefix}/{path.as_posix()}")
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        with path.open("rb") as f:
            tar.addfile(info, f)
    data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(data)
        tmp.flush()
        info = tar.gettarinfo(tmp.name, arcname=f"{prefix}/EXPORT_MANIFEST.json")
        info.size = len(data)
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        with open(tmp.name, "rb") as f:
            tar.addfile(info, f)
print(f"export_project: wrote {output} files={len(files)}")
PY
