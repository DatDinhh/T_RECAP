#!/usr/bin/env python3
"""Fail-closed compile-closure check for the unified native C0 runner."""

from __future__ import annotations

import re
import sys
from pathlib import Path


class ContractError(RuntimeError):
    """Raised when the native runner cannot compile every top it invokes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def canonical_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    require(data.endswith(b"\n"), f"{path}: final LF is required")
    require(b"\r" not in data, f"{path}: CR/CRLF is not canonical")
    try:
        return data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{path}: ASCII text is required") from exc


def contained_file(repo: Path, relative: Path, label: str) -> Path:
    candidate = repo / relative
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"cannot resolve {label} {candidate}: {exc}") from exc
    require(resolved.is_relative_to(repo), f"{label} escapes repository: {relative}")
    require(resolved.is_file(), f"{label} is not a regular file: {relative}")
    return resolved


def compile_block(runner_text: str) -> str:
    blocks = re.findall(
        r"Invoke-Native\s+-Exe\s+\$Vlog\s+`\s*"
        r"-Arguments\s+@\((.*?)\)\s*`\s*"
        r"-Log\s+\(Join-Path\s+\$RunDir\s+\"compile\.log\"\)",
        runner_text,
        flags=re.DOTALL,
    )
    require(len(blocks) == 1, "runner must contain exactly one RTL compile command")
    return blocks[0]


def parse_filelist(repo: Path, relative: str) -> tuple[set[Path], set[str]]:
    relative_path = Path(relative.replace("\\", "/"))
    require(
        not relative_path.is_absolute() and ".." not in relative_path.parts,
        f"unsafe filelist path {relative!r}",
    )
    filelist = contained_file(repo, relative_path, "filelist")
    text = canonical_text(filelist)
    sources: set[Path] = set()
    nested: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("+incdir+"):
            continue
        if stripped.startswith("-f "):
            child = stripped[3:].strip().replace("\\", "/")
            require(child, f"{filelist}:{line_number}: empty nested filelist")
            nested.add(child)
            continue
        require(
            stripped.endswith(".sv"),
            f"{filelist}:{line_number}: unsupported entry {stripped!r}",
        )
        source = Path(stripped.replace("\\", "/"))
        require(
            not source.is_absolute() and ".." not in source.parts,
            f"{filelist}:{line_number}: unsafe source path {stripped!r}",
        )
        contained_file(repo, source, "source")
        sources.add(source)
    return sources, nested


def collect_sources(repo: Path, roots: list[str]) -> set[Path]:
    pending = list(roots)
    seen_filelists: set[str] = set()
    sources: set[Path] = set()
    while pending:
        relative = pending.pop()
        require(relative not in seen_filelists, f"duplicate/cyclic filelist {relative}")
        seen_filelists.add(relative)
        direct_sources, nested = parse_filelist(repo, relative)
        sources.update(direct_sources)
        pending.extend(sorted(nested))
    return sources


def module_names(repo: Path, sources: set[Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    module_pattern = re.compile(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)", re.MULTILINE)
    for relative in sorted(sources):
        text = canonical_text(repo / relative)
        for name in module_pattern.findall(text):
            previous = result.get(name)
            require(
                previous is None, f"duplicate module {name}: {previous} and {relative}"
            )
            result[name] = relative
    return result


def main() -> int:
    repo = Path.cwd().resolve()
    runner = repo / "scripts/windows/run_c0_golden_v70.ps1"
    runner_text = canonical_text(runner)
    block = compile_block(runner_text)

    filelists = [
        item.replace("\\", "/")
        for item in re.findall(r"\"-f\"\s*,\s*\"([^\"]+\.f)\"", block)
    ]
    expected_filelists = [
        "filelists/rtl_core_plus_fft.f",
        "sim/filelists/c0_mag2_width.f",
        "sim/filelists/c0_v67_regression.f",
        "sim/filelists/c0_golden.f",
        "sim/filelists/c0_delay_history.f",
    ]
    require(
        filelists == expected_filelists,
        f"compile filelist closure mismatch: expected {expected_filelists}, got {filelists}",
    )

    invoked_tops = set(re.findall(r"-Top\s+\"([A-Za-z_][A-Za-z0-9_$]*)\"", runner_text))
    expected_tops = {
        "tb_trecap_mag2_width",
        "tb_trecap_delay_history",
        "tb_trecap_c0_flow_control",
        "tb_trecap_wola_tail_drain",
        "tb_trecap_c0_active_tail",
        "tb_trecap_c0_golden",
    }
    require(
        invoked_tops == expected_tops,
        f"unexpected regression tops: {sorted(invoked_tops)}",
    )

    sources = collect_sources(repo, filelists)
    modules = module_names(repo, sources)
    missing = sorted(invoked_tops - modules.keys())
    require(not missing, f"runner invokes uncompiled tops: {missing}")
    expected_top_sources = {
        "tb_trecap_mag2_width": Path("sim/tb/tb_trecap_mag2_width.sv"),
        "tb_trecap_delay_history": Path("sim/tb/tb_trecap_delay_history.sv"),
        "tb_trecap_c0_flow_control": Path("sim/tb/tb_trecap_c0_flow_control.sv"),
        "tb_trecap_wola_tail_drain": Path("sim/tb/tb_trecap_wola_tail_drain.sv"),
        "tb_trecap_c0_active_tail": Path("sim/tb/tb_trecap_c0_active_tail.sv"),
        "tb_trecap_c0_golden": Path("sim/tb/tb_trecap_c0_golden.sv"),
    }
    for top, expected_source in expected_top_sources.items():
        require(
            modules[top] == expected_source,
            f"{top} resolved to {modules[top]}, expected {expected_source}",
        )

    print(
        "C0_NATIVE_RUNNER_CLOSURE_PASS "
        f"tops={len(invoked_tops)} filelists={len(filelists)} sources={len(sources)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(f"C0_NATIVE_RUNNER_CLOSURE_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
