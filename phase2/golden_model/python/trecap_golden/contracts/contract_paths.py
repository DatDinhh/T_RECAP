# SPDX-License-Identifier: MIT
"""Repository path discovery for T-RECAP golden-model contract files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT_MARKERS: Final[tuple[str, ...]] = (
    "pyproject.toml",
    "Makefile",
    "spec/schemas/core_config.schema.json",
)

SCHEMA_FILES: Final[tuple[str, ...]] = (
    "core_config.schema.json",
    "coeff_manifest.schema.json",
    "test_vectors.schema.json",
    "vector_config.schema.json",
    "metrics.schema.json",
    "quality_bounds.schema.json",
    "artifact_index.schema.json",
    "frozen_release_manifest.schema.json",
)

CSV_SCHEMA_DOCS: Final[tuple[str, ...]] = (
    "frame_stats.schema.md",
    "bin_stats.schema.md",
)

GENERATED_FILES: Final[tuple[str, ...]] = (
    "core_config.json",
    "width_config.json",
    "artifact_contract.json",
    "gen_manifest.json",
)


class RepoDiscoveryError(RuntimeError):
    """Raised when the golden-model repository root cannot be found."""


def _looks_like_repo_root(candidate: Path) -> bool:
    return all((candidate / marker).exists() for marker in ROOT_MARKERS)


def find_repo_root(start: str | Path | None = None) -> Path:
    """Find the repository root from ``start`` or ``TRECAP_GOLDEN_ROOT``.

    The function deliberately requires the schema marker as well as the usual
    root build files. That prevents accidentally treating a parent directory or a
    random checkout as the golden-model contract root.
    """

    env_root = os.environ.get("TRECAP_GOLDEN_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if _looks_like_repo_root(root):
            return root
        raise RepoDiscoveryError(f"TRECAP_GOLDEN_ROOT is not a trecap-golden root: {root}")

    here = Path(start).expanduser().resolve() if start is not None else Path.cwd().resolve()
    if here.is_file():
        here = here.parent

    for candidate in (here, *here.parents):
        if _looks_like_repo_root(candidate):
            return candidate

    module_path = Path(__file__).resolve()
    for candidate in module_path.parents:
        if _looks_like_repo_root(candidate):
            return candidate

    raise RepoDiscoveryError(
        "could not locate trecap-golden repository root; set TRECAP_GOLDEN_ROOT"
    )


@dataclass(frozen=True, slots=True)
class ContractPaths:
    """Canonical filesystem locations for golden-model contract assets."""

    root: Path
    spec_dir: Path
    schemas_dir: Path
    spec_generated_dir: Path
    python_package_dir: Path
    python_generated_dir: Path
    artifacts_dir: Path
    coefficients_dir: Path
    test_vectors_dir: Path
    golden_dir: Path
    manifests_dir: Path
    configs_dir: Path

    @classmethod
    def discover(cls, start: str | Path | None = None) -> "ContractPaths":
        root = find_repo_root(start)
        return cls(
            root=root,
            spec_dir=root / "spec",
            schemas_dir=root / "spec" / "schemas",
            spec_generated_dir=root / "spec" / "generated",
            python_package_dir=root / "python" / "trecap_golden",
            python_generated_dir=root / "python" / "trecap_golden" / "generated",
            artifacts_dir=root / "artifacts",
            coefficients_dir=root / "artifacts" / "coefficients",
            test_vectors_dir=root / "artifacts" / "test_vectors",
            golden_dir=root / "artifacts" / "golden",
            manifests_dir=root / "artifacts" / "manifests",
            configs_dir=root / "configs",
        )

    def schema_path(self, name: str) -> Path:
        """Return the absolute path to a JSON schema or CSV schema document."""

        normalized = normalize_schema_name(name)
        if normalized.endswith(".schema.md"):
            return self.schemas_dir / normalized
        return self.schemas_dir / normalized

    def generated_path(self, name: str) -> Path:
        """Return the absolute path to a spec/generated file."""

        return self.spec_generated_dir / normalize_generated_name(name)

    def require_file(self, path: Path) -> Path:
        """Return ``path`` if it exists; otherwise raise FileNotFoundError."""

        if not path.is_file():
            raise FileNotFoundError(str(path))
        return path

    def require_dir(self, path: Path) -> Path:
        """Return ``path`` if it exists; otherwise raise NotADirectoryError."""

        if not path.is_dir():
            raise NotADirectoryError(str(path))
        return path


def normalize_schema_name(name: str) -> str:
    """Normalize a schema alias into an on-disk schema filename."""

    raw = name.strip()
    if not raw:
        raise ValueError("schema name must not be empty")
    if raw in CSV_SCHEMA_DOCS:
        return raw
    if raw.endswith(".schema.md"):
        return raw
    if raw.endswith(".schema.json"):
        return raw
    if raw.endswith(".json"):
        raw = raw[: -len(".json")]
    if raw.endswith(".schema"):
        raw = raw[: -len(".schema")]
    return f"{raw}.schema.json"


def normalize_generated_name(name: str) -> str:
    """Normalize a spec/generated alias into an on-disk JSON filename."""

    raw = name.strip()
    if not raw:
        raise ValueError("generated file name must not be empty")
    if raw.endswith(".json"):
        return raw
    return f"{raw}.json"


def default_paths(start: str | Path | None = None) -> ContractPaths:
    """Return repository contract paths discovered from ``start`` or the CWD."""

    return ContractPaths.discover(start)


__all__ = [
    "CSV_SCHEMA_DOCS",
    "ContractPaths",
    "GENERATED_FILES",
    "ROOT_MARKERS",
    "RepoDiscoveryError",
    "SCHEMA_FILES",
    "default_paths",
    "find_repo_root",
    "normalize_generated_name",
    "normalize_schema_name",
]
