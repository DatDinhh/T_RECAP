# SPDX-License-Identifier: MIT
"""Programmatic artifact checker for the T-RECAP golden repository."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from trecap_golden.contracts.contract_paths import ContractPaths, default_paths
from trecap_golden.generated import trecap_config as cfg

from . import csv_io, manifests
from .hashes import canonical_memh_file_hash
from .memh import MemhContract, contract_for_kind


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
    checked: dict[str, int] = field(default_factory=lambda: {"json": 0, "memh": 0, "csv": 0, "vectors": 0})

    @property
    def ok(self) -> bool:
        return not self.issues

    def add_issue(self, path: str | Path, check: str, message: str, *, severity: str = "error") -> None:
        self.issues.append(CheckIssue(severity, Path(path).as_posix(), check, message))

    def raise_for_errors(self) -> None:
        if self.issues:
            first = self.issues[0]
            raise ArtifactCheckError(f"{first.path}: {first.check}: {first.message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "trecap_artifact_check_report_v1",
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


def _schema_check(path: Path, schema_name: str, paths: ContractPaths, report: CheckReport) -> None:
    # Keep the artifact package checker lightweight and deterministic. Full
    # Draft 2020-12 schema validation remains available through
    # trecap_golden.contracts.schema_validate and make check-schemas. The
    # artifact checker verifies that the JSON object exists, parses, and carries
    # the expected schema tag when the artifact format defines one.
    _ = paths
    try:
        obj = manifests.read_json(path)
    except Exception as exc:  # pragma: no cover - defensive conversion to report issue
        report.add_issue(path, "json", str(exc))
        return
    report.checked["json"] += 1
    expected_tags = {
        "coeff_manifest": "trecap_phase2_coeff_manifest_v1",
        "test_vectors": "trecap_phase2_test_vectors_v1",
        "vector_config": "trecap_phase2_vector_config_v1",
        "metrics": "trecap_phase2_metrics_v1",
        "quality_bounds": "trecap_phase2_quality_bounds_v1",
        "artifact_index": "trecap_phase2_artifact_index_v1",
        "frozen_release_manifest": "trecap_phase2_frozen_release_manifest_v1",
    }
    expected = expected_tags.get(schema_name)
    if expected is not None and obj.get("schema") != expected:
        report.add_issue(path, "json_schema_tag", f"expected schema={expected!r}, got {obj.get('schema')!r}")


def _check_equal(report: CheckReport, path: Path, check: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        report.add_issue(path, check, f"expected {expected!r}, got {actual!r}")


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
            report.add_issue(p, "canonical_sha256", f"expected {expected_sha256}, got {digest}")
    elif expected_sha256 is not None and digest != expected_sha256:
        raise ArtifactCheckError(f"{p}: expected sha256 {expected_sha256}, got {digest}")
    return digest


def check_coefficients(artifacts_dir: str | Path, paths: ContractPaths, report: CheckReport) -> dict[str, str]:
    """Check coefficient memh files and ``coeff_manifest.json``."""

    coeff_dir = Path(artifacts_dir) / "coefficients"
    manifest_path = coeff_dir / "coeff_manifest.json"
    _schema_check(manifest_path, "coeff_manifest", paths, report)
    manifest = manifests.read_json(manifest_path)
    expected_hashes = manifest.get("hashes", {})
    actual_hashes: dict[str, str] = {}
    for key, contract in manifests.coefficient_contracts().items():
        digest = check_memh(coeff_dir / f"{key}.memh", contract, report=report)
        actual_hashes[f"{key}_sha256"] = digest
        _check_equal(report, manifest_path, f"hashes.{key}_sha256", digest, expected_hashes.get(f"{key}_sha256"))
        rows = len((coeff_dir / f"{key}.memh").read_text(encoding="ascii").splitlines())
        _check_equal(report, coeff_dir / f"{key}.memh", "rows", rows, cfg.L)
    return actual_hashes


def _vector_schema_checks(vector: manifests.VectorArtifacts, paths: ContractPaths, report: CheckReport) -> None:
    _schema_check(vector.config, "vector_config", paths, report)
    _schema_check(vector.metrics, "metrics", paths, report)


def check_vector(
    vector: manifests.VectorArtifacts,
    vector_manifest_entry: Mapping[str, Any],
    coeff_hashes: Mapping[str, str],
    paths: ContractPaths,
    report: CheckReport,
) -> None:
    """Check one vector directory pair under ``test_vectors`` and ``golden``."""

    report.checked["vectors"] += 1
    _vector_schema_checks(vector, paths, report)
    config = manifests.read_json(vector.config)
    metrics = manifests.read_json(vector.metrics)
    rows = config.get("artifact_rows", {})
    x_rows = int(rows.get("x_in", vector_manifest_entry.get("Ns", 0)))
    y_rows = int(rows.get("y_out", 0))
    frame_rows = int(rows.get("frame_stats_data_rows", 0))
    x_hash = check_memh(vector.x_in, contract_for_kind("x_in", rows=x_rows), report=report)
    y_hash = check_memh(vector.y_out, contract_for_kind("y_out", rows=y_rows), report=report)
    _check_equal(report, vector.x_in, "manifest.x_in_sha256", x_hash, vector_manifest_entry.get("x_in_sha256"))
    _check_equal(report, vector.y_out, "manifest.y_out_sha256", y_hash, vector_manifest_entry.get("y_out_sha256"))
    _check_equal(report, vector.config, "stream_hashes.x_in_sha256", x_hash, config.get("stream_hashes", {}).get("x_in_sha256"))
    _check_equal(report, vector.config, "stream_hashes.y_out_sha256", y_hash, config.get("stream_hashes", {}).get("y_out_sha256"))
    _check_equal(report, vector.metrics, "stream_hashes.y_out_sha256", y_hash, metrics.get("stream_hashes", {}).get("y_out_sha256"))

    try:
        frame_result = csv_io.read_frame_stats(vector.frame_stats, expected_rows=frame_rows)
        report.checked["csv"] += 1
        mismatches = csv_io.cross_check_frame_stats_metrics(frame_result.rows, metrics)
        for mismatch in mismatches:
            report.add_issue(vector.frame_stats, "metrics_cross_check", mismatch)
    except Exception as exc:  # pragma: no cover - defensive conversion to report issue
        report.add_issue(vector.frame_stats, "frame_stats", str(exc))

    expected_bin_rows = rows.get("bin_stats_data_rows")
    if expected_bin_rows is not None or vector_manifest_entry.get("requires_bin_stats", False):
        try:
            csv_io.read_bin_stats(vector.bin_stats, expected_rows=int(expected_bin_rows or frame_rows * cfg.UNIQUE_BINS))
            report.checked["csv"] += 1
        except Exception as exc:  # pragma: no cover - defensive conversion to report issue
            report.add_issue(vector.bin_stats, "bin_stats", str(exc))

    for key, value in coeff_hashes.items():
        _check_equal(report, vector.config, f"hashes.{key}", config.get("hashes", {}).get(key), value)
        _check_equal(report, vector.metrics, f"hashes.{key}", metrics.get("hashes", {}).get(key), value)


def check_vectors(artifacts_dir: str | Path, coeff_hashes: Mapping[str, str], paths: ContractPaths, report: CheckReport) -> None:
    """Check ``test_vectors.json`` and all declared vectors."""

    root = Path(artifacts_dir)
    manifest_path = root / "test_vectors" / "test_vectors.json"
    _schema_check(manifest_path, "test_vectors", paths, report)
    manifest = manifests.read_json(manifest_path)
    by_name = {entry["name"]: entry for entry in manifests.iter_vector_entries(manifest)}
    for vector in manifests.discover_vector_artifacts(root):
        check_vector(vector, by_name[vector.name], coeff_hashes, paths, report)


def check_optional_manifests(artifacts_dir: str | Path, paths: ContractPaths, report: CheckReport) -> None:
    """Schema-check optional global manifests when present."""

    manifest_dir = Path(artifacts_dir) / "manifests"
    for name, schema_name in {
        "quality_bounds.json": "quality_bounds",
        "artifact_index.json": "artifact_index",
        "frozen_release_manifest.json": "frozen_release_manifest",
    }.items():
        path = manifest_dir / name
        if path.exists():
            _schema_check(path, schema_name, paths, report)


def check_artifact_tree(
    artifacts_dir: str | Path,
    *,
    paths: ContractPaths | None = None,
    fail_fast: bool = False,
) -> CheckReport:
    """Check a complete T-RECAP artifact tree."""

    root = Path(artifacts_dir)
    cpaths = paths or default_paths(root)
    report = CheckReport(artifacts_dir=root)
    try:
        coeff_hashes = check_coefficients(root, cpaths, report)
        check_vectors(root, coeff_hashes, cpaths, report)
        check_optional_manifests(root, cpaths, report)
    except Exception as exc:  # pragma: no cover - final guard for report rather than traceback
        report.add_issue(root, "artifact_tree", str(exc))
    if fail_fast:
        report.raise_for_errors()
    return report


__all__ = [
    "ArtifactCheckError",
    "CheckIssue",
    "CheckReport",
    "check_artifact_tree",
    "check_coefficients",
    "check_memh",
    "check_optional_manifests",
    "check_vector",
    "check_vectors",
]
