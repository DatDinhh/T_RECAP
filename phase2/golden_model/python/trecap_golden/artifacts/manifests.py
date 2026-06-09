# SPDX-License-Identifier: MIT
"""Manifest helpers for T-RECAP golden artifact trees."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from trecap_golden.contracts.contract_paths import ContractPaths, default_paths
from trecap_golden.generated import trecap_config as cfg

from .hashes import canonical_memh_file_hash, sha256_file
from .memh import MemhContract, contract_for_kind


class ManifestError(ValueError):
    """Raised when manifest loading or discovery fails."""


@dataclass(frozen=True, slots=True)
class VectorArtifacts:
    """Paths associated with one frozen vector."""

    name: str
    test_vector_dir: Path
    golden_dir: Path

    @property
    def x_in(self) -> Path:
        return self.test_vector_dir / "x_in.memh"

    @property
    def config(self) -> Path:
        return self.test_vector_dir / "config.json"

    @property
    def y_out(self) -> Path:
        return self.golden_dir / "y_out.memh"

    @property
    def frame_stats(self) -> Path:
        return self.golden_dir / "frame_stats.csv"

    @property
    def metrics(self) -> Path:
        return self.golden_dir / "metrics.json"

    @property
    def bin_stats(self) -> Path:
        return self.golden_dir / "bin_stats.csv"


def read_json(path: str | Path) -> dict[str, Any]:
    """Read one JSON object manifest."""

    p = Path(path)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"missing JSON manifest: {p}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON in {p}: {exc}") from exc
    if not isinstance(obj, dict):
        raise ManifestError(f"{p}: manifest root must be a JSON object")
    return obj


def write_json(path: str | Path, obj: Mapping[str, Any]) -> None:
    """Write JSON using stable indentation and one final LF."""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(obj), indent=2, sort_keys=False) + "\n", encoding="utf-8")


def artifact_paths_from_root(root: str | Path) -> ContractPaths:
    """Return contract paths for a repository root or artifact-tree child path."""

    return default_paths(Path(root))


def coefficient_contracts() -> dict[str, MemhContract]:
    """Return canonical contracts for coefficient memh files keyed by stem."""

    return {
        "window_qw": contract_for_kind("window_qw", rows=cfg.L),
        "twiddle_re": contract_for_kind("twiddle_re", rows=cfg.L),
        "twiddle_im": contract_for_kind("twiddle_im", rows=cfg.L),
        "twiddle_inv_re": contract_for_kind("twiddle_inv_re", rows=cfg.L),
        "twiddle_inv_im": contract_for_kind("twiddle_inv_im", rows=cfg.L),
    }


def coefficient_hashes(coefficients_dir: str | Path) -> dict[str, str]:
    """Compute canonical coefficient hashes from frozen coefficient memh files."""

    root = Path(coefficients_dir)
    hashes: dict[str, str] = {}
    for key, contract in coefficient_contracts().items():
        hashes[f"{key}_sha256"] = canonical_memh_file_hash(root / f"{key}.memh", contract)
    return hashes


def coefficient_manifest(coefficients_dir: str | Path) -> dict[str, Any]:
    """Load ``coeff_manifest.json`` from a coefficient directory."""

    return read_json(Path(coefficients_dir) / "coeff_manifest.json")


def test_vectors_manifest(test_vectors_dir: str | Path) -> dict[str, Any]:
    """Load ``test_vectors.json`` from the test-vector artifact directory."""

    return read_json(Path(test_vectors_dir) / "test_vectors.json")


def iter_vector_entries(test_vectors: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return vector entries in manifest order."""

    entries = test_vectors.get("vectors", [])
    if not isinstance(entries, list):
        raise ManifestError("test_vectors.json field 'vectors' must be a list")
    return tuple(dict(entry) for entry in entries)


def discover_vector_artifacts(artifacts_dir: str | Path) -> tuple[VectorArtifacts, ...]:
    """Discover vector directories using ``test_vectors/test_vectors.json`` order."""

    root = Path(artifacts_dir)
    manifest = test_vectors_manifest(root / "test_vectors")
    vectors: list[VectorArtifacts] = []
    for entry in iter_vector_entries(manifest):
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestError("vector entry has missing or invalid name")
        vectors.append(VectorArtifacts(name, root / "test_vectors" / name, root / "golden" / name))
    return tuple(vectors)


def known_json_artifacts(artifacts_dir: str | Path) -> tuple[Path, ...]:
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
    return tuple(sorted(path for path in candidates if path.is_file()))


def artifact_index_entries(artifact_index_path: str | Path) -> dict[str, dict[str, Any]]:
    """Load artifact index and return entries keyed by artifact path."""

    obj = read_json(artifact_index_path)
    entries = obj.get("artifacts", [])
    if not isinstance(entries, list):
        raise ManifestError("artifact_index.json field 'artifacts' must be a list")
    out: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ManifestError("artifact_index.json has an entry without a path")
        out[entry["path"]] = dict(entry)
    return out


def file_records(files: Iterable[str | Path], *, base: str | Path | None = None) -> tuple[dict[str, Any], ...]:
    """Return byte-hash records for files, optionally relative to ``base``."""

    base_path = Path(base) if base is not None else None
    records: list[dict[str, Any]] = []
    for file_path in sorted(Path(path) for path in files):
        rel = file_path.relative_to(base_path).as_posix() if base_path is not None else file_path.as_posix()
        records.append({"path": rel, "sha256": sha256_file(file_path), "bytes": file_path.stat().st_size})
    return tuple(records)


__all__ = [
    "ManifestError",
    "VectorArtifacts",
    "artifact_index_entries",
    "artifact_paths_from_root",
    "coefficient_contracts",
    "coefficient_hashes",
    "coefficient_manifest",
    "discover_vector_artifacts",
    "file_records",
    "iter_vector_entries",
    "known_json_artifacts",
    "read_json",
    "test_vectors_manifest",
    "write_json",
]
