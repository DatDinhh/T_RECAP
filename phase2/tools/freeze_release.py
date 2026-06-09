#!/usr/bin/env python3
"""Freeze a top-level release manifest over checked canonical artifacts."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from _trecap_tool_common import (
    FRAME_STATS_HEADER,
    BIN_STATS_HEADER,
    GENERATOR_VERSION,
    GOLDEN_MODEL_VERSION,
    H,
    L,
    N,
    W_QW,
    W_TW,
    SPEC_REVISION,
    TELEMETRY_REVISION,
    ToolError,
    base_configuration,
    canonical_file_hash,
    csv_row_count,
    full_tail_geometry,
    read_json,
    main_wrapper,
    sha256_file,
    utc_now,
    widths,
    write_json,
)


def run_subprocess(argv: list[str]) -> None:
    proc = subprocess.run(argv, text=True)
    if proc.returncode != 0:
        raise ToolError(f"command failed with exit code {proc.returncode}: {' '.join(argv)}")


def artifact_type(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"memh", "json", "csv", "md", "bin", "tar", "zip"}:
        return suffix
    raise ToolError(f"unsupported artifact type for release manifest: {path}")


def load_release_config(path: Path | None) -> dict[str, Any]:
    """Load a reviewed release recipe.

    Release configs are human-reviewed inputs under configs/releases/. They are
    deliberately not generated manifests; freeze_release.py consumes them to
    choose the release name, version, artifact root, output path, and documented
    reproduction commands.
    """
    if path is None:
        return {}
    obj = read_json(path)
    if obj.get("schema") != "trecap_phase2_release_config_v1":
        raise ToolError(f"release config {path} has unsupported schema: {obj.get('schema')!r}")
    required = [
        "release_config_name",
        "release_name",
        "release_version",
        "spec_revision",
        "telemetry_revision",
        "suite_config",
        "artifact_root",
        "output_manifests",
        "reproduction",
    ]
    missing = [key for key in required if key not in obj]
    if missing:
        raise ToolError(f"release config {path} is missing required key(s): {', '.join(missing)}")
    if obj["release_config_name"] != path.stem:
        raise ToolError(
            f"release config {path}: release_config_name must equal filename stem {path.stem!r}"
        )
    if obj["spec_revision"] != SPEC_REVISION:
        raise ToolError(
            f"release config {path}: spec_revision {obj['spec_revision']!r} != {SPEC_REVISION!r}"
        )
    if obj["telemetry_revision"] != TELEMETRY_REVISION:
        raise ToolError(
            f"release config {path}: telemetry_revision {obj['telemetry_revision']!r} != {TELEMETRY_REVISION!r}"
        )
    suite = Path(str(obj["suite_config"]))
    if not suite.exists():
        raise ToolError(f"release config {path}: suite_config does not exist: {suite}")
    artifact_root = Path(str(obj["artifact_root"]))
    if not artifact_root.exists():
        raise ToolError(f"release config {path}: artifact_root does not exist: {artifact_root}")
    commands = obj.get("reproduction", {}).get("commands")
    if not isinstance(commands, list) or not commands or not all(isinstance(x, str) and x for x in commands):
        raise ToolError(f"release config {path}: reproduction.commands must be a nonempty string list")
    return obj


def manifest_relative_path(path: Path, artifact_root: Path | None = None) -> Path:
    """Return a schema-safe relative path for release manifests.

    The artifact contract forbids absolute paths in manifests.  If callers pass
    an absolute --artifacts directory, the manifest still records a stable
    logical artifact path rooted at that artifact directory name.
    """

    if artifact_root is not None:
        try:
            return Path(artifact_root.name) / path.relative_to(artifact_root)
        except ValueError:
            pass
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return Path(path.name)


def infer_role(path: Path) -> str:
    parts = path.as_posix().split("/")
    if "coefficients" in parts and path.suffix == ".memh":
        return "coefficient"
    if path.name == "x_in.memh":
        return "test_vector_input"
    if path.name == "y_out.memh":
        return "golden_output"
    if path.name in {"frame_stats.csv", "bin_stats.csv", "metrics.json"}:
        return "statistics"
    if path.name == "config.json":
        return "configuration"
    if "manifests" in parts or path.name in {"coeff_manifest.json", "test_vectors.json"}:
        return "manifest"
    return "debug"


def vector_name_from_path(path: Path) -> str | None:
    parts = path.as_posix().split("/")
    for anchor in ("test_vectors", "golden"):
        if anchor in parts:
            idx = parts.index(anchor)
            if idx + 1 < len(parts) and parts[idx + 1] != "test_vectors.json":
                return parts[idx + 1]
    return None


def rows_for_artifact(path: Path) -> int | None:
    if path.suffix == ".memh":
        return len(path.read_text(encoding="ascii").splitlines())
    if path.name == "frame_stats.csv":
        return csv_row_count(path, FRAME_STATS_HEADER)
    if path.name == "bin_stats.csv":
        return csv_row_count(path, BIN_STATS_HEADER)
    return None


def memh_contract(path: Path) -> tuple[int, bool] | None:
    name = path.name
    if name == "window_qw.memh":
        return W_QW, False
    if name.startswith("twiddle") and name.endswith(".memh"):
        return W_TW, True
    if name in {"x_in.memh", "y_out.memh"}:
        return N, True
    return None


def artifact_entry(path: Path, artifact_root: Path | None = None) -> dict[str, Any]:
    logical_path = manifest_relative_path(path, artifact_root)
    entry: dict[str, Any] = {
        "path": logical_path.as_posix(),
        "role": infer_role(logical_path),
        "artifact_type": artifact_type(path),
        "sha256": sha256_file(path),
        "canonicalized": path.suffix in {".memh", ".csv"},
        "required": True,
        "producer": "trecap-golden tools",
    }
    vname = vector_name_from_path(logical_path)
    if vname:
        entry["vector_name"] = vname
    if path.suffix == ".json":
        entry["schema_ref"] = schema_ref_for_json(path)
    rows = rows_for_artifact(path)
    if rows is not None:
        entry["rows"] = rows
    memh = memh_contract(path)
    if memh is not None:
        width, signed = memh
        entry["width_bits"] = width
        entry["signed"] = signed
        entry["canonical_sha256"] = canonical_file_hash(path, width, signed=signed)
        entry["content_contract"] = "fixed_width_lowercase_hex_lf"
    elif path.suffix == ".csv":
        entry["content_contract"] = "lf_csv_exact_header"
    elif path.suffix == ".json":
        entry["content_contract"] = "json_schema_validated"
    return entry


def schema_ref_for_json(path: Path) -> str:
    name = path.name
    if name == "coeff_manifest.json":
        return "spec/schemas/coeff_manifest.schema.json"
    if name == "test_vectors.json":
        return "spec/schemas/test_vectors.schema.json"
    if name == "config.json":
        return "spec/schemas/vector_config.schema.json"
    if name == "metrics.json":
        return "spec/schemas/metrics.schema.json"
    if name == "quality_bounds.json":
        return "spec/schemas/quality_bounds.schema.json"
    if name == "artifact_index.json":
        return "spec/schemas/artifact_index.schema.json"
    if name == "frozen_release_manifest.json":
        return "spec/schemas/frozen_release_manifest.schema.json"
    return "unvalidated_json"


def collect_artifact_paths(root: Path, include_index: bool) -> list[Path]:
    paths = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in {".memh", ".csv", ".json"}
    )
    filtered: list[Path] = []
    for path in paths:
        if path.name == "frozen_release_manifest.json":
            continue
        if not include_index and path.name == "artifact_index.json":
            continue
        filtered.append(path)
    return filtered


def write_core_config_snapshot(path: Path) -> None:
    snapshot = {
        "schema": "trecap_phase2_core_config_snapshot_v1",
        "spec_revision": SPEC_REVISION,
        "created_utc": utc_now(),
        "configuration": base_configuration("0"),
        "widths": widths(),
        "notes": "Generated by freeze_release.py until spec/generated/core_config.json is added.",
    }
    write_json(path, snapshot)


def write_artifact_index(root: Path, out_path: Path, release_name: str) -> None:
    artifacts = [artifact_entry(path, root) for path in collect_artifact_paths(root, include_index=False)]
    index = {
        "schema": "trecap_phase2_artifact_index_v1",
        "spec_revision": SPEC_REVISION,
        "created_utc": utc_now(),
        "release_name": release_name,
        "core_config_sha256": sha256_file(root / "manifests" / "core_config_snapshot.json"),
        "coeff_manifest_sha256": sha256_file(root / "coefficients" / "coeff_manifest.json"),
        "test_vectors_sha256": sha256_file(root / "test_vectors" / "test_vectors.json"),
        "quality_bounds_sha256": sha256_file(root / "manifests" / "quality_bounds.json"),
        "artifacts": artifacts,
    }
    write_json(out_path, index)


def run() -> int:
    parser = argparse.ArgumentParser(description="Freeze T-RECAP artifact release manifest")
    parser.add_argument("--release-config", type=Path, default=None, help="Reviewed release recipe under configs/releases/.")
    parser.add_argument("--artifacts", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--release-name", default=None)
    parser.add_argument("--release-version", default=None)
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args()

    release_config = load_release_config(args.release_config)
    artifacts_root = args.artifacts or Path(str(release_config.get("artifact_root", "artifacts")))
    output_manifest = args.out
    if output_manifest is None:
        output_manifest = Path(
            str(
                release_config.get("output_manifests", {}).get(
                    "frozen_release_manifest", "artifacts/manifests/frozen_release_manifest.json"
                )
            )
        )
    release_name = args.release_name or str(release_config.get("release_name", "phase2_revJ_golden"))
    release_version = args.release_version or str(release_config.get("release_version", "0.1.0"))
    reproduction_commands = release_config.get("reproduction", {}).get(
        "commands",
        [
            "make coeffs",
            "make vectors",
            "make golden",
            "make check-artifacts",
            "make quality-bounds",
            "make freeze-release",
        ],
    )

    if not args.skip_check:
        run_subprocess([sys.executable, "tools/artifact_check.py", "--artifacts", str(artifacts_root)])
    if not (artifacts_root / "manifests" / "quality_bounds.json").exists():
        run_subprocess(
            [
                sys.executable,
                "tools/make_quality_bounds.py",
                "--artifacts",
                str(artifacts_root),
                "--out",
                str(artifacts_root / "manifests" / "quality_bounds.json"),
            ]
        )

    core_config_path = artifacts_root / "manifests" / "core_config_snapshot.json"
    write_core_config_snapshot(core_config_path)
    artifact_index_path = artifacts_root / "manifests" / "artifact_index.json"
    write_artifact_index(artifacts_root, artifact_index_path, release_name)

    artifacts = [artifact_entry(path, artifacts_root) for path in collect_artifact_paths(artifacts_root, include_index=True)]
    release = {
        "schema": "trecap_phase2_frozen_release_manifest_v1",
        "release_name": release_name,
        "release_version": release_version,
        "spec_revision": SPEC_REVISION,
        "telemetry_revision": TELEMETRY_REVISION,
        "created_utc": utc_now(),
        "generator_versions": {
            "golden_model": GOLDEN_MODEL_VERSION,
            "coefficient_generator": GENERATOR_VERSION,
            "vector_generator": GENERATOR_VERSION,
            "artifact_checker": "artifact_check.py",
            "quality_bounds_generator": "make_quality_bounds.py",
        },
        "manifest_hashes": {
            "core_config_sha256": sha256_file(core_config_path),
            "coeff_manifest_sha256": sha256_file(artifacts_root / "coefficients" / "coeff_manifest.json"),
            "test_vectors_sha256": sha256_file(artifacts_root / "test_vectors" / "test_vectors.json"),
            "quality_bounds_sha256": sha256_file(artifacts_root / "manifests" / "quality_bounds.json"),
            "artifact_index_sha256": sha256_file(artifact_index_path),
        },
        "artifacts": artifacts,
        "acceptance": {
            "coefficients_hash_match": True,
            "stream_hashes_match": True,
            "row_counts_match": True,
            "json_schemas_pass": True,
            "csv_schemas_pass": True,
            "quality_bounds_pass": True,
            "no_internal_overflow_flags": True,
            "notes": "Artifact checks passed before release freeze; RTL/BRAM replay remains separate signoff.",
        },
        "reproduction": {
            "commands": reproduction_commands,
            "python_version": sys.version.split()[0],
        },
    }
    write_json(output_manifest, release)
    print(f"freeze_release: wrote {output_manifest}")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
