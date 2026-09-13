# SPDX-License-Identifier: MIT
"""Artifact utilities for the T-RECAP Phase 2 golden-model repository.

Import submodules directly, for example:

    from trecap_golden.artifacts import memh, csv_io, hashes, manifests
    from trecap_golden.artifacts.checker import check_artifact_tree

The package initializer is intentionally lightweight so importing `memh` does not
also import JSON Schema validation and the full artifact checker.
"""

from __future__ import annotations

__all__ = [
    "checker",
    "csv_io",
    "hashes",
    "manifests",
    "memh",
]
