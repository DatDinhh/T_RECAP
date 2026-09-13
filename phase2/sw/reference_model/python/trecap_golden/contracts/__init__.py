# SPDX-License-Identifier: MIT
"""Schema and repository-contract helpers for T-RECAP golden tooling."""

from __future__ import annotations

from typing import Any

from .contract_paths import ContractPaths, default_paths, find_repo_root

_LAZY_EXPORTS = {
    "load_all_schemas",
    "load_schema",
    "make_validator",
    "schema_inventory",
    "validate_artifact_tree",
    "validate_file",
    "validate_files",
    "validate_obj",
}

__all__ = [
    "ContractPaths",
    "default_paths",
    "find_repo_root",
    "load_all_schemas",
    "load_schema",
    "make_validator",
    "schema_inventory",
    "validate_artifact_tree",
    "validate_file",
    "validate_files",
    "validate_obj",
]


def __getattr__(name: str) -> Any:
    if name in {"load_all_schemas", "load_schema", "make_validator", "schema_inventory"}:
        from . import schema_loader

        return getattr(schema_loader, name)
    if name in _LAZY_EXPORTS:
        from . import schema_validate

        return getattr(schema_validate, name)
    raise AttributeError(name)
