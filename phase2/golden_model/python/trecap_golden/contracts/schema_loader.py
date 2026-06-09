# SPDX-License-Identifier: MIT
"""JSON Schema loading utilities for the T-RECAP golden-model contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .contract_paths import ContractPaths, SCHEMA_FILES, default_paths, normalize_schema_name

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class SchemaRecord:
    """Loaded schema plus provenance and digest information."""

    name: str
    path: Path
    schema_id: str
    sha256: str
    schema: JsonObject


def canonical_json_bytes(obj: Mapping[str, Any]) -> bytes:
    """Serialize JSON deterministically for local schema digesting."""

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def schema_key_from_path(path: str | Path) -> str:
    """Return the canonical short schema key for a schema path."""

    name = Path(path).name
    if name.endswith(".schema.json"):
        return name[: -len(".schema.json")]
    if name.endswith(".schema.md"):
        return name[: -len(".schema.md")]
    return Path(name).stem


def load_json(path: str | Path) -> JsonObject:
    """Load a JSON object and reject non-object top-level JSON."""

    p = Path(path)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {p}: {exc.msg} at line {exc.lineno}") from exc
    if not isinstance(obj, dict):
        raise TypeError(f"expected JSON object in {p}")
    return obj


def load_schema(name: str, paths: ContractPaths | None = None) -> SchemaRecord:
    """Load one JSON schema by alias or filename."""

    cpaths = paths or default_paths()
    filename = normalize_schema_name(name)
    if not filename.endswith(".schema.json"):
        raise ValueError(f"not a JSON schema filename: {filename}")
    path = cpaths.schema_path(filename)
    cpaths.require_file(path)
    schema = load_json(path)
    Draft202012Validator.check_schema(schema)
    digest = hashlib.sha256(canonical_json_bytes(schema)).hexdigest()
    return SchemaRecord(
        name=schema_key_from_path(path),
        path=path,
        schema_id=str(schema.get("$id", "")),
        sha256=digest,
        schema=schema,
    )


def load_all_schemas(paths: ContractPaths | None = None) -> dict[str, SchemaRecord]:
    """Load every JSON schema in the repository schema contract set."""

    cpaths = paths or default_paths()
    records: dict[str, SchemaRecord] = {}
    for schema_name in SCHEMA_FILES:
        record = load_schema(schema_name, cpaths)
        records[record.name] = record
    return records


def schema_store(paths: ContractPaths | None = None) -> dict[str, JsonObject]:
    """Return an id-addressable schema store for jsonschema resolvers."""

    store: dict[str, JsonObject] = {}
    for record in load_all_schemas(paths).values():
        if record.schema_id:
            store[record.schema_id] = record.schema
    return store


def make_validator(name: str, paths: ContractPaths | None = None) -> Draft202012Validator:
    """Create a Draft 2020-12 validator for one named schema."""

    record = load_schema(name, paths)
    return Draft202012Validator(record.schema)


def schema_inventory(paths: ContractPaths | None = None) -> list[dict[str, str]]:
    """Return a stable inventory of known JSON schemas and their digests."""

    records = load_all_schemas(paths)
    return [
        {
            "name": name,
            "path": str(record.path),
            "id": record.schema_id,
            "sha256": record.sha256,
        }
        for name, record in sorted(records.items())
    ]


__all__ = [
    "JsonObject",
    "SchemaRecord",
    "canonical_json_bytes",
    "load_all_schemas",
    "load_json",
    "load_schema",
    "make_validator",
    "schema_inventory",
    "schema_key_from_path",
    "schema_store",
]
