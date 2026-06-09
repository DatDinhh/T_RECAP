# SPDX-License-Identifier: MIT
"""Shared adapter for repository-owned golden-model tool scripts.

The source-of-truth command implementations still live under ``tools/`` because
that is the active artifact workflow used by the Makefile.  The importable
``trecap_golden.cli`` package provides stable Python module entry points without
forking a second copy of coefficient generation, vector generation, suite runs,
artifact checking, or release freezing.
"""

from __future__ import annotations

import os
import runpy
import sys
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from trecap_golden.contracts.contract_paths import ROOT_MARKERS, RepoDiscoveryError, find_repo_root

TOOL_SCRIPTS: Final[dict[str, str]] = {
    "gen_coeffs": "gen_coeffs.py",
    "gen_vectors": "gen_vectors.py",
    "run_suite": "run_suite.py",
    "artifact_check": "artifact_check.py",
    "freeze_release": "freeze_release.py",
}


class CliToolError(RuntimeError):
    """Raised when a repository tool cannot be located or executed."""


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Resolved repository tool invocation."""

    tool_name: str
    repo_root: Path
    script_path: Path
    argv: tuple[str, ...]


@contextmanager
def _temporary_process_state(repo_root: Path, script_path: Path, argv: Sequence[str]):
    """Temporarily set argv, cwd, and import path for a repository tool script."""

    old_cwd = Path.cwd()
    old_argv = sys.argv[:]
    old_path = sys.path[:]
    try:
        tools_dir = repo_root / "tools"
        python_dir = repo_root / "python"
        sys.argv = [str(script_path), *argv]
        sys.path.insert(0, str(tools_dir))
        sys.path.insert(0, str(python_dir))
        os.chdir(repo_root)
        yield
    finally:
        os.chdir(old_cwd)
        sys.argv = old_argv
        sys.path[:] = old_path


def _exit_code(code: object) -> int:
    """Normalize ``SystemExit.code`` into a process-style integer."""

    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def _normalize_argv(argv: Sequence[str] | None) -> list[str]:
    return list(sys.argv[1:] if argv is None else argv)


def _extract_repo_root(argv: list[str]) -> tuple[Path | None, tuple[str, ...]]:
    """Remove the wrapper-only ``--repo-root`` argument from ``argv``."""

    root: Path | None = None
    remaining: list[str] = []
    idx = 0
    while idx < len(argv):
        item = argv[idx]
        if item == "--repo-root":
            if idx + 1 >= len(argv):
                raise CliToolError("--repo-root requires a path argument")
            root = Path(argv[idx + 1]).expanduser().resolve()
            idx += 2
            continue
        if item.startswith("--repo-root="):
            value = item.split("=", 1)[1]
            if not value:
                raise CliToolError("--repo-root requires a non-empty path")
            root = Path(value).expanduser().resolve()
            idx += 1
            continue
        remaining.append(item)
        idx += 1
    return root, tuple(remaining)


def resolve_tool(tool_name: str, argv: Sequence[str] | None = None) -> ToolInvocation:
    """Resolve a repository tool script and stripped tool arguments."""

    if tool_name not in TOOL_SCRIPTS:
        known = ", ".join(sorted(TOOL_SCRIPTS))
        raise CliToolError(f"unknown T-RECAP CLI tool {tool_name!r}; known tools: {known}")

    root_override, remaining = _extract_repo_root(_normalize_argv(argv))
    if root_override is not None:
        missing = [marker for marker in ROOT_MARKERS if not (root_override / marker).exists()]
        if missing:
            joined = ", ".join(missing)
            raise CliToolError(f"--repo-root is not a trecap-golden root: {root_override} (missing: {joined})")
        repo_root = root_override
    else:
        try:
            repo_root = find_repo_root(Path.cwd())
        except RepoDiscoveryError as exc:
            raise CliToolError(
                "could not locate trecap-golden repository root; run from a source checkout, "
                "set TRECAP_GOLDEN_ROOT, or pass --repo-root <path>"
            ) from exc

    script_path = repo_root / "tools" / TOOL_SCRIPTS[tool_name]
    if not script_path.is_file():
        raise CliToolError(f"missing repository tool script: {script_path}")

    return ToolInvocation(tool_name=tool_name, repo_root=repo_root, script_path=script_path, argv=remaining)


def run_repository_tool(tool_name: str, argv: Sequence[str] | None = None) -> int:
    """Run a canonical ``tools/`` script through the Python package CLI."""

    invocation = resolve_tool(tool_name, argv)
    try:
        with _temporary_process_state(invocation.repo_root, invocation.script_path, invocation.argv):
            try:
                runpy.run_path(str(invocation.script_path), run_name="__main__")
            except SystemExit as exc:
                return _exit_code(exc.code)
    except CliToolError:
        raise
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        raise CliToolError(f"{tool_name}: {exc}") from exc
    return 0


def main_for(tool_name: str, argv: Sequence[str] | None = None) -> int:
    """CLI-safe wrapper that reports adapter errors on stderr."""

    try:
        return run_repository_tool(tool_name, argv)
    except CliToolError as exc:
        print(f"trecap-{tool_name}: ERROR: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "CliToolError",
    "TOOL_SCRIPTS",
    "ToolInvocation",
    "main_for",
    "resolve_tool",
    "run_repository_tool",
]
