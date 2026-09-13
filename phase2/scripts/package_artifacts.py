#!/usr/bin/env python3
"""Package T-RECAP Phase 2 contracts and artifact data.

File class: [1] hand-written repository infrastructure.

The package produced by this script is a portable implementation artifact bundle:
checked-in generated contracts, generated filelists, coefficient/vector/reference-output
artifacts if present, and a machine-readable manifest. It is deliberately not a
full source release and deliberately excludes local build output, virtual
environments, runs, quarantined material, and simulator/Quartus scratch files.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Mapping, Sequence

DEFAULT_INCLUDE_PATHS = [
    "spec/generated",
    "spec/schemas",
    "spec/normative/README.md",
    "rtl/include/generated",
    "sw/hps/include/generated",
    "sw/pc_dashboard/generated",
    "sw/reference_model/generated",
    "filelists",
    "artifacts/coefficients",
    "artifacts/test_vectors",
    "artifacts/reference_outputs",
    "artifacts/manifests",
]

TOOLCHAIN_PROVENANCE_FILES = [
    "scripts/gen_headers.py",
    "scripts/gen_filelists.py",
    "scripts/check_generated.py",
    "scripts/package_artifacts.py",
]

OPTIONAL_CAPTURE_PATHS = ["artifacts/telemetry_captures"]

EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "build",
    "out",
    "runs",
    "work",
    "db",
    "incremental_db",
    "output_files",
    "simulation",
}

EXCLUDED_FILE_NAMES = {
    ".gitkeep",
    ".DS_Store",
    "transcript",
    "modelsim.ini",
    "vsim.wlf",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".wlf",
    ".vcd",
    ".fst",
    ".ghw",
    ".bak",
    ".tmp",
    ".log",
}

STRICT_REQUIRED_ARTIFACTS = [
    "artifacts/coefficients/window_qw.memh",
    "artifacts/coefficients/twiddle_re.memh",
    "artifacts/coefficients/twiddle_im.memh",
    "artifacts/coefficients/twiddle_inv_re.memh",
    "artifacts/coefficients/twiddle_inv_im.memh",
    "artifacts/coefficients/coeff_manifest.json",
    "artifacts/test_vectors/test_vectors.json",
    "artifacts/manifests/artifact_index.json",
]


@dataclass(frozen=True)
class PackageFile:
    relpath: str
    size_bytes: int
    sha256: str


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(data: object) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_excluded(root: Path, path: Path) -> bool:
    r = PurePosixPath(rel(root, path))
    if any(part in EXCLUDED_DIR_NAMES for part in r.parts[:-1]):
        return True
    if path.name in EXCLUDED_FILE_NAMES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    return False


def iter_package_files(root: Path, include_paths: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    seen: set[str] = set()
    for item in include_paths:
        path = root / item
        if not path.exists():
            continue
        if path.is_file():
            if not is_excluded(root, path):
                r = rel(root, path)
                if r not in seen:
                    seen.add(r)
                    files.append(path)
            continue
        for p in sorted(path.rglob("*")):
            if p.is_file() and not is_excluded(root, p):
                r = rel(root, p)
                if r not in seen:
                    seen.add(r)
                    files.append(p)
    return sorted(files, key=lambda p: rel(root, p))


def build_manifest(
    root: Path,
    package_name: str,
    files: Sequence[Path],
    warnings: Sequence[str],
    include_paths: Sequence[str],
) -> tuple[dict, List[PackageFile]]:
    package_files = [
        PackageFile(rel(root, path), path.stat().st_size, sha256_file(path)) for path in files
    ]
    manifest = {
        "schema": "trecap_phase2_artifact_package_manifest_v1",
        "file_class": "[2] generated artifact package manifest - do not edit by hand",
        "package_name": package_name,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "generator": {
            "path": "scripts/package_artifacts.py",
            "version": "r1.0.0",
        },
        "package_policy": {
            "purpose": "Portable Phase 2 generated-contract and artifact bundle.",
            "not_a_source_release": True,
            "not_a_verification_database": True,
            "reference_model_is_not_final_golden_authority": True,
            "excluded_local_output": [
                "build",
                "out",
                "runs",
                "work",
                "__pycache__",
                ".pytest_cache",
                ".venv",
                "Quartus/ModelSim scratch directories",
            ],
        },
        "included_roots": list(include_paths),
        "file_count": len(package_files),
        "payload_bytes": sum(item.size_bytes for item in package_files),
        "files": [item.__dict__ for item in package_files],
        "warnings": list(warnings),
    }
    return manifest, package_files


def add_bytes_to_tar(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(data)
        tmp.flush()
        info = tar.gettarinfo(tmp.name, arcname=arcname)
        info.size = len(data)
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        with open(tmp.name, "rb") as f:
            tar.addfile(info, f)


def add_file_to_tar(tar: tarfile.TarFile, root: Path, path: Path, prefix: str) -> None:
    arcname = f"{prefix}/{rel(root, path)}"
    info = tar.gettarinfo(path, arcname=arcname)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    with path.open("rb") as f:
        tar.addfile(info, f)


def write_deterministic_targz(root: Path, archive_path: Path, prefix: str, files: Sequence[Path], manifest_bytes: bytes) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for path in files:
                    add_file_to_tar(tar, root, path, prefix)
                add_bytes_to_tar(tar, f"{prefix}/package_manifest.json", manifest_bytes)


def validate_strict(root: Path) -> List[str]:
    missing = [path for path in STRICT_REQUIRED_ARTIFACTS if not (root / path).is_file()]
    return missing


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Package T-RECAP Phase 2 generated contracts and artifacts.")
    parser.add_argument("--root", default=None, help="Repository root. Default: parent of this script directory.")
    parser.add_argument("--output-dir", default="out/artifacts", help="Directory for package archive and manifest.")
    parser.add_argument("--name", default=None, help="Package base name. Default uses UTC timestamp.")
    parser.add_argument("--include-captures", action="store_true", help="Include artifacts/telemetry_captures.")
    parser.add_argument("--include-tools", action="store_true", help="Include generator/checker scripts for provenance.")
    parser.add_argument("--strict", action="store_true", help="Require frozen coefficient/vector manifest files to exist.")
    parser.add_argument("--manifest-only", action="store_true", help="Write only the JSON manifest, not the tar.gz archive.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected files but do not write outputs.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else repo_root_from_script()
    if not (root / "Makefile").is_file():
        print(f"ERROR: repository root does not look valid: {root}")
        return 2

    warnings: List[str] = []
    include_paths = list(DEFAULT_INCLUDE_PATHS)
    if args.include_captures:
        include_paths.extend(OPTIONAL_CAPTURE_PATHS)
    if args.include_tools:
        include_paths.extend(TOOLCHAIN_PROVENANCE_FILES)

    missing_include_roots = [p for p in include_paths if not (root / p).exists()]
    for path in missing_include_roots:
        warnings.append(f"include path missing and skipped: {path}")

    if args.strict:
        missing = validate_strict(root)
        if missing:
            for item in missing:
                print(f"ERROR: strict artifact package requires missing file: {item}")
            return 1

    files = iter_package_files(root, include_paths)
    if not files:
        print("ERROR: no package files selected")
        return 1

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    package_name = args.name or f"trecap_phase2_artifacts_{now}"
    manifest, package_files = build_manifest(root, package_name, files, warnings, include_paths)
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(manifest_bytes)

    output_dir = (root / args.output_dir).resolve()
    try:
        output_dir.relative_to(root.resolve())
    except ValueError:
        print(f"ERROR: output directory escapes repository root: {output_dir}")
        return 2

    archive_path = output_dir / f"{package_name}.tar.gz"
    manifest_path = output_dir / f"{package_name}.manifest.json"

    if args.dry_run:
        print(f"package name: {package_name}")
        print(f"file count: {len(package_files)}")
        print(f"manifest sha256: {manifest_sha}")
        for item in package_files:
            print(f"  {item.relpath}  size={item.size_bytes}  sha256={item.sha256}")
        for warning in warnings:
            print(f"warning: {warning}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)
    if not args.manifest_only:
        write_deterministic_targz(root, archive_path, package_name, files, manifest_bytes)
        archive_sha = sha256_file(archive_path)
        print(f"wrote {archive_path.relative_to(root).as_posix()} sha256={archive_sha}")
    print(f"wrote {manifest_path.relative_to(root).as_posix()} sha256={manifest_sha}")
    for warning in warnings:
        print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
