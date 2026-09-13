# SPDX-License-Identifier: MIT
"""Fail-closed validation of a complete T-RECAP artifact release.

The checker treats the artifact tree as an acyclic authenticated graph:

* leaf memh/CSV/JSON artifacts are checked first;
* ``artifact_index.json`` authenticates every packageable leaf;
* ``frozen_release_manifest.json`` authenticates the index and the same leaves;
* an optional architecture import manifest authenticates the vendored source
  tree and the promoted root tree.

No release manifest is optional in the default mode.  Callers that are
constructing a new release must explicitly request ``require_frozen=False`` and
must run the default check again after freezing.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from trecap_golden.contracts.contract_paths import ContractPaths, default_paths
from trecap_golden.generated import trecap_config as cfg

from . import csv_io, manifests
from .hashes import canonical_memh_file_hash, sha256_file
from .memh import MemhContract, contract_for_kind, infer_contract, read_memh

try:  # Dependency absence is reported as a hard checker issue below.
    from jsonschema import Draft202012Validator, FormatChecker
except Exception as exc:  # pragma: no cover - exercised by dependency-failure regression
    Draft202012Validator = None  # type: ignore[assignment,misc]
    FormatChecker = None  # type: ignore[assignment,misc]
    _JSONSCHEMA_IMPORT_ERROR: Exception | None = exc
else:
    _JSONSCHEMA_IMPORT_ERROR = None


LOWER_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LOWER_CRC32_RE = re.compile(r"^[0-9a-f]{8}$")
WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
REFERENCE_ROOT_PATH = PurePosixPath("sw/reference_model")
EXPECTED_IMPORT_EXCLUDED_DIRECTORIES = (
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "legacy",
    "out",
    "runs",
)
EXPECTED_IMPORT_EXCLUDED_EXACT = (
    "spec/normative/T_RECAP_Phase2_Integrated_RevJ_RevG.pdf",
)
EXPECTED_IMPORT_EXCLUDED_SUFFIXES = (".pyc", ".pyo")
EXPECTED_GENERATED_IMPORT_MANIFESTS = (
    "artifacts/manifests/reference_import_manifest.json",
    "sw/reference_model/import_manifest.json",
)
EXPECTED_IMPORT_RESOURCE_CAPS: Mapping[str, int | str] = {
    "max_compression_ratio": "1000",
    "max_entries": 20_000,
    "max_file_bytes": 128 * 1024 * 1024,
    "max_total_bytes": 1024 * 1024 * 1024,
}
EXPECTED_IMPORT_POLICY: Mapping[str, Any] = {
    "excluded_directories": list(EXPECTED_IMPORT_EXCLUDED_DIRECTORIES),
    "excluded_exact": list(EXPECTED_IMPORT_EXCLUDED_EXACT),
    "excluded_suffixes": list(EXPECTED_IMPORT_EXCLUDED_SUFFIXES),
    "generated_manifest_paths": list(EXPECTED_GENERATED_IMPORT_MANIFESTS),
    "manifest_serialization": "canonical-json-sort-keys-compact-ascii-lf-v1",
    "path_policy": "portable-nfc-casefold-collision-free-v1",
    "payload_policy": "verbatim_bytes_no_newline_or_json_normalization",
    "policy_version": "trecap_phase2_reference_import_policy_v1",
    "resource_caps": EXPECTED_IMPORT_RESOURCE_CAPS,
}
SUPPORTED_ZIP_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
MAX_ZIP_MEMBER_NAME_BYTES = 4096
SUPPORTED_ARTIFACT_SUFFIXES = frozenset({".json", ".csv", ".memh"})
RELEASE_MANIFEST_NAMES = frozenset(
    {
        "artifact_index.json",
        "frozen_release_manifest.json",
        "reference_import_manifest.json",
    }
)
RELEASE_MANIFEST_PATHS = frozenset(
    {
        "artifacts/manifests/artifact_index.json",
        "artifacts/manifests/frozen_release_manifest.json",
        "artifacts/manifests/reference_import_manifest.json",
    }
)
PROMOTED_TREE_GITKEEP_PATHS = frozenset(
    {
        "coefficients/.gitkeep",
        "manifests/.gitkeep",
        "reference_outputs/.gitkeep",
        "telemetry_captures/.gitkeep",
        "test_vectors/.gitkeep",
    }
)
SCHEMA_FILES: Mapping[str, str] = {
    "core_config": "core_config.schema.json",
    "coeff_manifest": "coeff_manifest.schema.json",
    "test_vectors": "test_vectors.schema.json",
    "vector_config": "vector_config.schema.json",
    "metrics": "metrics.schema.json",
    "quality_bounds": "quality_bounds.schema.json",
    "artifact_index": "artifact_index.schema.json",
    "frozen_release_manifest": "frozen_release_manifest.schema.json",
    "reference_import_manifest": "reference_import_manifest.schema.json",
}
JSON_SCHEMA_BY_NAME: Mapping[str, str] = {
    "core_config_snapshot.json": "core_config",
    "coeff_manifest.json": "coeff_manifest",
    "test_vectors.json": "test_vectors",
    "config.json": "vector_config",
    "metrics.json": "metrics",
    "quality_bounds.json": "quality_bounds",
    "artifact_index.json": "artifact_index",
    "frozen_release_manifest.json": "frozen_release_manifest",
    "reference_import_manifest.json": "reference_import_manifest",
}


class ArtifactCheckError(ValueError):
    """Raised when artifact checking is requested in fail-fast mode."""


@dataclass(frozen=True, slots=True)
class CheckIssue:
    """One artifact check failure."""

    severity: str
    path: str
    check: str
    message: str


@dataclass(slots=True)
class CheckReport:
    """Structured result for artifact-tree validation."""

    artifacts_dir: Path
    issues: list[CheckIssue] = field(default_factory=list)
    checked: dict[str, int] = field(
        default_factory=lambda: {
            "json": 0,
            "memh": 0,
            "csv": 0,
            "vectors": 0,
            "raw_hashes": 0,
            "index_entries": 0,
            "release_entries": 0,
            "imported_files": 0,
            "promoted_files": 0,
        }
    )

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def add_issue(
        self,
        path: str | Path,
        check: str,
        message: str,
        *,
        severity: str = "error",
    ) -> None:
        self.issues.append(CheckIssue(severity, Path(path).as_posix(), check, message))

    def raise_for_errors(self) -> None:
        errors = [issue for issue in self.issues if issue.severity == "error"]
        if errors:
            first = errors[0]
            raise ArtifactCheckError(f"{first.path}: {first.check}: {first.message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "trecap_artifact_check_report_v2",
            "artifacts_dir": self.artifacts_dir.as_posix(),
            "ok": self.ok,
            "checked": dict(self.checked),
            "issues": [
                {
                    "severity": issue.severity,
                    "path": issue.path,
                    "check": issue.check,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


def _check_equal(
    report: CheckReport,
    path: Path,
    check: str,
    actual: Any,
    expected: Any,
) -> None:
    if actual != expected:
        report.add_issue(path, check, f"expected {expected!r}, got {actual!r}")


def _check_sha_text(report: CheckReport, path: Path, check: str, value: Any) -> bool:
    if not isinstance(value, str) or LOWER_SHA256_RE.fullmatch(value) is None:
        report.add_issue(path, check, f"expected lowercase SHA-256, got {value!r}")
        return False
    return True


def _schema_dir(
    *,
    paths: ContractPaths | None,
    schemas_dir: str | Path | None,
    artifacts_dir: Path,
) -> Path:
    if schemas_dir is not None:
        return Path(schemas_dir)
    if paths is not None:
        return paths.schemas_dir
    return default_paths(artifacts_dir).schemas_dir


def _schema_check(
    path: Path,
    schema_name: str,
    schema_dir: Path,
    report: CheckReport,
) -> dict[str, Any] | None:
    try:
        path_mode = path.lstat().st_mode
    except OSError as exc:
        report.add_issue(path, "strict_json", str(exc))
        return None
    if stat.S_ISLNK(path_mode) or not stat.S_ISREG(path_mode):
        report.add_issue(
            path,
            "strict_json",
            "JSON input must be a non-symlink regular file",
        )
        return None
    try:
        obj = manifests.read_json(path)
    except Exception as exc:
        report.add_issue(path, "strict_json", str(exc))
        return None
    report.checked["json"] += 1

    if _JSONSCHEMA_IMPORT_ERROR is not None or Draft202012Validator is None:
        report.add_issue(
            path,
            "dependency",
            "jsonschema is required; install the locked Python dependencies "
            f"({_JSONSCHEMA_IMPORT_ERROR})",
        )
        return obj

    filename = SCHEMA_FILES.get(schema_name)
    if filename is None:
        report.add_issue(path, "schema", f"unknown schema name {schema_name!r}")
        return obj
    schema_path = schema_dir / filename
    try:
        schema_mode = schema_path.lstat().st_mode
    except OSError as exc:
        report.add_issue(schema_path, "schema_required", str(exc))
        return obj
    if stat.S_ISLNK(schema_mode) or not stat.S_ISREG(schema_mode):
        report.add_issue(
            schema_path,
            "schema_required",
            "schema must be a non-symlink regular file",
        )
        return obj
    try:
        schema = manifests.read_json(schema_path)
    except Exception as exc:
        report.add_issue(schema_path, "schema_required", str(exc))
        return obj
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker() if FormatChecker is not None else None,
        )
        errors = sorted(
            validator.iter_errors(obj),
            key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
        )
    except Exception as exc:
        report.add_issue(schema_path, "schema_invalid", str(exc))
        return obj
    for error in errors:
        location = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        report.add_issue(path, "json_schema", f"{location}: {error.message}")
    return obj


def _logical_path(
    artifacts_dir: Path,
    logical: Any,
    owner: Path,
    report: CheckReport,
) -> Path | None:
    if not isinstance(logical, str) or not logical:
        report.add_issue(owner, "path", f"artifact path must be a nonempty string: {logical!r}")
        return None
    if "\\" in logical or "\x00" in logical:
        report.add_issue(owner, "path", f"backslash/NUL forbidden in artifact path {logical!r}")
        return None
    pure = PurePosixPath(logical)
    parts = pure.parts
    if pure.is_absolute() or not parts or parts[0] != "artifacts":
        report.add_issue(owner, "path", f"path must be rooted at artifacts/: {logical!r}")
        return None
    if pure.as_posix() != logical:
        report.add_issue(owner, "path", f"path is not canonical POSIX form: {logical!r}")
        return None
    if any(part in {"", ".", ".."} for part in parts):
        report.add_issue(owner, "path", f"unsafe artifact path: {logical!r}")
        return None

    target = artifacts_dir.joinpath(*parts[1:])
    current = artifacts_dir
    for part in parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            report.add_issue(owner, "path_exists", f"missing indexed artifact: {logical}")
            return None
        except OSError as exc:
            report.add_issue(owner, "path_stat", f"cannot stat {logical}: {exc}")
            return None
        if stat.S_ISLNK(mode):
            report.add_issue(owner, "path_symlink", f"symlink forbidden in artifact path: {logical}")
            return None
    try:
        resolved_root = artifacts_dir.resolve(strict=True)
        resolved_target = target.resolve(strict=True)
        resolved_target.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        report.add_issue(owner, "path_containment", f"{logical}: {exc}")
        return None
    if not target.is_file():
        report.add_issue(owner, "path_regular_file", f"not a regular file: {logical}")
        return None
    return target


def _raw_hash(path: Path, report: CheckReport) -> str | None:
    try:
        digest = sha256_file(path)
    except Exception as exc:
        report.add_issue(path, "sha256", str(exc))
        return None
    report.checked["raw_hashes"] += 1
    return digest


def _source_hash(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _verify_generator_source_hashes(
    source_root: Path | None,
    coeff_manifest: Mapping[str, Any],
    vector_manifest: Mapping[str, Any] | None,
    report: CheckReport,
    coeff_path: Path,
    vector_path: Path | None,
) -> None:
    if source_root is None:
        report.add_issue(
            coeff_path,
            "generator_source",
            "reference source root is required to verify generator_source_sha256",
        )
        return
    common = source_root / "tools" / "_trecap_tool_common.py"
    coeff_tool = source_root / "tools" / "gen_coeffs.py"
    vector_tool = source_root / "tools" / "gen_vectors.py"
    required = [common, coeff_tool, vector_tool]
    missing = [path for path in required if not path.is_file()]
    if missing:
        report.add_issue(
            coeff_path,
            "generator_source",
            "missing generator source(s): " + ", ".join(path.as_posix() for path in missing),
        )
        return
    coeff_actual = _source_hash([coeff_tool, common])
    _check_equal(
        report,
        coeff_path,
        "generator_source_sha256",
        coeff_manifest.get("generator_source_sha256"),
        coeff_actual,
    )
    if vector_manifest is not None and vector_path is not None:
        generators = sorted((source_root / "python" / "trecap_golden" / "generators").glob("*.py"))
        if not generators:
            report.add_issue(vector_path, "generator_source", "generator source set is empty")
            return
        vector_actual = _source_hash([vector_tool, common, *generators])
        _check_equal(
            report,
            vector_path,
            "generator_source_sha256",
            vector_manifest.get("generator_source_sha256"),
            vector_actual,
        )


def check_memh(
    path: str | Path,
    contract: MemhContract,
    *,
    expected_sha256: str | None = None,
    report: CheckReport | None = None,
) -> str:
    """Validate a memh file and return its canonical SHA-256."""

    p = Path(path)
    digest = canonical_memh_file_hash(p, contract)
    if report is not None:
        report.checked["memh"] += 1
        if expected_sha256 is not None and digest != expected_sha256:
            report.add_issue(
                p,
                "canonical_sha256",
                f"expected {expected_sha256}, got {digest}",
            )
    elif expected_sha256 is not None and digest != expected_sha256:
        raise ArtifactCheckError(f"{p}: expected sha256 {expected_sha256}, got {digest}")
    return digest


def check_coefficients(
    artifacts_dir: str | Path,
    paths: ContractPaths | None,
    report: CheckReport,
    *,
    schema_dir: Path | None = None,
) -> dict[str, str]:
    """Check coefficient files and every field that authenticates them."""

    root = Path(artifacts_dir)
    schemas = schema_dir or _schema_dir(paths=paths, schemas_dir=None, artifacts_dir=root)
    coeff_dir = root / "coefficients"
    manifest_path = coeff_dir / "coeff_manifest.json"
    manifest = _schema_check(manifest_path, "coeff_manifest", schemas, report)
    if manifest is None:
        return {}

    expected_names = {
        "window_qw",
        "twiddle_re",
        "twiddle_im",
        "twiddle_inv_re",
        "twiddle_inv_im",
    }
    coefficients = manifest.get("coefficients")
    hashes = manifest.get("hashes")
    artifact_rows = manifest.get("artifact_rows")
    if not isinstance(coefficients, dict):
        report.add_issue(manifest_path, "coefficients", "coefficients must be an object")
        coefficients = {}
    if not isinstance(hashes, dict):
        report.add_issue(manifest_path, "hashes", "hashes must be an object")
        hashes = {}
    if not isinstance(artifact_rows, dict):
        report.add_issue(manifest_path, "artifact_rows", "artifact_rows must be an object")
        artifact_rows = {}
    _check_equal(report, manifest_path, "coefficient set", set(coefficients), expected_names)
    _check_equal(
        report,
        manifest_path,
        "coefficient memh inventory",
        {path.stem for path in coeff_dir.glob("*.memh") if path.is_file()},
        expected_names,
    )

    actual_hashes: dict[str, str] = {}
    for name in sorted(expected_names):
        entry = coefficients.get(name)
        if not isinstance(entry, dict):
            report.add_issue(manifest_path, f"coefficients.{name}", "missing coefficient entry")
            continue
        path = coeff_dir / f"{name}.memh"
        try:
            contract = contract_for_kind(name, rows=cfg.L)
            digest = check_memh(path, contract, report=report)
            raw_digest = _raw_hash(path, report)
        except Exception as exc:
            report.add_issue(path, "memh", str(exc))
            continue
        key = f"{name}_sha256"
        actual_hashes[key] = digest
        expected_entry = {
            "file": f"{name}.memh",
            "rows": cfg.L,
            "width_bits": contract.width_bits,
            "signed": contract.signed,
        }
        for field_name, expected in expected_entry.items():
            _check_equal(
                report,
                manifest_path,
                f"coefficients.{name}.{field_name}",
                entry.get(field_name),
                expected,
            )
        _check_equal(report, manifest_path, f"coefficients.{name}.sha256", entry.get("sha256"), digest)
        _check_equal(
            report,
            manifest_path,
            f"coefficients.{name}.canonical_sha256",
            entry.get("canonical_sha256"),
            digest,
        )
        _check_equal(report, manifest_path, f"hashes.{key}", hashes.get(key), digest)
        _check_equal(report, manifest_path, f"artifact_rows.{name}", artifact_rows.get(name), cfg.L)
        if raw_digest is not None:
            _check_equal(report, path, "raw_vs_canonical_sha256", raw_digest, digest)
    return actual_hashes


@dataclass(frozen=True, slots=True)
class _VectorCheck:
    names: tuple[str, ...]
    manifest: dict[str, Any] | None
    manifest_path: Path
    raw_hashes: dict[str, str]


def _vector_directories(root: Path) -> set[str]:
    return {
        path.name
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".") and not path.is_symlink()
    } if root.is_dir() else set()


def check_vectors(
    artifacts_dir: str | Path,
    coeff_hashes: Mapping[str, str],
    paths: ContractPaths | None,
    report: CheckReport,
    *,
    output_subdir: str = "golden",
    schema_dir: Path | None = None,
) -> _VectorCheck:
    """Check every declared vector and all raw/canonical hash edges."""

    root = Path(artifacts_dir)
    schemas = schema_dir or _schema_dir(paths=paths, schemas_dir=None, artifacts_dir=root)
    vector_root = root / "test_vectors"
    output_root = root / output_subdir
    manifest_path = vector_root / "test_vectors.json"
    manifest = _schema_check(manifest_path, "test_vectors", schemas, report)
    if manifest is None:
        return _VectorCheck((), None, manifest_path, {})
    entries = manifest.get("vectors")
    if not isinstance(entries, list):
        report.add_issue(manifest_path, "vectors", "vectors must be an array")
        return _VectorCheck((), manifest, manifest_path, {})

    names: list[str] = []
    by_name: dict[str, dict[str, Any]] = {}
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict):
            report.add_issue(manifest_path, "vectors", f"entry {ordinal} is not an object")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            report.add_issue(manifest_path, "vectors", f"entry {ordinal} has invalid name")
            continue
        if name in by_name:
            report.add_issue(manifest_path, "vectors", f"duplicate vector name {name!r}")
            continue
        by_name[name] = entry
        names.append(name)
    expected_names = set(names)
    _check_equal(
        report,
        vector_root,
        "test vector directory set",
        _vector_directories(vector_root),
        expected_names,
    )
    _check_equal(
        report,
        output_root,
        f"{output_subdir} directory set",
        _vector_directories(output_root),
        expected_names,
    )

    all_raw_hashes: dict[str, str] = {}
    for name in names:
        report.checked["vectors"] += 1
        entry = by_name[name]
        vdir = vector_root / name
        odir = output_root / name
        config_path = vdir / "config.json"
        metrics_path = odir / "metrics.json"
        config = _schema_check(config_path, "vector_config", schemas, report)
        metrics = _schema_check(metrics_path, "metrics", schemas, report)
        if config is None or metrics is None:
            continue
        try:
            ns = int(entry.get("Ns"))
            geometry = cfg.full_tail_geometry(ns)
        except Exception as exc:
            report.add_issue(manifest_path, "geometry", f"{name}: {exc}")
            continue
        requires_bin = bool(entry.get("requires_bin_stats", False))
        rows = config.get("artifact_rows")
        if not isinstance(rows, dict):
            report.add_issue(config_path, "artifact_rows", "artifact_rows must be an object")
            continue
        expected_rows = cfg.artifact_rows_for_vector(ns, include_bin_stats=requires_bin)
        _check_equal(report, config_path, "artifact_rows", rows, expected_rows)
        _check_equal(report, config_path, "configuration", config.get("configuration"), metrics.get("configuration"))
        _check_equal(report, config_path, "contract", config.get("contract"), metrics.get("contract"))
        _check_equal(report, config_path, "widths", config.get("widths"), metrics.get("widths"))
        _check_equal(report, config_path, "hashes", config.get("hashes"), metrics.get("hashes"))
        _check_equal(report, config_path, "vector_name", config.get("vector_name"), name)
        _check_equal(report, metrics_path, "vector_name", metrics.get("vector_name"), name)
        entry_config_edges = {
            "Ns": config.get("configuration", {}).get("Ns"),
            "THR2": config.get("configuration", {}).get("THR2"),
            "PROTECT_DC": config.get("configuration", {}).get("PROTECT_DC"),
            "PROTECT_NYQ": config.get("configuration", {}).get("PROTECT_NYQ"),
            "tail_policy": config.get("contract", {}).get("tail_policy"),
            "rounding": config.get("contract", {}).get("rounding_mode"),
        }
        for field_name, config_value in entry_config_edges.items():
            _check_equal(
                report,
                manifest_path,
                f"{name}.{field_name}/config",
                entry.get(field_name),
                config_value,
            )
        _check_equal(
            report,
            config_path,
            "configuration.Ns",
            config.get("configuration", {}).get("Ns"),
            geometry.ns,
        )
        _check_equal(
            report,
            config_path,
            "configuration.Ny",
            config.get("configuration", {}).get("Ny"),
            geometry.ny,
        )
        _check_equal(
            report,
            config_path,
            "configuration.frames",
            config.get("configuration", {}).get("frames"),
            geometry.frames,
        )

        x_path = vdir / "x_in.memh"
        y_path = odir / "y_out.memh"
        frame_path = odir / "frame_stats.csv"
        bin_path = odir / "bin_stats.csv"
        try:
            x_hash = check_memh(
                x_path,
                contract_for_kind("x_in", rows=geometry.ns),
                report=report,
            )
            y_hash = check_memh(
                y_path,
                contract_for_kind("y_out", rows=geometry.ny),
                report=report,
            )
        except Exception as exc:
            report.add_issue(vdir, "stream_memh", str(exc))
            continue
        stream_hashes = config.get("stream_hashes", {})
        metric_stream_hashes = metrics.get("stream_hashes", {})
        _check_equal(report, manifest_path, f"{name}.x_in_sha256", entry.get("x_in_sha256"), x_hash)
        _check_equal(report, manifest_path, f"{name}.y_out_sha256", entry.get("y_out_sha256"), y_hash)
        _check_equal(report, config_path, "stream_hashes.x_in_sha256", stream_hashes.get("x_in_sha256"), x_hash)
        _check_equal(report, config_path, "stream_hashes.y_out_sha256", stream_hashes.get("y_out_sha256"), y_hash)
        _check_equal(
            report,
            metrics_path,
            "stream_hashes.x_in_sha256",
            metric_stream_hashes.get("x_in_sha256"),
            x_hash,
        )
        _check_equal(
            report,
            metrics_path,
            "stream_hashes.y_out_sha256",
            metric_stream_hashes.get("y_out_sha256"),
            y_hash,
        )
        for key, value in coeff_hashes.items():
            _check_equal(report, config_path, f"hashes.{key}", config.get("hashes", {}).get(key), value)
            _check_equal(report, metrics_path, f"hashes.{key}", metrics.get("hashes", {}).get(key), value)

        try:
            frame_result = csv_io.read_frame_stats(frame_path, expected_rows=geometry.frames)
            report.checked["csv"] += 1
            mismatches = csv_io.cross_check_frame_stats_metrics(frame_result.rows, metrics)
            for mismatch in mismatches:
                report.add_issue(frame_path, "metrics_cross_check", mismatch)
        except Exception as exc:
            report.add_issue(frame_path, "frame_stats", str(exc))
        if requires_bin:
            try:
                bin_result = csv_io.read_bin_stats(
                    bin_path,
                    expected_rows=geometry.bin_stats_rows,
                )
                report.checked["csv"] += 1
                for ordinal, row in enumerate(bin_result.rows):
                    expected_pair = (
                        ordinal // cfg.UNIQUE_BINS,
                        ordinal % cfg.UNIQUE_BINS,
                    )
                    actual_pair = (row["frame_idx"], row["bin_idx"])
                    if actual_pair != expected_pair:
                        report.add_issue(
                            bin_path,
                            "bin_order",
                            f"row {ordinal}: expected {expected_pair}, got {actual_pair}",
                        )
                        break
            except Exception as exc:
                report.add_issue(bin_path, "bin_stats", str(exc))
        elif bin_path.exists():
            report.add_issue(bin_path, "unexpected_artifact", "bin_stats.csv is not declared")

        raw_targets = {
            "config_sha256": config_path,
            "metrics_sha256": metrics_path,
            "frame_stats_sha256": frame_path,
        }
        if requires_bin:
            raw_targets["bin_stats_sha256"] = bin_path
        for field_name, target in raw_targets.items():
            digest = _raw_hash(target, report)
            if digest is None:
                continue
            _check_equal(report, manifest_path, f"{name}.{field_name}", entry.get(field_name), digest)
            logical = (
                f"artifacts/test_vectors/{name}/config.json"
                if field_name == "config_sha256"
                else f"artifacts/{output_subdir}/{name}/"
                + {
                    "metrics_sha256": "metrics.json",
                    "frame_stats_sha256": "frame_stats.csv",
                    "bin_stats_sha256": "bin_stats.csv",
                }[field_name]
            )
            all_raw_hashes[logical] = digest
        all_raw_hashes[f"artifacts/test_vectors/{name}/x_in.memh"] = x_hash
        all_raw_hashes[f"artifacts/{output_subdir}/{name}/y_out.memh"] = y_hash

    return _VectorCheck(tuple(names), manifest, manifest_path, all_raw_hashes)


def check_optional_manifests(
    artifacts_dir: str | Path,
    paths: ContractPaths,
    report: CheckReport,
) -> None:
    """Backward-compatible name; manifests are required and fully checked."""

    _ = paths
    root = Path(artifacts_dir)
    required = (
        root / "manifests" / "quality_bounds.json",
        root / "manifests" / "artifact_index.json",
        root / "manifests" / "frozen_release_manifest.json",
    )
    for path in required:
        if not path.is_file():
            report.add_issue(path, "required_manifest", "required release manifest is missing")


def _check_core_config(
    artifacts_dir: Path,
    schema_dir: Path,
    report: CheckReport,
) -> dict[str, Any] | None:
    path = artifacts_dir / "manifests" / "core_config_snapshot.json"
    obj = _schema_check(path, "core_config", schema_dir, report)
    if obj is not None:
        _check_equal(report, path, "generated_core_config_snapshot", obj, cfg.core_config_payload())
    return obj


def _check_quality_bounds(
    artifacts_dir: Path,
    schema_dir: Path,
    vectors: _VectorCheck,
    coeff_hashes: Mapping[str, str],
    output_subdir: str,
    report: CheckReport,
) -> dict[str, Any] | None:
    path = artifacts_dir / "manifests" / "quality_bounds.json"
    obj = _schema_check(path, "quality_bounds", schema_dir, report)
    if obj is None:
        return None
    _check_equal(report, path, "hashes", obj.get("hashes"), dict(coeff_hashes))
    bounds = obj.get("bounds")
    if not isinstance(bounds, dict):
        report.add_issue(path, "bounds", "bounds must be an object")
        return obj
    _check_equal(report, path, "bound vector set", set(bounds), set(vectors.names))
    by_name = {
        item.get("name"): item
        for item in (vectors.manifest or {}).get("vectors", [])
        if isinstance(item, dict)
    }
    for name in vectors.names:
        bound = bounds.get(name)
        item = by_name.get(name)
        if not isinstance(bound, dict) or not isinstance(item, dict):
            continue
        _check_equal(report, path, f"bounds.{name}.x_in_sha256", bound.get("x_in_sha256"), item.get("x_in_sha256"))
        _check_equal(report, path, f"bounds.{name}.y_out_sha256", bound.get("y_out_sha256"), item.get("y_out_sha256"))
        metrics_path = artifacts_dir / output_subdir / name / "metrics.json"
        try:
            metrics = manifests.read_json(metrics_path)
        except Exception as exc:
            report.add_issue(metrics_path, "strict_json", str(exc))
            continue
        errors = metrics.get("time_domain_errors", {})
        for field_name in ("max_abs_err", "sum_sq_err", "error_sample_count"):
            _check_equal(
                report,
                path,
                f"bounds.{name}.{field_name}",
                bound.get(field_name),
                errors.get(field_name),
            )
    return obj


def _artifact_role(logical: str, output_subdir: str) -> tuple[str, str | None]:
    parts = PurePosixPath(logical).parts
    name = parts[-1]
    vector: str | None = None
    if len(parts) >= 4 and parts[1] == "test_vectors" and name != "test_vectors.json":
        vector = parts[2]
    if len(parts) >= 4 and parts[1] == output_subdir:
        vector = parts[2]
    if parts[1:3] == ("coefficients", name) and name.endswith(".memh"):
        return "coefficient", None
    if name == "x_in.memh":
        return "test_vector_input", vector
    if name == "y_out.memh":
        return "golden_output", vector
    if name == "config.json":
        return "configuration", vector
    if name in {"metrics.json", "frame_stats.csv", "bin_stats.csv"}:
        return "statistics", vector
    if "manifests" in parts or name in {"coeff_manifest.json", "test_vectors.json"}:
        return "manifest", vector
    return "debug", vector


def _expected_schema_name(logical: str, output_subdir: str) -> str | None:
    fixed = {
        "artifacts/coefficients/coeff_manifest.json": "coeff_manifest",
        "artifacts/manifests/artifact_index.json": "artifact_index",
        "artifacts/manifests/core_config_snapshot.json": "core_config",
        "artifacts/manifests/frozen_release_manifest.json": (
            "frozen_release_manifest"
        ),
        "artifacts/manifests/quality_bounds.json": "quality_bounds",
        "artifacts/manifests/reference_import_manifest.json": (
            "reference_import_manifest"
        ),
        "artifacts/test_vectors/test_vectors.json": "test_vectors",
    }
    if logical in fixed:
        return fixed[logical]
    parts = PurePosixPath(logical).parts
    if (
        len(parts) == 4
        and parts[:2] == ("artifacts", "test_vectors")
        and parts[-1] == "config.json"
    ):
        return "vector_config"
    if (
        len(parts) == 4
        and parts[:2] == ("artifacts", output_subdir)
        and parts[-1] == "metrics.json"
    ):
        return "metrics"
    return None


def _expected_entry(
    logical: str,
    physical: Path,
    output_subdir: str,
    schema_dir: Path,
    report: CheckReport,
) -> dict[str, Any] | None:
    digest = _raw_hash(physical, report)
    if digest is None:
        return None
    suffix = physical.suffix.lower()
    role, vector = _artifact_role(logical, output_subdir)
    expected: dict[str, Any] = {
        "path": logical,
        "role": role,
        "artifact_type": suffix.lstrip("."),
        "sha256": digest,
        "canonicalized": suffix in {".memh", ".csv"},
        "required": True,
    }
    if vector is not None:
        expected["vector_name"] = vector
    if suffix == ".json":
        schema_name = _expected_schema_name(logical, output_subdir)
        if schema_name is None:
            report.add_issue(
                physical,
                "json_contract",
                f"unknown JSON artifact path has no approved schema: {logical}",
            )
            return None
        if _schema_check(physical, schema_name, schema_dir, report) is None:
            return None
        expected["schema_ref"] = f"spec/schemas/{SCHEMA_FILES[schema_name]}"
        expected["content_contract"] = "json_schema_validated"
    elif suffix == ".csv":
        try:
            if physical.name == "frame_stats.csv":
                result = csv_io.read_frame_stats(physical)
            elif physical.name == "bin_stats.csv":
                result = csv_io.read_bin_stats(physical)
            else:
                report.add_issue(physical, "csv", "unknown CSV artifact")
                return None
            expected["rows"] = result.data_rows
            expected["content_contract"] = "lf_csv_exact_header"
        except Exception as exc:
            report.add_issue(physical, "csv", str(exc))
            return None
    elif suffix == ".memh":
        try:
            contract = infer_contract(physical)
            parsed = read_memh(physical, contract)
            canonical = canonical_memh_file_hash(
                physical,
                MemhContract(contract.width_bits, contract.signed, parsed.rows, contract.kind),
            )
        except Exception as exc:
            report.add_issue(physical, "memh", str(exc))
            return None
        expected.update(
            {
                "width_bits": contract.width_bits,
                "signed": contract.signed,
                "rows": parsed.rows,
                "canonical_sha256": canonical,
                "content_contract": "fixed_width_lowercase_hex_lf",
            }
        )
    return expected


def _inventory_paths(artifacts_dir: Path) -> set[str]:
    result: set[str] = set()
    for path in artifacts_dir.rglob("*"):
        logical = f"artifacts/{path.relative_to(artifacts_dir).as_posix()}"
        if (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in SUPPORTED_ARTIFACT_SUFFIXES
            and logical not in RELEASE_MANIFEST_PATHS
        ):
            result.add(logical)
    return result


def _entry_map(
    entries: Any,
    owner: Path,
    report: CheckReport,
    *,
    counter: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(entries, list):
        report.add_issue(owner, "entries", "artifacts must be an array")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict):
            report.add_issue(owner, "entries", f"entry {ordinal} is not an object")
            continue
        logical = entry.get("path")
        if not isinstance(logical, str):
            report.add_issue(owner, "entries", f"entry {ordinal} has invalid path")
            continue
        if logical in result:
            report.add_issue(owner, "entries", f"duplicate artifact path {logical!r}")
            continue
        result[logical] = entry
        report.checked[counter] += 1
    return result


def _compare_entry(
    owner: Path,
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    report: CheckReport,
) -> None:
    for key, expected_value in expected.items():
        _check_equal(report, owner, f"{actual.get('path')}.{key}", actual.get(key), expected_value)
    if not isinstance(actual.get("producer"), str) or not actual.get("producer"):
        report.add_issue(owner, "producer", f"{actual.get('path')}: producer must be nonempty")


def _check_artifact_index(
    artifacts_dir: Path,
    schema_dir: Path,
    output_subdir: str,
    report: CheckReport,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    path = artifacts_dir / "manifests" / "artifact_index.json"
    obj = _schema_check(path, "artifact_index", schema_dir, report)
    if obj is None:
        return None, {}
    named_hashes = {
        "core_config_sha256": artifacts_dir / "manifests" / "core_config_snapshot.json",
        "coeff_manifest_sha256": artifacts_dir / "coefficients" / "coeff_manifest.json",
        "test_vectors_sha256": artifacts_dir / "test_vectors" / "test_vectors.json",
        "quality_bounds_sha256": artifacts_dir / "manifests" / "quality_bounds.json",
    }
    for field_name, target in named_hashes.items():
        digest = _raw_hash(target, report)
        if digest is not None:
            _check_equal(report, path, field_name, obj.get(field_name), digest)

    entries = _entry_map(obj.get("artifacts"), path, report, counter="index_entries")
    inventory = _inventory_paths(artifacts_dir)
    _check_equal(report, path, "complete artifact inventory", set(entries), inventory)
    for logical, entry in entries.items():
        physical = _logical_path(artifacts_dir, logical, path, report)
        if physical is None:
            continue
        expected = _expected_entry(
            logical,
            physical,
            output_subdir,
            schema_dir,
            report,
        )
        if expected is not None:
            _compare_entry(path, entry, expected, report)
    return obj, entries


def _check_frozen_release(
    artifacts_dir: Path,
    schema_dir: Path,
    output_subdir: str,
    index_manifest: Mapping[str, Any],
    index_entries: Mapping[str, Mapping[str, Any]],
    report: CheckReport,
) -> dict[str, Any] | None:
    path = artifacts_dir / "manifests" / "frozen_release_manifest.json"
    obj = _schema_check(path, "frozen_release_manifest", schema_dir, report)
    if obj is None:
        return None
    for field_name in ("release_name", "spec_revision", "created_utc"):
        _check_equal(
            report,
            path,
            f"release/index metadata equality {field_name}",
            obj.get(field_name),
            index_manifest.get(field_name),
        )
    named_hashes = {
        "core_config_sha256": artifacts_dir / "manifests" / "core_config_snapshot.json",
        "coeff_manifest_sha256": artifacts_dir / "coefficients" / "coeff_manifest.json",
        "test_vectors_sha256": artifacts_dir / "test_vectors" / "test_vectors.json",
        "quality_bounds_sha256": artifacts_dir / "manifests" / "quality_bounds.json",
        "artifact_index_sha256": artifacts_dir / "manifests" / "artifact_index.json",
    }
    manifest_hashes = obj.get("manifest_hashes")
    if not isinstance(manifest_hashes, dict):
        report.add_issue(path, "manifest_hashes", "manifest_hashes must be an object")
        manifest_hashes = {}
    for field_name, target in named_hashes.items():
        digest = _raw_hash(target, report)
        if digest is not None:
            _check_equal(report, path, f"manifest_hashes.{field_name}", manifest_hashes.get(field_name), digest)

    entries = _entry_map(obj.get("artifacts"), path, report, counter="release_entries")
    index_logical = "artifacts/manifests/artifact_index.json"
    expected_paths = set(index_entries) | {index_logical}
    _check_equal(report, path, "release/index entry set", set(entries), expected_paths)
    for logical, entry in entries.items():
        physical = _logical_path(artifacts_dir, logical, path, report)
        if physical is None:
            continue
        expected = _expected_entry(
            logical,
            physical,
            output_subdir,
            schema_dir,
            report,
        )
        if expected is not None:
            _compare_entry(path, entry, expected, report)
        if logical in index_entries:
            # The release and index must carry the same authenticated metadata.
            _check_equal(
                report,
                path,
                f"release/index entry equality {logical}",
                entry,
                index_entries[logical],
            )
    return obj


def _detect_output_subdir(artifacts_dir: Path, requested: str | None, report: CheckReport) -> str:
    if requested is not None:
        if requested not in {"golden", "reference_outputs"}:
            report.add_issue(artifacts_dir, "output_subdir", f"unsupported output subdir {requested!r}")
        return requested
    present = [
        name
        for name in ("golden", "reference_outputs")
        if (artifacts_dir / name).is_dir()
        and any(path.is_dir() for path in (artifacts_dir / name).iterdir())
    ]
    if len(present) != 1:
        report.add_issue(
            artifacts_dir,
            "output_subdir",
            f"expected exactly one populated output namespace, got {present}",
        )
        return present[0] if present else "golden"
    return present[0]


def _source_root_from_schema_dir(schema_dir: Path) -> Path | None:
    try:
        candidate = schema_dir.resolve().parents[1]
    except IndexError:
        return None
    if (candidate / "tools" / "gen_coeffs.py").is_file():
        return candidate
    return None


def _preflight_artifact_tree(root: Path, report: CheckReport) -> bool:
    """Reject unsafe tree nodes before any parser is allowed to follow them."""

    ok = True
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        report.add_issue(root, "artifact_tree_node", str(exc))
        return False
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        report.add_issue(
            root,
            "artifact_tree_node",
            "artifact root must be a non-symlink directory",
        )
        return False

    observed_gitkeep: set[str] = set()
    portable_paths: dict[str, str] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        path_error = _portable_relative_path_error(relative)
        if path_error is not None:
            report.add_issue(path, "artifact_tree_path", path_error)
            ok = False
            continue
        portable_key = unicodedata.normalize("NFC", relative).casefold()
        previous = portable_paths.get(portable_key)
        if previous is not None:
            report.add_issue(
                path,
                "artifact_tree_collision",
                f"portable path collision: {previous!r}, {relative!r}",
            )
            ok = False
            continue
        portable_paths[portable_key] = relative
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            report.add_issue(path, "artifact_tree_node", str(exc))
            ok = False
            continue
        if stat.S_ISLNK(mode):
            report.add_issue(
                path,
                "artifact_tree_symlink",
                "symlinks are forbidden anywhere in the artifact tree",
            )
            ok = False
        elif stat.S_ISDIR(mode):
            continue
        elif stat.S_ISREG(mode):
            if path.name == ".gitkeep":
                observed_gitkeep.add(relative)
                if path.stat().st_size != 0:
                    report.add_issue(
                        path,
                        "artifact_tree_gitkeep",
                        ".gitkeep placeholders must be exactly zero bytes",
                    )
                    ok = False
            elif path.suffix.lower() not in SUPPORTED_ARTIFACT_SUFFIXES:
                report.add_issue(
                    path,
                    "artifact_tree_file_type",
                    "unsupported regular file in artifact tree",
                )
                ok = False
        else:
            report.add_issue(
                path,
                "artifact_tree_special",
                "special files are forbidden anywhere in the artifact tree",
            )
            ok = False
    if observed_gitkeep and observed_gitkeep != PROMOTED_TREE_GITKEEP_PATHS:
        report.add_issue(
            root,
            "artifact_tree_gitkeep",
            "the optional promoted-tree .gitkeep set must match the fixed layout: "
            f"got {sorted(observed_gitkeep)}",
        )
        ok = False
    return ok


def check_artifact_tree(
    artifacts_dir: str | Path,
    *,
    paths: ContractPaths | None = None,
    schemas_dir: str | Path | None = None,
    output_subdir: str | None = None,
    source_root: str | Path | None = None,
    require_frozen: bool = True,
    fail_fast: bool = False,
) -> CheckReport:
    """Check one complete embedded or promoted T-RECAP artifact tree."""

    root = Path(artifacts_dir)
    report = CheckReport(artifacts_dir=root)
    if not root.is_dir():
        report.add_issue(root, "artifacts_dir", "artifact directory is missing")
        if fail_fast:
            report.raise_for_errors()
        return report
    if not _preflight_artifact_tree(root, report):
        if fail_fast:
            report.raise_for_errors()
        return report
    schemas = _schema_dir(paths=paths, schemas_dir=schemas_dir, artifacts_dir=root)
    outputs = _detect_output_subdir(root, output_subdir, report)
    resolved_source_root = (
        Path(source_root)
        if source_root is not None
        else _source_root_from_schema_dir(schemas)
    )
    try:
        coeff_hashes = check_coefficients(
            root,
            paths,
            report,
            schema_dir=schemas,
        )
        vectors = check_vectors(
            root,
            coeff_hashes,
            paths,
            report,
            output_subdir=outputs,
            schema_dir=schemas,
        )
        _verify_generator_source_hashes(
            resolved_source_root,
            manifests.read_json(root / "coefficients" / "coeff_manifest.json"),
            vectors.manifest,
            report,
            root / "coefficients" / "coeff_manifest.json",
            vectors.manifest_path,
        )
        _check_core_config(root, schemas, report)
        _check_quality_bounds(
            root,
            schemas,
            vectors,
            coeff_hashes,
            outputs,
            report,
        )
        if require_frozen:
            index_manifest, index_entries = _check_artifact_index(
                root,
                schemas,
                outputs,
                report,
            )
            _check_frozen_release(
                root,
                schemas,
                outputs,
                index_manifest or {},
                index_entries,
                report,
            )
        # Explicit content/pre-freeze mode deliberately does not authenticate
        # an existing index or release.  Release generators must always follow
        # it with the default frozen check after writing both manifests.
    except Exception as exc:  # Defensive boundary: never turn a crash into success.
        report.add_issue(root, "artifact_tree", f"{type(exc).__name__}: {exc}")
    if fail_fast:
        report.raise_for_errors()
    return report


def _tree_digest(records: Iterable[Mapping[str, Any]], *, path_key: str) -> str:
    """Match the importer's binary, domain-separated tree digest exactly."""

    digest = hashlib.sha256()
    digest.update(b"TRECAP_REFERENCE_IMPORT_TREE_V1\0")
    for record in sorted(records, key=lambda item: str(item[path_key])):
        path_bytes = str(record[path_key]).encode("utf-8")
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(int(record["size_bytes"]).to_bytes(8, "big"))
        digest.update(bytes.fromhex(str(record["sha256"])))
    return digest.hexdigest()


def _safe_repo_file(
    repo: Path,
    logical: Any,
    owner: Path,
    report: CheckReport,
    *,
    check: str,
) -> Path | None:
    """Resolve a manifest path without following a symlink out of the repo."""

    path_error = _portable_relative_path_error(logical)
    if path_error is not None or not isinstance(logical, str):
        report.add_issue(
            owner,
            check,
            f"unsafe repository-relative path {logical!r}: {path_error}",
        )
        return None
    pure = PurePosixPath(logical)

    target = repo.joinpath(*pure.parts)
    current = repo
    for part in pure.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            report.add_issue(owner, check, f"missing file {logical!r}")
            return None
        except OSError as exc:
            report.add_issue(owner, check, f"cannot stat {logical!r}: {exc}")
            return None
        if stat.S_ISLNK(mode):
            report.add_issue(owner, check, f"symlink forbidden in path {logical!r}")
            return None
    try:
        target.resolve(strict=True).relative_to(repo.resolve(strict=True))
    except (OSError, ValueError) as exc:
        report.add_issue(owner, check, f"path escapes repository {logical!r}: {exc}")
        return None
    if not target.is_file():
        report.add_issue(owner, check, f"not a regular file: {logical!r}")
        return None
    return target


def _canonical_json_hash(path: Path, report: CheckReport) -> str | None:
    try:
        value = manifests.read_json(path)
        payload = (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
            + b"\n"
        )
    except Exception as exc:
        report.add_issue(path, "promotion_map", str(exc))
        return None
    return hashlib.sha256(payload).hexdigest()


def _portable_relative_path_error(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return "path must be a nonempty string"
    if "\\" in value or "\x00" in value:
        return "backslash/NUL is forbidden"
    if ntpath.splitdrive(value)[0] or value.startswith(("/", "//")):
        return "absolute, drive-qualified, and UNC paths are forbidden"
    if unicodedata.normalize("NFC", value) != value:
        return "path must already be Unicode-NFC canonical"
    if any(
        ord(character) < 32
        or ord(character) == 127
        or unicodedata.category(character) in {"Cc", "Cf"}
        for character in value
    ):
        return "control characters are forbidden"
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        return "path is not canonical repository-relative POSIX form"
    for component in pure.parts:
        if component.endswith((" ", ".")):
            return "trailing dot/space is not portable"
        if any(character in WINDOWS_FORBIDDEN for character in component):
            return "Windows-forbidden path character"
        if len(component.encode("utf-8")) > 255:
            return "path component exceeds 255 UTF-8 bytes"
        stem = component.split(".", maxsplit=1)[0].upper()
        if stem in WINDOWS_RESERVED:
            return f"Windows-reserved component {component!r}"
    return None


def _validate_promotion_map(
    value: Mapping[str, Any],
    *,
    reference_root: str,
    owner: Path,
    report: CheckReport,
) -> set[tuple[str, str]]:
    expected_top = {"schema", "promotions"}
    if set(value) != expected_top:
        report.add_issue(
            owner,
            "promotion_map",
            f"top-level keys must be exactly {sorted(expected_top)}",
        )
    if value.get("schema") != "trecap_phase2_reference_promotion_map_v1":
        report.add_issue(owner, "promotion_map", "promotion-map schema tag mismatch")
    rows = value.get("promotions")
    if not isinstance(rows, list):
        report.add_issue(owner, "promotion_map", "promotions must be an array")
        return set()

    expected: set[tuple[str, str]] = set()
    portable_destinations: dict[str, str] = {}
    destination_keys: list[tuple[str, str]] = []
    for ordinal, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {
            "source_path",
            "destination_path",
        }:
            report.add_issue(
                owner,
                "promotion_map",
                f"promotions[{ordinal}] must contain only source_path/destination_path",
            )
            continue
        source = row.get("source_path")
        destination = row.get("destination_path")
        source_error = _portable_relative_path_error(source)
        destination_error = _portable_relative_path_error(destination)
        if source_error is not None:
            report.add_issue(
                owner,
                "promotion_map",
                f"promotions[{ordinal}].source_path: {source_error}",
            )
            continue
        if destination_error is not None:
            report.add_issue(
                owner,
                "promotion_map",
                f"promotions[{ordinal}].destination_path: {destination_error}",
            )
            continue
        assert isinstance(source, str)
        assert isinstance(destination, str)
        if PurePosixPath(destination).parts[0] not in {"artifacts", "spec"}:
            report.add_issue(
                owner,
                "promotion_map",
                f"destination must be under artifacts/ or spec/: {destination!r}",
            )
            continue
        if destination == "artifacts/manifests/reference_import_manifest.json":
            report.add_issue(
                owner,
                "promotion_map",
                "generated import manifest cannot be a promotion destination",
            )
            continue
        pair = (
            (PurePosixPath(reference_root) / source).as_posix(),
            destination,
        )
        if pair in expected:
            report.add_issue(owner, "promotion_map", f"duplicate promotion {pair!r}")
            continue
        portable_key = unicodedata.normalize("NFC", destination).casefold()
        previous = portable_destinations.get(portable_key)
        if previous is not None:
            report.add_issue(
                owner,
                "promotion_map",
                f"portable destination collision: {previous!r}, {destination!r}",
            )
            continue
        portable_destinations[portable_key] = destination
        destination_keys.append((portable_key, destination))
        expected.add(pair)

    destination_keys.sort()
    for (previous_key, previous), (current_key, current) in zip(
        destination_keys,
        destination_keys[1:],
    ):
        if current_key.startswith(previous_key + "/"):
            report.add_issue(
                owner,
                "promotion_map",
                f"destination file/directory prefix conflict: {previous!r}, {current!r}",
            )
    return expected


def _reference_exclusion_reason(relative: str) -> str | None:
    parts = PurePosixPath(relative).parts
    for component in parts:
        if component in EXPECTED_IMPORT_EXCLUDED_DIRECTORIES:
            return f"excluded_directory:{component}"
    if relative in EXPECTED_IMPORT_EXCLUDED_EXACT:
        return f"excluded_exact:{relative}"
    if PurePosixPath(relative).suffix in EXPECTED_IMPORT_EXCLUDED_SUFFIXES:
        return f"excluded_suffix:{PurePosixPath(relative).suffix}"
    return None


def _preflight_reference_tree(
    repo: Path,
    reference_root: Path,
    owner: Path,
    report: CheckReport,
) -> tuple[set[str], set[str]]:
    actual_imported: set[str] = set()
    actual_excluded: set[str] = set()
    try:
        root_mode = reference_root.lstat().st_mode
    except OSError as exc:
        report.add_issue(reference_root, "imported_inventory", str(exc))
        return actual_imported, actual_excluded
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        report.add_issue(
            reference_root,
            "imported_inventory",
            "reference root must be a non-symlink directory",
        )
        return actual_imported, actual_excluded

    max_entries = int(EXPECTED_IMPORT_RESOURCE_CAPS["max_entries"])
    max_file_bytes = int(EXPECTED_IMPORT_RESOURCE_CAPS["max_file_bytes"])
    max_total_bytes = int(EXPECTED_IMPORT_RESOURCE_CAPS["max_total_bytes"])
    entry_count = 0
    total_bytes = 0
    portable_paths: dict[str, str] = {}
    stack = [reference_root]

    while stack:
        directory = stack.pop()
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            report.add_issue(directory, "imported_inventory", str(exc))
            continue
        for child in children:
            entry_count += 1
            child_path = Path(child.path)
            if entry_count > max_entries:
                report.add_issue(
                    owner,
                    "imported_inventory_caps",
                    "reference tree exceeds max_entries",
                )
                return actual_imported, actual_excluded
            relative = child_path.relative_to(reference_root).as_posix()
            path_error = _portable_relative_path_error(relative)
            if path_error is not None:
                report.add_issue(
                    child_path,
                    "imported_inventory_path",
                    path_error,
                )
                continue
            portable_key = unicodedata.normalize("NFC", relative).casefold()
            previous = portable_paths.get(portable_key)
            if previous is not None:
                report.add_issue(
                    child_path,
                    "imported_inventory_collision",
                    f"portable path collision: {previous!r}, {relative!r}",
                )
                continue
            portable_paths[portable_key] = relative
            try:
                mode = child.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                report.add_issue(child_path, "imported_inventory", str(exc))
                continue
            if stat.S_ISLNK(mode):
                report.add_issue(
                    child_path,
                    "imported_inventory_symlink",
                    "symlinks are forbidden in the embedded reference tree",
                )
                continue
            if relative == "import_manifest.json":
                if not stat.S_ISREG(mode):
                    report.add_issue(
                        child_path,
                        "imported_inventory",
                        "reserved import_manifest.json must be a regular file",
                    )
                continue
            if relative.startswith("import_manifest.json/"):
                report.add_issue(
                    child_path,
                    "imported_inventory",
                    "path conflicts with reserved import_manifest.json",
                )
                continue
            if stat.S_ISDIR(mode):
                stack.append(child_path)
                continue
            if not stat.S_ISREG(mode):
                report.add_issue(
                    child_path,
                    "imported_inventory_special",
                    "special files are forbidden in the embedded reference tree",
                )
                continue
            size_bytes = child.stat(follow_symlinks=False).st_size
            if size_bytes > max_file_bytes:
                report.add_issue(
                    child_path,
                    "imported_inventory_caps",
                    "file exceeds max_file_bytes",
                )
                continue
            total_bytes += size_bytes
            if total_bytes > max_total_bytes:
                report.add_issue(
                    owner,
                    "imported_inventory_caps",
                    "reference tree exceeds max_total_bytes",
                )
                return actual_imported, actual_excluded
            logical = child_path.relative_to(repo).as_posix()
            if _reference_exclusion_reason(relative) is None:
                actual_imported.add(logical)
            else:
                actual_excluded.add(logical)
    return actual_imported, actual_excluded


def _canonical_zip_member(raw_name: str) -> tuple[str, bool]:
    if not isinstance(raw_name, str) or not raw_name:
        raise ValueError("ZIP member name must be a nonempty string")
    if "\x00" in raw_name:
        raise ValueError("ZIP member contains NUL")
    if len(raw_name.encode("utf-8")) > MAX_ZIP_MEMBER_NAME_BYTES:
        raise ValueError("ZIP member name exceeds 4096 UTF-8 bytes")
    slash_name = raw_name.replace("\\", "/")
    is_directory = slash_name.endswith("/")
    without_trailing = slash_name[:-1] if is_directory else slash_name
    if without_trailing.endswith("/"):
        raise ValueError("ZIP member has repeated trailing separators")
    parts = without_trailing.split("/")
    canonical_parts: list[str] = []
    for component in parts:
        normalized = unicodedata.normalize("NFC", component)
        component_error = _portable_relative_path_error(normalized)
        if component_error is not None:
            raise ValueError(f"unsafe ZIP member {raw_name!r}: {component_error}")
        if "/" in normalized:
            raise ValueError(f"unsafe ZIP component in {raw_name!r}")
        canonical_parts.append(normalized)
    canonical = "/".join(canonical_parts)
    path_error = _portable_relative_path_error(canonical)
    if path_error is not None:
        raise ValueError(f"unsafe ZIP member {raw_name!r}: {path_error}")
    return canonical, is_directory


def _zip_member_is_directory(
    info: zipfile.ZipInfo,
    directory_from_name: bool,
) -> bool:
    if info.flag_bits & 0x1:
        raise ValueError(f"encrypted ZIP member is forbidden: {info.filename!r}")
    if info.compress_type not in SUPPORTED_ZIP_COMPRESSION:
        raise ValueError(
            f"unsupported ZIP compression method {info.compress_type}: "
            f"{info.filename!r}"
        )
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    unix_type = stat.S_IFMT(unix_mode)
    dos_directory = bool(info.external_attr & 0x10)
    is_directory = directory_from_name or info.is_dir() or dos_directory
    if unix_type == stat.S_IFLNK:
        raise ValueError(f"ZIP symlink is forbidden: {info.filename!r}")
    if unix_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ValueError(f"ZIP special file is forbidden: {info.filename!r}")
    if unix_type == stat.S_IFDIR and not is_directory:
        raise ValueError(f"ZIP file/directory type mismatch: {info.filename!r}")
    if unix_type == stat.S_IFREG and is_directory:
        raise ValueError(f"ZIP directory/regular type mismatch: {info.filename!r}")
    if is_directory and (info.file_size != 0 or info.compress_size != 0):
        raise ValueError(f"ZIP directory has a payload: {info.filename!r}")
    return is_directory


def _zip_member_hash(bundle: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    observed = 0
    with bundle.open(info, "r") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > info.file_size:
                raise ValueError(
                    f"ZIP member expands beyond declared size: {info.filename!r}"
                )
            digest.update(chunk)
    if observed != info.file_size:
        raise ValueError(
            f"ZIP size mismatch for {info.filename!r}: "
            f"{observed} != {info.file_size}"
        )
    return digest.hexdigest()


def _verify_source_zip_records(
    archive: Path,
    source: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    owner: Path,
    report: CheckReport,
) -> None:
    try:
        before = archive.lstat()
        with archive.open("rb") as archive_stream:
            opened = os.fstat(archive_stream.fileno())
            archive_digest = hashlib.sha256()
            while True:
                chunk = archive_stream.read(1024 * 1024)
                if not chunk:
                    break
                archive_digest.update(chunk)
            actual_archive_sha256 = archive_digest.hexdigest()
            if actual_archive_sha256 != source.get("archive_sha256"):
                raise ValueError(
                    "source archive SHA-256 changed or does not match manifest"
                )
            if opened.st_size != source.get("archive_size_bytes"):
                raise ValueError(
                    "source archive size changed or does not match manifest"
                )
            archive_stream.seek(0)
            with zipfile.ZipFile(archive_stream, "r") as bundle:
                infos = bundle.infolist()
                if not infos:
                    raise ValueError("ZIP archive is empty")
                max_entries = int(EXPECTED_IMPORT_RESOURCE_CAPS["max_entries"])
                max_file_bytes = int(
                    EXPECTED_IMPORT_RESOURCE_CAPS["max_file_bytes"]
                )
                max_total_bytes = int(
                    EXPECTED_IMPORT_RESOURCE_CAPS["max_total_bytes"]
                )
                max_ratio = float(
                    EXPECTED_IMPORT_RESOURCE_CAPS["max_compression_ratio"]
                )
                if len(infos) > max_entries:
                    raise ValueError("ZIP exceeds max_entries")

                archive_root = source.get("archive_root")
                root_error = _portable_relative_path_error(archive_root)
                if (
                    root_error is not None
                    or not isinstance(archive_root, str)
                    or "/" in archive_root
                ):
                    raise ValueError(
                        f"invalid archive root {archive_root!r}: {root_error}"
                    )

                exact_seen: dict[str, str] = {}
                portable_seen: dict[str, str] = {}
                header_offsets: set[int] = set()
                file_members: list[str] = []
                preflight: list[
                    tuple[zipfile.ZipInfo, str, str, str, str | None]
                ] = []
                total_uncompressed = 0
                saw_root = False

                for info in infos:
                    raw_name = getattr(info, "orig_filename", info.filename)
                    canonical_name, directory_from_name = _canonical_zip_member(
                        raw_name
                    )
                    is_directory = _zip_member_is_directory(
                        info,
                        directory_from_name,
                    )
                    if info.header_offset in header_offsets:
                        raise ValueError(
                            f"duplicate ZIP local-header offset: {raw_name!r}"
                        )
                    header_offsets.add(info.header_offset)
                    if canonical_name in exact_seen:
                        raise ValueError(
                            "ZIP separator/NFC duplicate: "
                            f"{exact_seen[canonical_name]!r} and {raw_name!r}"
                        )
                    exact_seen[canonical_name] = raw_name
                    portable_key = unicodedata.normalize(
                        "NFC",
                        canonical_name,
                    ).casefold()
                    if portable_key in portable_seen:
                        raise ValueError(
                            "ZIP casefold/Unicode collision: "
                            f"{portable_seen[portable_key]!r} and {raw_name!r}"
                        )
                    portable_seen[portable_key] = raw_name

                    parts = PurePosixPath(canonical_name).parts
                    if not parts or parts[0] != archive_root:
                        raise ValueError(
                            f"ZIP member is outside required root "
                            f"{archive_root!r}: {raw_name!r}"
                        )
                    if len(parts) == 1:
                        if not is_directory:
                            raise ValueError(
                                "archive root entry must be a directory"
                            )
                        saw_root = True
                        continue
                    relative = PurePosixPath(*parts[1:]).as_posix()
                    if relative == "import_manifest.json" or relative.startswith(
                        "import_manifest.json/"
                    ):
                        raise ValueError(
                            "source archive contains reserved generated "
                            "import_manifest.json"
                        )
                    reason = _reference_exclusion_reason(relative)
                    if is_directory:
                        continue
                    if info.file_size < 0 or info.compress_size < 0:
                        raise ValueError(f"negative ZIP size: {raw_name!r}")
                    if info.file_size > max_file_bytes:
                        raise ValueError(
                            f"ZIP member exceeds max_file_bytes: {raw_name!r}"
                        )
                    total_uncompressed += info.file_size
                    if total_uncompressed > max_total_bytes:
                        raise ValueError("ZIP exceeds max_total_bytes")
                    if info.file_size:
                        if info.compress_size == 0:
                            raise ValueError(
                                "nonempty ZIP member has zero compressed size: "
                                f"{raw_name!r}"
                            )
                        if info.file_size / info.compress_size > max_ratio:
                            raise ValueError(
                                "ZIP member exceeds max_compression_ratio: "
                                f"{raw_name!r}"
                            )
                    file_members.append(canonical_name)
                    preflight.append(
                        (info, raw_name, canonical_name, relative, reason)
                    )

                if not saw_root and not preflight:
                    raise ValueError(
                        f"ZIP does not contain archive root {archive_root!r}"
                    )
                sorted_files = sorted(file_members)
                for previous, current in zip(sorted_files, sorted_files[1:]):
                    if current.startswith(previous + "/"):
                        raise ValueError(
                            "ZIP file/directory prefix conflict: "
                            f"{previous!r} and {current!r}"
                        )
                portable_files = sorted(
                    (unicodedata.normalize("NFC", member).casefold(), member)
                    for member in file_members
                )
                for (previous_key, previous), (current_key, current) in zip(
                    portable_files,
                    portable_files[1:],
                ):
                    if current_key.startswith(previous_key + "/"):
                        raise ValueError(
                            "ZIP portable file/directory prefix conflict: "
                            f"{previous!r} and {current!r}"
                        )
                if not any(reason is None for *_prefix, reason in preflight):
                    raise ValueError("ZIP contains no included reference files")

                observed_by_raw: dict[str, dict[str, Any]] = {}
                for info, raw_name, canonical_name, relative, reason in preflight:
                    observed: dict[str, Any] = {
                        "archive_member": canonical_name,
                        "archive_member_raw": raw_name,
                        "class": "[0]",
                        "crc32": f"{info.CRC:08x}",
                        "origin": "source_archive",
                        "path": (REFERENCE_ROOT_PATH / relative).as_posix(),
                        "sha256": _zip_member_hash(bundle, info),
                        "size_bytes": info.file_size,
                    }
                    if reason is not None:
                        observed["reason"] = reason
                    observed_by_raw[raw_name] = observed

                expected_by_raw: dict[str, Mapping[str, Any]] = {}
                for ordinal, record in enumerate(records):
                    raw_name = record.get("archive_member_raw")
                    if not isinstance(raw_name, str):
                        report.add_issue(
                            owner,
                            "source_archive_record",
                            f"record {ordinal} lacks archive_member_raw",
                        )
                        continue
                    if raw_name in expected_by_raw:
                        report.add_issue(
                            owner,
                            "source_archive_record",
                            f"duplicate record for archive member {raw_name!r}",
                        )
                        continue
                    expected_by_raw[raw_name] = record
                _check_equal(
                    report,
                    owner,
                    "complete source archive file inventory",
                    set(expected_by_raw),
                    set(observed_by_raw),
                )
                common_members = sorted(
                    set(expected_by_raw) & set(observed_by_raw)
                )
                for raw_name in common_members:
                    expected_record = expected_by_raw[raw_name]
                    observed_record = observed_by_raw[raw_name]
                    for key, expected_value in observed_record.items():
                        _check_equal(
                            report,
                            owner,
                            f"{raw_name}.{key}",
                            expected_record.get(key),
                            expected_value,
                        )
                    if "reason" not in observed_record and "reason" in expected_record:
                        report.add_issue(
                            owner,
                            "source_archive_record",
                            "included member has unexpected exclusion reason: "
                            f"{raw_name!r}",
                        )

            after = os.fstat(archive_stream.fileno())
            archive_stream.seek(0)
            final_digest = hashlib.sha256()
            while True:
                chunk = archive_stream.read(1024 * 1024)
                if not chunk:
                    break
                final_digest.update(chunk)
            identity_before = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            identity_opened = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            identity_after = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if (
                identity_before != identity_opened
                or identity_opened != identity_after
                or final_digest.hexdigest() != actual_archive_sha256
            ):
                raise ValueError("source archive changed during verification")
    except (
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        NotImplementedError,
    ) as exc:
        report.add_issue(archive, "source_archive_zip", str(exc))


def check_reference_import_manifest(
    repo_root: str | Path,
    manifest_path: str | Path,
    *,
    schemas_dir: str | Path,
    require_verified_source: bool = False,
    source_archive: str | Path | None = None,
    promotion_map_path: str | Path | None = None,
    report: CheckReport | None = None,
) -> CheckReport:
    """Validate v3 vendoring and promotion provenance.

    The current v69 bundle is explicitly allowed to identify itself as an
    unverified embedded proxy.  ``require_verified_source`` turns that status
    into a hard gate and optionally hashes the supplied clean archive.
    """

    repo = Path(repo_root).resolve()
    path = Path(manifest_path)
    if not path.is_absolute():
        path = repo / path
    result = report or CheckReport(repo / "artifacts")
    manifest_file = _safe_repo_file(
        repo,
        path.relative_to(repo).as_posix()
        if path.is_absolute() and path.is_relative_to(repo)
        else path.as_posix(),
        path,
        result,
        check="manifest_path",
    )
    if manifest_file is None:
        return result
    path = manifest_file
    obj = _schema_check(path, "reference_import_manifest", Path(schemas_dir), result)
    if obj is None:
        return result
    if obj.get("schema") != "trecap_phase2_reference_import_manifest_v3":
        result.add_issue(path, "schema_tag", "v3 import manifest is required")
        return result
    internal_logical = (
        PurePosixPath(str(obj.get("reference_root", "sw/reference_model")))
        / "import_manifest.json"
    ).as_posix()
    internal = _safe_repo_file(
        repo,
        internal_logical,
        path,
        result,
        check="manifest_mirror",
    )
    try:
        if internal is not None and path.read_bytes() != internal.read_bytes():
            result.add_issue(path, "manifest_mirror", f"{internal} is not byte-identical")
    except OSError as exc:
        result.add_issue(internal or path, "manifest_mirror", str(exc))

    source = obj.get("source", {})
    status_value = obj.get("provenance_status")
    source_verified = (
        isinstance(source, dict)
        and source.get("kind") == "zip"
        and source.get("verified") is True
        and status_value == "verified_source_archive"
    )
    source_kind_value = source.get("kind") if isinstance(source, dict) else None
    expected_status = {
        "zip": "verified_source_archive",
        "embedded_proxy": "embedded_proxy_unverified_source_archive",
    }.get(source_kind_value)
    if expected_status is not None:
        _check_equal(
            result,
            path,
            "source/provenance status consistency",
            status_value,
            expected_status,
        )
    expected_verified = {"zip": True, "embedded_proxy": False}.get(
        source_kind_value
    )
    if expected_verified is not None:
        _check_equal(
            result,
            path,
            "source.verified",
            source.get("verified") if isinstance(source, dict) else None,
            expected_verified,
        )
    if require_verified_source and not source_verified:
        result.add_issue(
            path,
            "source_provenance",
            f"verified complete source archive required, got {status_value!r}",
        )
    if require_verified_source and source_archive is None:
        result.add_issue(
            path,
            "source_provenance",
            "--require-verified-source also requires --source-archive",
        )
    if isinstance(source, dict) and source.get("kind") == "zip":
        _check_equal(
            result,
            path,
            "source.expected_sha256",
            source.get("expected_sha256"),
            source.get("archive_sha256"),
        )
    elif source_archive is not None:
        result.add_issue(
            path,
            "source_archive",
            "a source archive was supplied for a non-ZIP provenance record",
        )

    policy = obj.get("import_policy")
    if not isinstance(policy, dict):
        result.add_issue(path, "import_policy", "must be an object")
        policy = {}
    expected_policy = dict(EXPECTED_IMPORT_POLICY)
    expected_policy["archive_validation"] = (
        "complete-central-directory-and-full-member-crc"
        if isinstance(source, dict) and source.get("kind") == "zip"
        else "not_applicable_embedded_proxy"
    )
    _check_equal(
        result,
        path,
        "complete fixed import policy",
        policy,
        expected_policy,
    )

    archive: Path | None = None
    if source_archive is not None:
        archive = Path(source_archive)
        if archive.is_symlink() or not archive.is_file():
            result.add_issue(
                archive,
                "source_archive",
                "source archive must be a non-symlink regular file",
            )
            digest = None
        else:
            digest = _raw_hash(archive, result)
        expected = source.get("archive_sha256") if isinstance(source, dict) else None
        if digest is not None:
            _check_equal(result, path, "source.archive_sha256", digest, expected)
        try:
            archive_size = archive.stat().st_size
        except OSError as exc:
            result.add_issue(archive, "source_archive", str(exc))
        else:
            _check_equal(
                result,
                path,
                "source.archive_size_bytes",
                archive_size,
                source.get("archive_size_bytes") if isinstance(source, dict) else None,
            )
        if isinstance(source, dict):
            _check_equal(
                result,
                path,
                "source.archive_name",
                archive.name,
                source.get("archive_name"),
            )

    map_path = (
        Path(promotion_map_path)
        if promotion_map_path is not None
        else repo / "config" / "reference_import_promotions.json"
    )
    if not map_path.is_absolute():
        map_path = repo / map_path
    try:
        map_logical = map_path.relative_to(repo).as_posix()
    except ValueError:
        result.add_issue(
            map_path,
            "promotion_map",
            "promotion map must remain inside the architecture repository",
        )
        safe_map_path = None
    else:
        safe_map_path = _safe_repo_file(
            repo,
            map_logical,
            path,
            result,
            check="promotion_map",
        )
    map_digest = (
        _canonical_json_hash(safe_map_path, result)
        if safe_map_path is not None
        else None
    )
    if map_digest is not None:
        _check_equal(
            result,
            path,
            "promotion_map_sha256",
            obj.get("promotion_map_sha256"),
            map_digest,
        )
    try:
        if safe_map_path is None:
            raise ValueError("promotion map is unavailable")
        promotion_map = manifests.read_json(safe_map_path)
        expected_promotions = _validate_promotion_map(
            promotion_map,
            reference_root=str(obj.get("reference_root", "sw/reference_model")),
            owner=safe_map_path,
            report=result,
        )
    except Exception as exc:
        result.add_issue(map_path, "promotion_map", str(exc))
        expected_promotions = set()

    imported = obj.get("imported_reference_files")
    promoted = obj.get("promoted_root_files")
    excluded = obj.get("excluded_members")
    if not isinstance(imported, list):
        result.add_issue(path, "imported_reference_files", "must be an array")
        imported = []
    if not isinstance(promoted, list):
        result.add_issue(path, "promoted_root_files", "must be an array")
        promoted = []
    if not isinstance(excluded, list):
        result.add_issue(path, "excluded_members", "must be an array")
        excluded = []
    _check_equal(
        result,
        path,
        "imported_reference_file_count",
        obj.get("imported_reference_file_count"),
        len(imported),
    )
    _check_equal(
        result,
        path,
        "promoted_root_file_count",
        obj.get("promoted_root_file_count"),
        len(promoted),
    )
    _check_equal(
        result,
        path,
        "excluded_member_count",
        obj.get("excluded_member_count"),
        len(excluded),
    )

    source_kind = source.get("kind") if isinstance(source, dict) else None
    expected_origin = (
        "source_archive" if source_kind == "zip" else "embedded_proxy"
    )
    reference_root = repo / str(obj.get("reference_root", "sw/reference_model"))
    actual_imported, actual_excluded = _preflight_reference_tree(
        repo,
        reference_root,
        path,
        result,
    )
    seen_imported: set[str] = set()
    imported_by_path: dict[str, Mapping[str, Any]] = {}
    imported_records_valid = True
    for ordinal, entry in enumerate(imported):
        if not isinstance(entry, dict):
            result.add_issue(path, "imported_reference_files", f"entry {ordinal} is not an object")
            imported_records_valid = False
            continue
        relative = entry.get("path")
        path_error = _portable_relative_path_error(relative)
        if path_error is not None or not isinstance(relative, str):
            result.add_issue(
                path,
                "imported_reference_files",
                f"entry {ordinal} has unsafe path {relative!r}: {path_error}",
            )
            imported_records_valid = False
            continue
        if relative in seen_imported:
            result.add_issue(path, "imported_reference_files", f"bad/duplicate path {relative!r}")
            imported_records_valid = False
            continue
        try:
            reference_relative = (
                PurePosixPath(relative).relative_to(REFERENCE_ROOT_PATH).as_posix()
            )
        except ValueError:
            result.add_issue(
                path,
                "imported_reference_files",
                f"path is outside {REFERENCE_ROOT_PATH.as_posix()}: {relative!r}",
            )
            imported_records_valid = False
            continue
        if _reference_exclusion_reason(reference_relative) is not None:
            result.add_issue(
                path,
                "imported_reference_files",
                f"excluded-policy path appears in imported inventory: {relative!r}",
            )
            imported_records_valid = False
        seen_imported.add(relative)
        imported_by_path[relative] = entry
        _check_equal(
            result,
            path,
            f"{relative}.origin",
            entry.get("origin"),
            expected_origin,
        )
        _check_equal(result, path, f"{relative}.class", entry.get("class"), "[0]")
        if source_kind == "zip":
            if (
                not isinstance(entry.get("archive_member"), str)
                or not isinstance(entry.get("archive_member_raw"), str)
                or not isinstance(entry.get("crc32"), str)
                or LOWER_CRC32_RE.fullmatch(str(entry.get("crc32"))) is None
            ):
                result.add_issue(
                    path,
                    "source_archive_record",
                    f"imported record lacks archive metadata: {relative!r}",
                )
                imported_records_valid = False
        else:
            for key in ("archive_member", "archive_member_raw", "crc32"):
                _check_equal(
                    result,
                    path,
                    f"{relative}.{key}",
                    entry.get(key),
                    None,
                )
        if not _check_sha_text(
            result,
            path,
            f"{relative}.sha256",
            entry.get("sha256"),
        ):
            imported_records_valid = False
        size_bytes = entry.get("size_bytes")
        if (
            not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
        ):
            result.add_issue(
                path,
                f"{relative}.size_bytes",
                f"expected a nonnegative integer, got {size_bytes!r}",
            )
            imported_records_valid = False
        physical = _safe_repo_file(
            repo,
            relative,
            path,
            result,
            check="imported_file",
        )
        if physical is None:
            continue
        digest = _raw_hash(physical, result)
        if digest is not None:
            _check_equal(result, path, f"{relative}.sha256", entry.get("sha256"), digest)
        _check_equal(result, path, f"{relative}.size_bytes", entry.get("size_bytes"), physical.stat().st_size)
        result.checked["imported_files"] += 1

    seen_excluded: set[str] = set()
    for ordinal, entry in enumerate(excluded):
        if not isinstance(entry, dict):
            result.add_issue(
                path,
                "excluded_members",
                f"entry {ordinal} is not an object",
            )
            continue
        relative = entry.get("path")
        path_error = _portable_relative_path_error(relative)
        if path_error is not None or not isinstance(relative, str):
            result.add_issue(
                path,
                "excluded_members",
                f"entry {ordinal} has unsafe path {relative!r}: {path_error}",
            )
            continue
        if relative in seen_excluded or relative in seen_imported:
            result.add_issue(
                path,
                "excluded_members",
                f"duplicate/overlapping excluded path {relative!r}",
            )
            continue
        try:
            reference_relative = (
                PurePosixPath(relative).relative_to(REFERENCE_ROOT_PATH).as_posix()
            )
        except ValueError:
            result.add_issue(
                path,
                "excluded_members",
                f"path is outside {REFERENCE_ROOT_PATH.as_posix()}: {relative!r}",
            )
            continue
        expected_reason = _reference_exclusion_reason(reference_relative)
        if expected_reason is None:
            result.add_issue(
                path,
                "excluded_members",
                f"path is not excluded by the fixed policy: {relative!r}",
            )
        else:
            _check_equal(
                result,
                path,
                f"{relative}.reason",
                entry.get("reason"),
                expected_reason,
            )
        seen_excluded.add(relative)
        _check_equal(
            result,
            path,
            f"{relative}.origin",
            entry.get("origin"),
            expected_origin,
        )
        _check_equal(result, path, f"{relative}.class", entry.get("class"), "[0]")
        _check_sha_text(
            result,
            path,
            f"{relative}.sha256",
            entry.get("sha256"),
        )
        size_bytes = entry.get("size_bytes")
        if (
            not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
        ):
            result.add_issue(
                path,
                f"{relative}.size_bytes",
                f"expected a nonnegative integer, got {size_bytes!r}",
            )
        if source_kind == "zip":
            if (
                not isinstance(entry.get("archive_member"), str)
                or not isinstance(entry.get("archive_member_raw"), str)
                or not isinstance(entry.get("crc32"), str)
                or LOWER_CRC32_RE.fullmatch(str(entry.get("crc32"))) is None
            ):
                result.add_issue(
                    path,
                    "source_archive_record",
                    f"excluded record lacks archive metadata: {relative!r}",
                )
        else:
            for key in ("archive_member", "archive_member_raw", "crc32"):
                _check_equal(
                    result,
                    path,
                    f"{relative}.{key}",
                    entry.get(key),
                    None,
                )
            physical = _safe_repo_file(
                repo,
                relative,
                path,
                result,
                check="excluded_file",
            )
            if physical is not None:
                digest = _raw_hash(physical, result)
                if digest is not None:
                    _check_equal(
                        result,
                        path,
                        f"{relative}.sha256",
                        entry.get("sha256"),
                        digest,
                    )
                _check_equal(
                    result,
                    path,
                    f"{relative}.size_bytes",
                    entry.get("size_bytes"),
                    physical.stat().st_size,
                )

    _check_equal(
        result,
        path,
        "complete imported inventory",
        seen_imported,
        actual_imported,
    )
    if source_kind == "embedded_proxy":
        _check_equal(
            result,
            path,
            "complete excluded inventory",
            seen_excluded,
            actual_excluded,
        )
    elif actual_excluded:
        result.add_issue(
            path,
            "complete excluded inventory",
            f"verified ZIP staging tree contains excluded files: {sorted(actual_excluded)}",
        )
    if imported and imported_records_valid:
        try:
            imported_digest = _tree_digest(imported, path_key="path")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            result.add_issue(path, "imported_tree_sha256", str(exc))
        else:
            _check_equal(
                result,
                path,
                "imported_tree_sha256",
                obj.get("imported_tree_sha256"),
                imported_digest,
            )

    if source_kind == "zip" and archive is not None and archive.is_file():
        _verify_source_zip_records(
            archive,
            source if isinstance(source, dict) else {},
            [
                entry
                for entry in (*imported, *excluded)
                if isinstance(entry, Mapping)
            ],
            path,
            result,
        )

    seen_destinations: set[str] = set()
    observed_promotions: set[tuple[str, str]] = set()
    promoted_records_valid = True
    for ordinal, entry in enumerate(promoted):
        if not isinstance(entry, dict):
            result.add_issue(path, "promoted_root_files", f"entry {ordinal} is not an object")
            continue
        source_path = entry.get("source_path")
        destination_path = entry.get("path")
        operation = entry.get("operation")
        if not isinstance(source_path, str) or not isinstance(destination_path, str):
            result.add_issue(path, "promoted_root_files", f"entry {ordinal} has invalid path")
            continue
        if destination_path in seen_destinations:
            result.add_issue(path, "promoted_root_files", f"duplicate destination {destination_path!r}")
            continue
        seen_destinations.add(destination_path)
        observed_promotions.add((source_path, destination_path))
        if not _check_sha_text(
            result,
            path,
            f"{destination_path}.sha256",
            entry.get("sha256"),
        ):
            promoted_records_valid = False
        size_bytes = entry.get("size_bytes")
        if (
            not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
        ):
            result.add_issue(
                path,
                f"{destination_path}.size_bytes",
                f"expected a nonnegative integer, got {size_bytes!r}",
            )
            promoted_records_valid = False
        source_file = _safe_repo_file(
            repo,
            source_path,
            path,
            result,
            check="promotion_source",
        )
        destination_file = _safe_repo_file(
            repo,
            destination_path,
            path,
            result,
            check="promotion_destination",
        )
        if source_file is None or destination_file is None:
            continue
        source_hash = _raw_hash(source_file, result)
        destination_hash = _raw_hash(destination_file, result)
        if destination_hash is not None:
            _check_equal(result, path, f"{destination_path}.sha256", entry.get("sha256"), destination_hash)
        _check_equal(
            result,
            path,
            f"{destination_path}.size_bytes",
            entry.get("size_bytes"),
            destination_file.stat().st_size,
        )
        if operation == "verbatim_copy" and source_hash is not None and destination_hash is not None:
            _check_equal(result, path, f"{destination_path}.verbatim_copy", destination_hash, source_hash)
        elif operation != "verbatim_copy":
            result.add_issue(path, "promotion_operation", f"unsupported operation {operation!r}")
        imported_source = imported_by_path.get(source_path)
        if imported_source is None:
            result.add_issue(
                path,
                "promotion_source",
                f"promotion source is not in imported inventory: {source_path!r}",
            )
        elif source_hash is not None:
            _check_equal(
                result,
                path,
                f"{destination_path}.imported_source_sha256",
                imported_source.get("sha256"),
                source_hash,
            )
        result.checked["promoted_files"] += 1
    _check_equal(
        result,
        path,
        "complete promotion inventory",
        observed_promotions,
        expected_promotions,
    )
    if promoted and promoted_records_valid:
        try:
            promoted_digest = _tree_digest(promoted, path_key="path")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            result.add_issue(path, "promoted_tree_sha256", str(exc))
        else:
            _check_equal(
                result,
                path,
                "promoted_tree_sha256",
                obj.get("promoted_tree_sha256"),
                promoted_digest,
            )
    return result


__all__ = [
    "ArtifactCheckError",
    "CheckIssue",
    "CheckReport",
    "check_artifact_tree",
    "check_coefficients",
    "check_memh",
    "check_optional_manifests",
    "check_reference_import_manifest",
    "check_vectors",
]
