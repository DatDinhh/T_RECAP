# SPDX-License-Identifier: MIT
"""Package CLI wrapper for ``tools/gen_vectors.py``."""

from __future__ import annotations

from collections.abc import Sequence

from ._tool_adapter import main_for


def main(argv: Sequence[str] | None = None) -> int:
    """Run the canonical repository ``gen_vectors`` tool."""

    return main_for("gen_vectors", argv)


if __name__ == "__main__":  # pragma: no cover - exercised through python -m
    raise SystemExit(main())
