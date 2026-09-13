# SPDX-License-Identifier: MIT
"""Package CLI wrapper for ``tools/freeze_release.py``."""

from __future__ import annotations

from collections.abc import Sequence

from ._tool_adapter import main_for


def main(argv: Sequence[str] | None = None) -> int:
    """Run the canonical repository ``freeze_release`` tool."""

    return main_for("freeze_release", argv)


if __name__ == "__main__":  # pragma: no cover - exercised through python -m
    raise SystemExit(main())
