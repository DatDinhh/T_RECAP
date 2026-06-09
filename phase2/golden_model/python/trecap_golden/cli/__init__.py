# SPDX-License-Identifier: MIT
"""Importable CLI entry points for the T-RECAP golden-model workflow.

The package CLIs intentionally delegate to the canonical repository tools under
``tools/``.  This keeps one implementation path for coefficient generation,
vector generation, golden-suite execution, artifact checking, and release
freezing.
"""

from __future__ import annotations

from ._tool_adapter import TOOL_SCRIPTS, CliToolError, main_for, run_repository_tool

CLI_TOOL_NAMES = tuple(sorted(TOOL_SCRIPTS))

__all__ = ["CLI_TOOL_NAMES", "CliToolError", "main_for", "run_repository_tool"]
