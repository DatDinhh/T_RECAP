# SPDX-License-Identifier: MIT
"""Schema validation helpers for golden-model JSON artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from .contract_paths import ContractPaths, default_paths
from .schema_loader import JsonObject, load_json, load_schema, make_validator, schema_inventory

SCHEMA_BY_EXACT_NAME: dict[str, str] = {
    "artifact_index.json": "artifact_index",
    "coeff_manifest.json": "coeff_manifest",
    "core_config.json": "core_config",
    "frozen_release_manifest.json": "frozen_release_manifest",
    "metrics.json": "metrics",
    "quality_bounds.json": "quality_bounds",
    "test_vectors.json": "test_vectors",
    "vector_config.json": "vector_config",
}

SCHEMA_BY_SCHEMA_FIELD: dict[str, str] = {
    "trecap_phase2_artifact_index_v1": "artifact_index",
    "trecap_phase2_coeff_manifest_v1": "coeff_manifest",
    "trecap_phase2_core_config_v1": "core_config",
    "trecap_phase2_frozen_release_manifest_v1": "frozen_release_manifest",
    "trecap_phase2_metrics_v1": "metrics",
    "trecap_phase2_quality_bounds_v1": "quality_bounds",
    "trecap_phase2_test_vectors_v1": "test_vectors",
    "trecap_phase2_vector_config_v1": "vector_config",
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One schema validation issue in stable display form."""

    path: str
    schema_path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of validating one object or file."""

    ok: bool
    schema_name: str
    instance_path: Path | None
    schema_path: Path
    errors: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    def raise_for_errors(self) -> None:
        """Raise ValidationErrorSummary if validation failed."""

        if not self.ok:
            raise ValidationErrorSummary(self)


class ValidationErrorSummary(ValueError):
    """Compact exception for failed artifact/schema validation."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        location = str(result.instance_path) if result.instance_path else "<object>"
        details = "; ".join(issue.message for issue in result.errors[:3])
        super().__init__(f"{location} failed {result.schema_name} validation: {details}")


def _json_path(error: ValidationError) -> str:
    if not error.path:
        return "$"
    return "$" + "".join(f"[{part!r}]" if isinstance(part, int) else f".{part}" for part in error.path)


def _schema_path(error: ValidationError) -> str:
    if not error.schema_path:
        return "$schema"
    return "$schema" + "".join(
        f"[{part!r}]" if isinstance(part, int) else f".{part}" for part in error.schema_path
    )


def infer_schema_name(path: str | Path, obj: JsonObject | None = None) -> str:
    """Infer the repository schema name for a JSON artifact.

    Exact file names win first. If the file is a per-vector ``config.json``, the
    ``schema`` field disambiguates it. This avoids treating all generic
    ``config.json`` files as core config files.
    """

    p = Path(path)
    exact = SCHEMA_BY_EXACT_NAME.get(p.name)
    if exact:
        return exact

    if obj is not None:
        schema_field = obj.get("schema")
        if isinstance(schema_field, str) and schema_field in SCHEMA_BY_SCHEMA_FIELD:
            return SCHEMA_BY_SCHEMA_FIELD[schema_field]
        if "vector_name" in obj and "artifact_rows" in obj:
            return "vector_config"
        if "artifact_contract" in obj and "configuration" in obj:
            return "core_config"

    if p.name == "config.json":
        parts = set(p.parts)
        if "test_vectors" in parts:
            return "vector_config"

    raise ValueError(f"cannot infer schema for {p}; pass schema_name explicitly")


def validate_obj(
    obj: JsonObject,
    schema_name: str,
    *,
    paths: ContractPaths | None = None,
    instance_path: str | Path | None = None,
) -> ValidationResult:
    """Validate a JSON object against one repository schema."""

    cpaths = paths or default_paths()
    schema = load_schema(schema_name, cpaths)
    validator = make_validator(schema.name, cpaths)
    errors = tuple(
        ValidationIssue(
            path=_json_path(error),
            schema_path=_schema_path(error),
            message=error.message,
        )
        for error in sorted(validator.iter_errors(obj), key=lambda item: list(item.path))
    )
    return ValidationResult(
        ok=not errors,
        schema_name=schema.name,
        instance_path=Path(instance_path) if instance_path is not None else None,
        schema_path=schema.path,
        errors=errors,
    )


def validate_file(
    path: str | Path,
    schema_name: str | None = None,
    *,
    paths: ContractPaths | None = None,
) -> ValidationResult:
    """Load and validate one JSON artifact file."""

    p = Path(path)
    obj = load_json(p)
    resolved_schema = schema_name or infer_schema_name(p, obj)
    return validate_obj(obj, resolved_schema, paths=paths, instance_path=p)


def validate_files(
    files: list[str | Path],
    *,
    schema_name: str | None = None,
    paths: ContractPaths | None = None,
) -> list[ValidationResult]:
    """Validate multiple JSON files and return one result per file."""

    cpaths = paths or default_paths()
    return [validate_file(file_path, schema_name, paths=cpaths) for file_path in files]


def artifact_tree_json_files(artifacts_dir: str | Path) -> list[Path]:
    """Return known JSON artifacts under an artifact tree in stable order."""

    root = Path(artifacts_dir)
    candidates: list[Path] = []
    for pattern in (
        "coefficients/coeff_manifest.json",
        "test_vectors/test_vectors.json",
        "test_vectors/*/config.json",
        "golden/*/metrics.json",
        "manifests/quality_bounds.json",
        "manifests/artifact_index.json",
        "manifests/frozen_release_manifest.json",
    ):
        candidates.extend(root.glob(pattern))
    return sorted(path for path in candidates if path.is_file())


def validate_artifact_tree(
    artifacts_dir: str | Path,
    *,
    paths: ContractPaths | None = None,
) -> list[ValidationResult]:
    """Validate all known JSON artifacts found under ``artifacts_dir``."""

    files = artifact_tree_json_files(artifacts_dir)
    return validate_files(files, paths=paths)


def result_to_dict(result: ValidationResult) -> dict[str, Any]:
    """Convert a validation result into JSON-serializable form."""

    return {
        "ok": result.ok,
        "schema_name": result.schema_name,
        "instance_path": str(result.instance_path) if result.instance_path else None,
        "schema_path": str(result.schema_path),
        "errors": [
            {
                "path": issue.path,
                "schema_path": issue.schema_path,
                "message": issue.message,
            }
            for issue in result.errors
        ],
    }


def _print_human(results: list[ValidationResult]) -> None:
    for result in results:
        instance = str(result.instance_path) if result.instance_path else "<object>"
        if result.ok:
            print(f"OK {instance} [{result.schema_name}]")
            continue
        print(f"FAIL {instance} [{result.schema_name}]", file=sys.stderr)
        for issue in result.errors:
            print(f"  {issue.path}: {issue.message}", file=sys.stderr)


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate T-RECAP golden-model JSON contracts")
    parser.add_argument("files", nargs="*", help="JSON files to validate")
    parser.add_argument("--schema", default=None, help="Schema name override, e.g. metrics")
    parser.add_argument("--artifacts", default=None, help="Validate known JSON files under artifact tree")
    parser.add_argument("--root", default=None, help="trecap-golden repository root")
    parser.add_argument("--inventory", action="store_true", help="Print schema inventory and exit")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argparser()
    args = parser.parse_args(argv)
    paths = default_paths(args.root) if args.root else default_paths()

    if args.inventory:
        payload = {"schemas": schema_inventory(paths)}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for item in payload["schemas"]:
                print(f"{item['name']}: {item['sha256']}  {item['path']}")
        return 0

    files = [Path(file_name) for file_name in args.files]
    if args.artifacts:
        files.extend(artifact_tree_json_files(args.artifacts))
    if not files:
        parser.error("provide files, --artifacts, or --inventory")

    results = validate_files(files, schema_name=args.schema, paths=paths)
    if args.json:
        print(json.dumps({"results": [result_to_dict(result) for result in results]}, indent=2))
    else:
        _print_human(results)
    return 0 if all(result.ok for result in results) else 1


__all__ = [
    "SCHEMA_BY_EXACT_NAME",
    "SCHEMA_BY_SCHEMA_FIELD",
    "ValidationErrorSummary",
    "ValidationIssue",
    "ValidationResult",
    "artifact_tree_json_files",
    "infer_schema_name",
    "main",
    "result_to_dict",
    "validate_artifact_tree",
    "validate_file",
    "validate_files",
    "validate_obj",
]


if __name__ == "__main__":
    raise SystemExit(main())
