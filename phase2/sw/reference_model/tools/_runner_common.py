"""Shared read-only input handling for the reference runners."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from _trecap_tool_common import (
    ToolError, read_json, require_vector_name, validate_threshold,
)
from trecap_golden.generated.trecap_config import CONFIGURATION_BASE, CONTRACT, WIDTHS

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def default_reference_exe() -> Path:
    roots = [PACKAGE_ROOT / "build", PACKAGE_ROOT.parents[1] / "build/host/reference_model"]
    for root in roots:
        for suffix in ("phase2_golden_model", "phase2_golden_model.exe",
                       "Release/phase2_golden_model.exe", "RelWithDebInfo/phase2_golden_model.exe"):
            candidate = root / suffix
            if candidate.is_file():
                return candidate.resolve()
    raise ToolError("reference executable not found; build the C++ target and pass --reference-exe")


def load_vector_config(directory: Path) -> dict[str, Any]:
    config = read_json(directory / "config.json")
    if not isinstance(config, dict) or config.get("schema") != "trecap_phase2_vector_config_v1":
        raise ToolError(f"{directory}: expected a vector config object")
    if not isinstance(config.get("vector_name"), str):
        raise ToolError(f"{directory}: vector_name must be a string")
    require_vector_name(config["vector_name"])
    cfg = config.get("configuration")
    if not isinstance(cfg, dict):
        raise ToolError(f"{directory}: missing configuration object")
    for key, expected in CONFIGURATION_BASE.items():
        if key == "THR2":
            if not isinstance(cfg.get(key), str):
                raise ToolError("configuration.THR2 must be a decimal string")
            validate_threshold(cfg[key])
        elif type(cfg.get(key)) is not type(expected) or cfg[key] != expected:
            raise ToolError(f"{directory}: unsupported baseline field {key}")
    for block, fields in (("contract", CONTRACT), ("widths", WIDTHS)):
        actual = config.get(block)
        if not isinstance(actual, dict):
            raise ToolError(f"{directory}: missing {block} object")
        for key, expected in fields.items():
            if type(actual.get(key)) is not type(expected) or actual[key] != expected:
                raise ToolError(f"{directory}: unsupported {block}.{key}")
    if not isinstance(config.get("artifact_rows"), dict):
        raise ToolError(f"{directory}: missing artifact_rows object")
    return config


def ensure_separate_output(output: Path, *inputs: Path) -> None:
    target = output.resolve()
    for source in inputs:
        source = source.resolve()
        if target == source or target.is_relative_to(source) or source.is_relative_to(target):
            raise ToolError(f"output must be separate from inputs: {target}")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ToolError(f"output must be new or empty: {target}")


def run_command(exe: Path, vector_dir: Path, output: Path, coeff_dir: Path, *,
                threshold: str | None = None, collect: bool = False) -> list[str]:
    command = [str(exe.resolve()), "--vector-dir", str(vector_dir.resolve()),
               "--output-dir", str(output.resolve()), "--coeff-dir", str(coeff_dir.resolve())]
    if threshold is not None:
        command.extend(["--thr2", validate_threshold(threshold)])
    if collect:
        command.append("--collect-bin-stats")
    return command
