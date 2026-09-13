# SPDX-License-Identifier: MIT
"""SHA-256 helpers for T-RECAP canonical artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .memh import MemhContract, canonical_bytes, read_memh


def sha256_bytes(data: bytes) -> str:
    """Return lowercase SHA-256 hex digest for bytes."""

    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str, *, encoding: str = "utf-8") -> str:
    """Return SHA-256 for encoded text."""

    return sha256_bytes(text.encode(encoding))


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 over exact file bytes."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    """Serialize JSON deterministically for package-side diagnostics.

    Signoff JSON schemas still define the artifact fields. This helper exists for
    reproducible diagnostics and should not be confused with the canonical memh
    hash rule.
    """

    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_json_hash(obj: Any) -> str:
    """Return SHA-256 of deterministic JSON diagnostic serialization."""

    return sha256_bytes(canonical_json_bytes(obj))


def canonical_memh_hash(values: Iterable[int], contract: MemhContract) -> str:
    """Return the canonical memh hash of a logical integer vector."""

    return sha256_bytes(canonical_bytes(values, contract))


def canonical_memh_file_hash(path: str | Path, contract: MemhContract) -> str:
    """Read a memh file strictly and hash its logical canonical serialization."""

    parsed = read_memh(path, contract)
    return canonical_memh_hash(parsed.values, parsed.contract)


def file_hash_record(path: str | Path) -> dict[str, str | int]:
    """Return a stable byte-hash record for manifests."""

    p = Path(path)
    return {"path": p.as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size}


__all__ = [
    "canonical_json_bytes",
    "canonical_json_hash",
    "canonical_memh_file_hash",
    "canonical_memh_hash",
    "file_hash_record",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
]
