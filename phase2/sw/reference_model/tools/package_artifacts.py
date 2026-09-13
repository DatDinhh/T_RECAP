#!/usr/bin/env python3
"""Package checked T-RECAP golden artifacts into deterministic archives."""
from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from _trecap_tool_common import ToolError, main_wrapper, read_json, sha256_file, write_json

_PACKAGE_SUFFIXES = {".memh", ".csv", ".json"}


def sanitize_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-.") or "trecap-golden-artifacts"


def run_artifact_check(artifacts: Path) -> None:
    proc = subprocess.run([sys.executable, "tools/artifact_check.py", "--artifacts", str(artifacts)], text=True)
    if proc.returncode != 0:
        raise ToolError("artifact_check.py failed; refusing to package unchecked artifacts")


def collect_files(artifacts: Path) -> list[Path]:
    if not artifacts.exists():
        raise ToolError(f"missing artifact directory: {artifacts}")
    return sorted(p for p in artifacts.rglob("*") if p.is_file() and p.suffix.lower() in _PACKAGE_SUFFIXES)


def load_release_info(artifacts: Path, allow_unfrozen: bool) -> dict[str, Any]:
    manifest_path = artifacts / "manifests" / "frozen_release_manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        return {
            "release_name": manifest.get("release_name", "phase2_revJ_golden"),
            "release_version": manifest.get("release_version", "0.0.0"),
            "spec_revision": manifest.get("spec_revision", "core_rev_j"),
            "telemetry_revision": manifest.get("telemetry_revision", "telemetry_rev_g"),
            "frozen_release_manifest_sha256": sha256_file(manifest_path),
            "release_manifest_created_utc": manifest.get("created_utc", ""),
            "frozen": True,
        }
    if not allow_unfrozen:
        raise ToolError(
            f"missing {manifest_path}; run make freeze-release or pass --allow-unfrozen for diagnostic packaging"
        )
    return {
        "release_name": "unfrozen_artifacts",
        "release_version": "0.0.0-unfrozen",
        "spec_revision": "core_rev_j",
        "telemetry_revision": "telemetry_rev_g",
        "frozen_release_manifest_sha256": None,
        "release_manifest_created_utc": "",
        "frozen": False,
    }


def rows_for(path: Path) -> int | None:
    if path.suffix.lower() in {".memh", ".csv"}:
        return len(path.read_text(encoding="utf-8" if path.suffix.lower() == ".csv" else "ascii").splitlines())
    return None


def package_manifest(artifacts: Path, files: list[Path], release_info: dict[str, Any], archive_root: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in files:
        rel = path.relative_to(artifacts).as_posix()
        entry: dict[str, Any] = {
            "path": f"artifacts/{rel}",
            "artifact_type": path.suffix.lower().lstrip("."),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        row_count = rows_for(path)
        if row_count is not None:
            entry["rows"] = row_count
        entries.append(entry)
    return {
        "schema": "trecap_artifact_package_manifest_v1",
        "package_contract": "deterministic_archive_with_lf_artifacts",
        "archive_root": archive_root,
        "release": release_info,
        "artifact_count": len(entries),
        "files": entries,
        "notes": [
            "Artifacts are packaged after artifact_check.py unless --skip-check was used.",
            "Canonical memh hashes inside release manifests remain the signoff authority.",
        ],
    }


def add_bytes_to_tar(tf: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mtime = 0
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    tf.addfile(info, io.BytesIO(data))


def write_tar_gz(out_path: Path, archive_root: str, files: list[Path], artifacts: Path, manifest: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tf:
                add_bytes_to_tar(tf, f"{archive_root}/PACKAGE_MANIFEST.json", json.dumps(manifest, indent=2).encode("utf-8") + b"\n")
                add_bytes_to_tar(
                    tf,
                    f"{archive_root}/README_PACKAGE.md",
                    package_readme(manifest).encode("utf-8"),
                )
                for path in files:
                    rel = path.relative_to(artifacts).as_posix()
                    add_bytes_to_tar(tf, f"{archive_root}/artifacts/{rel}", path.read_bytes())


def write_zip(out_path: Path, archive_root: str, files: list[Path], artifacts: Path, manifest: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        def write_member(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)

        write_member(f"{archive_root}/PACKAGE_MANIFEST.json", json.dumps(manifest, indent=2).encode("utf-8") + b"\n")
        write_member(f"{archive_root}/README_PACKAGE.md", package_readme(manifest).encode("utf-8"))
        for path in files:
            rel = path.relative_to(artifacts).as_posix()
            write_member(f"{archive_root}/artifacts/{rel}", path.read_bytes())


def package_readme(manifest: dict[str, Any]) -> str:
    release = manifest["release"]
    return (
        "# T-RECAP Golden Artifact Package\n\n"
        f"Release: `{release['release_name']}`\n\n"
        f"Version: `{release['release_version']}`\n\n"
        f"Spec revision: `{release['spec_revision']}`\n\n"
        "This archive contains frozen coefficient, vector, golden-output, statistics, and manifest artifacts. "
        "The canonical memh hashes recorded in the manifests are the signoff authority. "
        "Do not treat regenerated vectors as equivalent unless their canonical hashes match.\n"
    )


def run() -> int:
    parser = argparse.ArgumentParser(description="Package checked T-RECAP artifacts")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--name", default=None, help="archive basename without extension")
    parser.add_argument("--format", choices=["tar.gz", "zip", "both"], default="tar.gz")
    parser.add_argument("--skip-check", action="store_true")
    parser.add_argument("--allow-unfrozen", action="store_true")
    args = parser.parse_args()

    if not args.skip_check:
        run_artifact_check(args.artifacts)
    files = collect_files(args.artifacts)
    if not files:
        raise ToolError(f"no packageable artifacts found under {args.artifacts}")
    release_info = load_release_info(args.artifacts, args.allow_unfrozen)
    base_name = sanitize_name(args.name or f"trecap-golden-artifacts-{release_info['release_name']}-{release_info['release_version']}")
    archive_root = base_name
    manifest = package_manifest(args.artifacts, files, release_info, archive_root)

    outputs: dict[str, str] = {}
    archive_paths: list[str] = []
    if args.format in {"tar.gz", "both"}:
        tar_path = args.out / f"{base_name}.tar.gz"
        write_tar_gz(tar_path, archive_root, files, args.artifacts, manifest)
        outputs["tar_gz"] = tar_path.as_posix()
        outputs["tar_gz_sha256"] = sha256_file(tar_path)
        archive_paths.append(tar_path.as_posix())
    if args.format in {"zip", "both"}:
        zip_path = args.out / f"{base_name}.zip"
        write_zip(zip_path, archive_root, files, args.artifacts, manifest)
        outputs["zip"] = zip_path.as_posix()
        outputs["zip_sha256"] = sha256_file(zip_path)
        archive_paths.append(zip_path.as_posix())

    sidecar = {
        "schema": "trecap_artifact_package_sidecar_v1",
        "package_manifest_sha256": __import__("hashlib").sha256(
            (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        ).hexdigest(),
        "outputs": outputs,
        "artifact_count": len(files),
        "release": release_info,
    }
    sidecar_path = args.out / f"{base_name}.package_manifest.json"
    write_json(sidecar_path, sidecar)
    print(f"package_artifacts: wrote {', '.join(archive_paths)}")
    print(f"package_artifacts: wrote {sidecar_path}")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
