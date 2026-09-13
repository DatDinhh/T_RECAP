#!/usr/bin/env python3
"""Lint the T-RECAP Phase 2 implementation repository layout.

File class: [1] hand-written repository infrastructure.

This script enforces repository-level hygiene only. It is not a verification
runner, not a SystemVerilog parser, and not a replacement for generated-header
or artifact checks. It catches the errors that otherwise become expensive later:
missing required directories, generated files edited by hand, Phase 1 root dumps,
DDR writer ownership drift, accidental build output in source locations, and
cross-layer dependency leaks.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

REQUIRED_ROOT_FILES = [
    "README.md",
    "Makefile",
    "CMakeLists.txt",
    ".gitignore",
    ".editorconfig",
    ".clang-format",
    ".pre-commit-config.yaml",
    "run_platform_designer.ps1",
]

REQUIRED_DIRS = [
    "docs/specs",
    "docs/architecture",
    "docs/bringup",
    "docs/deprecation",
    "spec/generated",
    "spec/schemas",
    "spec/normative",
    "config/profiles",
    "config/boards",
    "scripts",
    "scripts/quartus",
    "scripts/bringup",
    "scripts/windows",
    "filelists",
    "sim/filelists",
    "sim/tb",
    "rtl/include/generated",
    "rtl/common",
    "rtl/interfaces",
    "rtl/sources",
    "rtl/core",
    "rtl/fft",
    "rtl/telemetry",
    "rtl/hps_bridge",
    "rtl/platform/de1soc",
    "rtl/top",
    "sw/reference_model",
    "sw/hps/include/generated",
    "sw/hps/src",
    "sw/hps/config",
    "sw/hps/scripts",
    "sw/hps/systemd",
    "sw/hps/tests",
    "sw/pc_dashboard/generated",
    "sw/pc_dashboard/tests",
    "sw/pc_dashboard/trecap_dashboard",
    "artifacts/coefficients",
    "artifacts/test_vectors",
    "artifacts/reference_outputs",
    "artifacts/manifests",
    "artifacts/telemetry_captures",
    "constraints/de1soc",
    "platform/de1soc/qsys",
    "platform/de1soc/qsys/presets",
    "platform/de1soc/address_map",
    "platform/de1soc/generated_notes",
    "platform/de1soc/linux",
    "ci/github",
    "ci/docker",
    "legacy/phase1",
    "legacy/deprecated_phase2_docs",
    "runs",
]

REQUIRED_DOC_FILES = [
    "docs/specs/README.md",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/repo_architecture.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/module_api.md",
    "docs/architecture/dependency_rules.md",
    "docs/architecture/build_order.md",
    "docs/architecture/generated_contracts.md",
    "docs/architecture/generated_header_flow.md",
    "docs/architecture/clock_reset_plan.md",
    "docs/architecture/cdc_plan.md",
    "docs/architecture/memory_map.md",
    "docs/architecture/avalon_mm_csr_adapter.md",
    "docs/architecture/platform_designer_wrapper.md",
    "docs/architecture/source_core_integration.md",
    "docs/architecture/core_telemetry_composition.md",
    "docs/architecture/de1soc_board_top_integration.md",
    "docs/architecture/de1soc_bram_replay_path.md",
    "docs/architecture/de1soc_ddr_ring_ownership.md",
    "docs/architecture/de1soc_hps_transport.md",
    "docs/architecture/de1soc_command_path.md",
    "docs/architecture/coding_style.md",
    "docs/bringup/de1_soc_connections.md",
    "docs/bringup/quartus_programming.md",
    "docs/bringup/bram_replay_signoff.md",
    "docs/bringup/hps_ethernet_bringup.md",
    "docs/bringup/ddr_ring_bringup.md",
    "docs/bringup/audio_linein_bringup.md",
    "docs/bringup/adc_bringup.md",
    "docs/bringup/pc_dashboard_bringup.md",
    "docs/deprecation/deprecated_phase2_documents.md",
    "docs/deprecation/phase1_quarantine_notes.md",
]

REQUIRED_HAND_WRITTEN_CONTRACTS = [
    "spec/generated/csr_map.json",
    "spec/generated/packet_layouts.json",
    "spec/generated/interface_types.json",
    "spec/schemas/csr_map.schema.json",
    "spec/schemas/packet_layouts.schema.json",
    "spec/schemas/interface_types.schema.json",
    "spec/schemas/runtime_profile.schema.json",
    "spec/schemas/avalon_csr_adapter.schema.json",
    "spec/schemas/platform_designer_wrapper.schema.json",
    "spec/schemas/source_core_integration.schema.json",
    "spec/schemas/core_telemetry_composition.schema.json",
    "spec/schemas/de1soc_board_top_integration.schema.json",
    "spec/schemas/de1soc_clock_reset_architecture.schema.json",
    "spec/schemas/de1soc_audio_linein.schema.json",
    "spec/schemas/de1soc_adc_live.schema.json",
    "spec/schemas/de1soc_bram_replay_path.schema.json",
    "spec/schemas/de1soc_ddr_ring_ownership.schema.json",
    "spec/schemas/de1soc_hps_transport.schema.json",
    "spec/schemas/de1soc_command_path.schema.json",
    "platform/de1soc/address_map/avalon_csr_adapter.json",
    "platform/de1soc/address_map/platform_designer_wrapper.json",
    "config/boards/de1soc_source_core_integration.json",
    "config/boards/core_telemetry_composition.json",
    "config/boards/de1soc_board_top_integration.json",
    "config/boards/de1soc_clock_reset_architecture.json",
    "config/boards/de1soc_audio_linein.json",
    "config/boards/de1soc_adc_live.json",
    "config/boards/de1soc_bram_replay_path.json",
    "config/boards/de1soc_ddr_ring_ownership.json",
    "config/boards/de1soc_hps_transport.json",
    "config/boards/de1soc_command_path.json",
    "spec/normative/README.md",
]

REQUIRED_PROFILE_FILES = [
    "config/profiles/baseline_core.json",
    "config/profiles/sim_core_only.json",
    "config/profiles/de1soc_bram_replay.json",
    "config/profiles/de1soc_linein_demo.json",
    "config/profiles/de1soc_adc_demo.json",
    "config/profiles/telemetry_status_only.json",
    "config/profiles/telemetry_full_demo.json",
    "config/profiles/README.md",
]

REQUIRED_SCRIPTS = [
    "scripts/gen_headers.py",
    "scripts/gen_filelists.py",
    "scripts/check_profiles.py",
    "scripts/check_hps_platform.py",
    "scripts/check_csr_adapter.py",
    "scripts/check_platform_designer_wrapper.py",
    "scripts/check_source_core_integration.py",
    "scripts/check_core_telemetry_composition.py",
    "scripts/check_de1soc_board_top.py",
    "scripts/check_de1soc_clock_reset.py",
    "scripts/check_de1soc_audio_path.py",
    "scripts/check_de1soc_adc_path.py",
    "scripts/check_bram_replay_path.py",
    "scripts/check_ddr_ring_ownership.py",
    "scripts/check_hps_transport.py",
    "scripts/check_command_path.py",
    "scripts/sim/check_step16_audio_model.py",
    "scripts/sim/check_step17_adc_model.py",
    "scripts/import_de1soc_hps_preset.py",
    "scripts/lint_repo_layout.py",
    "scripts/check_generated.py",
    "scripts/package_artifacts.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/write_platform_generation_manifest.py",
    "scripts/clean_outputs.sh",
    "scripts/format.sh",
    "scripts/lint.sh",
    "scripts/quartus/build_de1soc.sh",
    "scripts/quartus/program_sof.sh",
    "scripts/quartus/export_project.sh",
    "sw/hps/scripts/run_udp_streamer.sh",
]

REQUIRED_PLATFORM_CONFIGS = [
    "platform/de1soc/qsys/hps_config.tcl",
    "platform/de1soc/qsys/platform_designer.tcl",
    "platform/de1soc/qsys/generate_system.sh",
    "platform/de1soc/qsys/system_blueprint.xml",
    "platform/de1soc/qsys/system.qsys",
    "platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv",
    "platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json",
    "platform/de1soc/qsys/presets/README.md",
    "platform/de1soc/address_map/address_map.md",
    "platform/de1soc/address_map/hps_bridge_regions.json",
    "platform/de1soc/address_map/avalon_csr_adapter.json",
    "platform/de1soc/address_map/platform_designer_wrapper.json",
    "platform/de1soc/linux/trecap_reserved_memory.dtsi",
    "rtl/platform/de1soc/platform_designer_wrapper.sv",
]

GENERATED_OUTPUTS = [
    "spec/generated/gen_manifest.json",
    "rtl/include/generated/trecap_core_pkg.sv",
    "rtl/include/generated/trecap_csr_pkg.sv",
    "rtl/include/generated/trecap_packet_pkg.sv",
    "rtl/include/generated/trecap_iface_pkg.sv",
    "sw/hps/include/generated/trecap_csr.h",
    "sw/hps/include/generated/trecap_packet.h",
    "sw/pc_dashboard/generated/trecap_packet.py",
    "sw/reference_model/generated/trecap_config.py",
]

REQUIRED_FILELISTS = [
    "filelists/rtl_core.f",
    "filelists/rtl_core_plus_fft.f",
    "filelists/rtl_telemetry.f",
    "filelists/rtl_core_telemetry.f",
    "filelists/rtl_hps_bridge.f",
    "filelists/rtl_bram_replay_system.f",
    "filelists/rtl_de1soc_full.f",
    "filelists/quartus_de1soc.qsf.inc",
]

REQUIRED_MILESTONE_SOURCES = [
    "rtl/platform/de1soc/audio_pll_wrapper.sv",
    "rtl/platform/de1soc/audio_codec_i2c_init.sv",
    "rtl/platform/de1soc/adc_wrapper.sv",
    "rtl/hps_bridge/trecap_csr_bank.sv",
    "rtl/hps_bridge/trecap_csr_shadow_commit.sv",
    "rtl/hps_bridge/trecap_ddr_record_builder.sv",
    "rtl/hps_bridge/trecap_ddr_ring_writer.sv",
    "rtl/hps_bridge/trecap_hps_bridge_top.sv",
    "rtl/hps_bridge/trecap_ring_pointer_ctrl.sv",
    "scripts/sim/check_step12_ddr_ring_model.py",
    "sim/check_step14_command_rtl.py",
    "scripts/windows/run_step11_bram_e2e.ps1",
    "scripts/windows/run_step12_ddr_ring_ownership.ps1",
    "sim/filelists/step11_bram_e2e.f",
    "sim/filelists/step12_ddr_ring_ownership.f",
    "sim/filelists/step14_command_csr.f",
    "sim/tb/tb_trecap_step11_bram_e2e.sv",
    "sim/tb/tb_trecap_step12_ddr_ring_ownership.sv",
    "sim/tb/tb_trecap_step14_command_csr.sv",
    "sw/hps/config/trecap_hps_config.json",
    "sw/hps/Makefile",
    "sw/hps/include/command_server.h",
    "sw/hps/include/csr_map.h",
    "sw/hps/include/ring_reader.h",
    "sw/hps/include/status_patch.h",
    "sw/hps/scripts/reserve_ddr_region_notes.md",
    "sw/hps/src/config.c",
    "sw/hps/src/ring_reader.c",
    "sw/hps/src/trecap_udp_streamer.c",
    "sw/hps/include/trecap_hps_config.h",
    "sw/hps/include/udp_sender.h",
    "sw/hps/include/generated/trecap_csr.h",
    "sw/hps/include/generated/trecap_packet.h",
    "sw/hps/src/main.c",
    "sw/hps/src/command_server.c",
    "sw/hps/src/csr_map.c",
    "sw/hps/src/status_patch.c",
    "sw/hps/src/udp_sender.c",
    "sw/hps/scripts/run_udp_streamer.sh",
    "sw/hps/systemd/trecap_udp_streamer.service",
    "sw/hps/tests/test_step13_hps_transport.c",
    "sw/hps/include/command_bridge.h",
    "sw/hps/src/command_bridge.c",
    "sw/hps/tests/test_step14_command_path.c",
    "sw/pc_dashboard/tests/test_step14_command_client.py",
    "tests/test_gen_headers_csr_freeze.py",
    "tests/test_command_path_contract_freeze.py",
]

FORBIDDEN_PHASE1_ROOT_FILES = [
    "t_recap_demo_top.sv",
    "golden_model.cpp",
    "viz.py",
    "run.py",
    "x.memh",
    "y.memh",
    "sup.memh",
    "metrics.json",
    "tb_top.sv",
    "tb_pkg.sv",
    "board_if.sv",
    "tap_if.sv",
    "bind_taps.sv",
    "board_driver.sv",
    "ref_model_phase1.sv",
    "golden_files_loader.sv",
    "x_stream_monitor.sv",
    "y_stream_monitor.sv",
    "pair_monitor.sv",
    "io_monitor.sv",
    "metrics_monitor.sv",
    "scoreboard_pairs.sv",
    "scoreboard_y_stream.sv",
    "scoreboard_metrics.sv",
    "cov_phase1.sv",
    "sva_phase1_bind.sv",
    "test_base.sv",
    "test_bypass_lossless.sv",
    "test_golden_thresh16.sv",
    "test_threshold_sweep.sv",
    "test_clear_metrics_midrun.sv",
    "test_mode_switch_stress.sv",
]

FORBIDDEN_ROOT_PATTERNS = [
    "tb_top.sv.bak*",
    "*.wlf",
    "*.vcd",
    "*.fst",
    "*.ghw",
    "transcript",
    "modelsim.ini",
    "*.sof",
    "*.pof",
    "*.qpf",
    "*.qsf",
]

GENERATED_PREFIXES = [
    "rtl/include/generated/",
    "sw/hps/include/generated/",
    "sw/pc_dashboard/generated/",
    "sw/reference_model/generated/",
    "filelists/",
]

SKIP_TEXT_DIRS = {
    ".git",
    ".venv",
    "build",
    "out",
    "runs",
    "audio_work",
    "adc_work",
    "__pycache__",
    ".pytest_cache",
    "legacy",
    "artifacts/reference_outputs",
    "artifacts/telemetry_captures",
}

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".sh",
    ".sv",
    ".v",
    ".vh",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".f",
    ".inc",
    ".tcl",
    ".qsf",
    ".sdc",
    ".dts",
    ".dtsi",
    ".txt",
}


@dataclass
class Finding:
    level: str
    message: str


class Reporter:
    def __init__(self) -> None:
        self.findings: List[Finding] = []

    def error(self, message: str) -> None:
        self.findings.append(Finding("ERROR", message))

    def warn(self, message: str) -> None:
        self.findings.append(Finding("WARN", message))

    def ok(self) -> bool:
        return not any(f.level == "ERROR" for f in self.findings)

    def emit(self, verbose: bool = False) -> None:
        errors = [f for f in self.findings if f.level == "ERROR"]
        warnings = [f for f in self.findings if f.level == "WARN"]
        for f in errors + warnings:
            print(f"{f.level}: {f.message}")
        if verbose or not self.findings:
            print(
                f"lint_repo_layout: {'OK' if not errors else 'FAIL'} "
                f"({len(errors)} errors, {len(warnings)} warnings)"
            )


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def read_json(root: Path, path: str, reporter: Reporter) -> object | None:
    p = root / path
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        reporter.error(f"invalid JSON in {path}: {exc}")
    except OSError as exc:
        reporter.error(f"cannot read {path}: {exc}")
    return None


def parse_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().replace("_", "")
        if text.lower().startswith("0x"):
            return int(text, 16)
        return int(text, 10)
    raise ValueError(f"cannot parse integer from {value!r}")


def should_skip_path(path: Path) -> bool:
    parts = set(path.parts)
    if parts & {
        ".git", ".venv", ".nox", ".tox", "build", "out", "runs",
        "__pycache__", ".pytest_cache", "test-results"
    }:
        return True
    as_posix = path.as_posix()
    return any(as_posix.startswith(skip + "/") or as_posix == skip for skip in SKIP_TEXT_DIRS)


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        r = rel(root, path)
        if should_skip_path(Path(r)):
            continue
        if path.suffix in TEXT_SUFFIXES:
            yield path


def check_required_paths(root: Path, reporter: Reporter) -> None:
    for path in REQUIRED_ROOT_FILES:
        if not (root / path).is_file():
            reporter.error(f"required root file missing: {path}")
    for path in REQUIRED_DIRS:
        if not (root / path).is_dir():
            reporter.error(f"required directory missing: {path}")
    for group_name, files in [
        ("documentation", REQUIRED_DOC_FILES),
        ("hand-written contract", REQUIRED_HAND_WRITTEN_CONTRACTS),
        ("runtime/build profile", REQUIRED_PROFILE_FILES),
        ("script", REQUIRED_SCRIPTS),
        ("platform configuration", REQUIRED_PLATFORM_CONFIGS),
        ("generated output", GENERATED_OUTPUTS),
        ("filelist", REQUIRED_FILELISTS),
        ("milestone source", REQUIRED_MILESTONE_SOURCES),
    ]:
        for path in files:
            if not (root / path).is_file():
                reporter.error(f"required {group_name} file missing: {path}")


def check_root_pollution(root: Path, reporter: Reporter) -> None:
    for name in FORBIDDEN_PHASE1_ROOT_FILES:
        if (root / name).exists():
            reporter.error(f"forbidden Phase 1/root artifact at repository root: {name}")
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        for pattern in FORBIDDEN_ROOT_PATTERNS:
            if fnmatch.fnmatch(path.name, pattern):
                reporter.error(f"forbidden generated/simulator/project output at repository root: {path.name}")


def check_json_contracts(root: Path, reporter: Reporter) -> None:
    csr = read_json(root, "spec/generated/csr_map.json", reporter)
    packets = read_json(root, "spec/generated/packet_layouts.json", reporter)
    iface = read_json(root, "spec/generated/interface_types.json", reporter)
    read_json(root, "spec/generated/gen_manifest.json", reporter)
    for path in [
        "spec/schemas/csr_map.schema.json",
        "spec/schemas/packet_layouts.schema.json",
        "spec/schemas/interface_types.schema.json",
    ]:
        read_json(root, path, reporter)

    if isinstance(csr, dict):
        version = csr.get("constants", {}).get("VERSION", {})
        if isinstance(version, dict):
            packed = (parse_int(version.get("major", 0)) << 16) | parse_int(version.get("minor", 0))
            declared = parse_int(version.get("packed_hex", 0))
            if packed != declared:
                reporter.error("csr_map VERSION packed_hex does not match major/minor")
        seen_offsets: dict[int, str] = {}
        for reg in csr.get("registers", []):
            if not isinstance(reg, dict):
                reporter.error("csr_map register entry is not an object")
                continue
            off = parse_int(reg.get("offset", 0))
            name = str(reg.get("name", "<unnamed>"))
            if off % 4 != 0:
                reporter.error(f"CSR offset for {name} is not 32-bit aligned: 0x{off:x}")
            if off in seen_offsets:
                reporter.error(f"duplicate CSR offset 0x{off:x}: {seen_offsets[off]} and {name}")
            seen_offsets[off] = name

    if isinstance(packets, dict):
        tr = packets.get("transport", {})
        if isinstance(tr, dict):
            header = parse_int(tr.get("telemetry_header_bytes", 0))
            max_udp = parse_int(tr.get("udp_no_fragment_payload_max_bytes", 0))
            if header != 32:
                reporter.error(f"telemetry_header_bytes must be 32, got {header}")
            if max_udp != 1200:
                reporter.error(f"udp_no_fragment_payload_max_bytes must be 1200, got {max_udp}")
        packet_codes: dict[int, str] = {}
        for pkt in packets.get("packet_types", []):
            code = parse_int(pkt.get("code", 0))
            name = str(pkt.get("name", "<unnamed>"))
            if code in packet_codes:
                reporter.error(f"duplicate packet type 0x{code:04x}: {packet_codes[code]} and {name}")
            packet_codes[code] = name
        required_packets = {"WAVE", "SPEC64", "SPEC129", "METRICS", "STATUS", "WRAP"}
        missing = required_packets - set(packet_codes.values())
        if missing:
            reporter.error(f"packet_layouts missing required packet types: {sorted(missing)}")

    if isinstance(iface, dict):
        package = iface.get("package", {})
        if isinstance(package, dict) and package.get("name") != "trecap_iface_pkg":
            reporter.error("interface_types package.name must be trecap_iface_pkg")


def check_generated_banners(root: Path, reporter: Reporter) -> None:
    for path in GENERATED_OUTPUTS:
        if path == "spec/generated/gen_manifest.json":
            continue
        p = root / path
        if not p.exists():
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:512]
        except OSError as exc:
            reporter.error(f"cannot read generated output {path}: {exc}")
            continue
        if "AUTO-GENERATED - DO NOT EDIT" not in head:
            reporter.error(f"generated output missing no-edit banner: {path}")


def check_filelists(root: Path, reporter: Reporter) -> None:
    for path in REQUIRED_FILELISTS:
        p = root / path
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "legacy/" in text or "legacy\\" in text:
            reporter.error(f"generated filelist includes quarantined legacy path: {path}")
        if not path.endswith(("rtl_de1soc_full.f", "quartus_de1soc.qsf.inc")):
            for board_only in (
                "rtl/platform/de1soc/audio_pll_wrapper.sv",
                "rtl/platform/de1soc/audio_codec_i2c_init.sv",
            ):
                if board_only in text:
                    reporter.error(f"{path} must not include Step-16 board-only source {board_only}")
        if path.endswith("rtl_telemetry.f") and "trecap_ddr_ring_writer.sv" in text:
            reporter.error("rtl_telemetry.f must not include trecap_ddr_ring_writer.sv")
        if path.endswith("rtl_telemetry.f") and (
            "rtl/core/trecap_core_top.sv" in text
            or "rtl/top/trecap_core_telemetry_top.sv" in text
        ):
            reporter.error("rtl_telemetry.f must remain a telemetry-only compile closure")
        if path.endswith("rtl_core_telemetry.f"):
            for required in (
                "rtl/core/trecap_core_top.sv",
                "rtl/telemetry/trecap_telemetry_top.sv",
                "rtl/top/trecap_core_telemetry_top.sv",
            ):
                if text.count(required) != 1:
                    reporter.error(f"rtl_core_telemetry.f must list {required} exactly once")
            if "rtl/hps_bridge/" in text or "rtl/sources/" in text:
                reporter.error(
                    "rtl_core_telemetry.f must not own source selection or the HPS/DDR bridge"
                )
        if path.endswith("rtl_hps_bridge.f") and "rtl/hps_bridge/trecap_ddr_ring_writer.sv" not in text:
            reporter.warn("rtl_hps_bridge.f does not list rtl/hps_bridge/trecap_ddr_ring_writer.sv yet")
        if path.endswith("rtl_hps_bridge.f") and "rtl/hps_bridge/trecap_avmm_csr_adapter.sv" not in text:
            reporter.error("rtl_hps_bridge.f must list rtl/hps_bridge/trecap_avmm_csr_adapter.sv")
        if path.endswith("rtl_core_plus_fft.f") and "trecap_avmm_csr_adapter.sv" in text:
            reporter.error("rtl_core_plus_fft.f must not include the Avalon-MM CSR adapter")
        if path.endswith("rtl_de1soc_full.f") and text.count("rtl/platform/de1soc/platform_designer_wrapper.sv") != 1:
            reporter.error("rtl_de1soc_full.f must list platform_designer_wrapper.sv exactly once")
        if path.endswith("rtl_de1soc_full.f"):
            for required in (
                "rtl/platform/de1soc/audio_pll_wrapper.sv",
                "rtl/platform/de1soc/audio_codec_i2c_init.sv",
                "rtl/platform/de1soc/audio_codec_wrapper.sv",
                "rtl/platform/de1soc/adc_wrapper.sv",
                "rtl/platform/de1soc/clock_reset_ctrl.sv",
                "rtl/top/trecap_de1soc_full_top.sv",
                "rtl/platform/de1soc/de1_soc_trecap_top.sv",
            ):
                if text.count(required) != 1:
                    reporter.error(f"rtl_de1soc_full.f must list {required} exactly once")
        if path.endswith("quartus_de1soc.qsf.inc") and text.count("rtl/platform/de1soc/platform_designer_wrapper.sv") != 1:
            reporter.error("quartus_de1soc.qsf.inc must list platform_designer_wrapper.sv exactly once")
        if path.endswith("quartus_de1soc.qsf.inc"):
            for required in (
                "rtl/platform/de1soc/audio_pll_wrapper.sv",
                "rtl/platform/de1soc/audio_codec_i2c_init.sv",
                "rtl/platform/de1soc/audio_codec_wrapper.sv",
                "rtl/platform/de1soc/adc_wrapper.sv",
                "rtl/platform/de1soc/clock_reset_ctrl.sv",
                "rtl/top/trecap_de1soc_full_top.sv",
                "rtl/platform/de1soc/de1_soc_trecap_top.sv",
            ):
                if text.count(required) != 1:
                    reporter.error(f"quartus_de1soc.qsf.inc must list {required} exactly once")
        if path.endswith(("rtl_core.f", "rtl_core_plus_fft.f", "rtl_de1soc_full.f")):
            integration = "rtl/top/trecap_source_core_integration.sv"
            if text.count(integration) != 1:
                reporter.error(f"{path} must list trecap_source_core_integration.sv exactly once")
        if path.endswith("rtl_de1soc_full.f"):
            if "rtl/top/trecap_core_telemetry_top.sv" in text:
                reporter.error(
                    "rtl_de1soc_full.f must not include the standalone second-core composition"
                )
            integration_pos = text.find("rtl/top/trecap_source_core_integration.sv")
            pll_pos = text.find("rtl/platform/de1soc/audio_pll_wrapper.sv")
            i2c_pos = text.find("rtl/platform/de1soc/audio_codec_i2c_init.sv")
            audio_pos = text.find("rtl/platform/de1soc/audio_codec_wrapper.sv")
            board_pos = text.find("rtl/platform/de1soc/de1_soc_trecap_top.sv")
            if integration_pos < 0 or board_pos < 0 or integration_pos >= board_pos:
                reporter.error("rtl_de1soc_full.f must place source-core integration before board top")
            if min(pll_pos, i2c_pos, audio_pos, board_pos) < 0 or not (
                pll_pos < audio_pos < board_pos and i2c_pos < audio_pos
            ):
                reporter.error(
                    "rtl_de1soc_full.f must place audio PLL/I2C before audio wrapper and board top"
                )
        if path.endswith("quartus_de1soc.qsf.inc"):
            if "rtl/top/trecap_core_telemetry_top.sv" in text:
                reporter.error(
                    "quartus_de1soc.qsf.inc must not include the standalone second-core composition"
                )
            integration = "rtl/top/trecap_source_core_integration.sv"
            if text.count(integration) != 1:
                reporter.error("quartus_de1soc.qsf.inc must list source-core integration exactly once")
            pll_pos = text.find("rtl/platform/de1soc/audio_pll_wrapper.sv")
            i2c_pos = text.find("rtl/platform/de1soc/audio_codec_i2c_init.sv")
            audio_pos = text.find("rtl/platform/de1soc/audio_codec_wrapper.sv")
            board_pos = text.find("rtl/platform/de1soc/de1_soc_trecap_top.sv")
            if min(pll_pos, i2c_pos, audio_pos, board_pos) < 0 or not (
                pll_pos < audio_pos < board_pos and i2c_pos < audio_pos
            ):
                reporter.error(
                    "quartus_de1soc.qsf.inc must place audio PLL/I2C before audio wrapper and board top"
                )


def check_layer_ownership(root: Path, reporter: Reporter) -> None:
    for path in root.rglob("trecap_ddr_ring_writer.sv"):
        r = rel(root, path)
        if r != "rtl/hps_bridge/trecap_ddr_ring_writer.sv":
            reporter.error(f"DDR ring writer is in the wrong layer: {r}")

    for path in root.rglob("trecap_avmm_csr_adapter.sv"):
        r = rel(root, path)
        if r != "rtl/hps_bridge/trecap_avmm_csr_adapter.sv":
            reporter.error(f"Avalon-MM CSR adapter is in the wrong layer: {r}")

    for path in root.rglob("platform_designer_wrapper.sv"):
        r = rel(root, path)
        if r != "rtl/platform/de1soc/platform_designer_wrapper.sv":
            reporter.error(f"Platform Designer wrapper is in the wrong layer: {r}")

    for module_name in ("audio_pll_wrapper.sv", "audio_codec_i2c_init.sv"):
        expected = f"rtl/platform/de1soc/{module_name}"
        for path in root.rglob(module_name):
            r = rel(root, path)
            if r != expected:
                reporter.error(f"Step-16 audio platform module is in the wrong layer: {r}")

    for path in root.rglob("adc_wrapper.sv"):
        r = rel(root, path)
        if r != "rtl/platform/de1soc/adc_wrapper.sv":
            reporter.error(f"Step-17 ADC platform module is in the wrong layer: {r}")

    for path in root.rglob("trecap_source_core_integration.sv"):
        r = rel(root, path)
        if r != "rtl/top/trecap_source_core_integration.sv":
            reporter.error(f"source-core integration is in the wrong layer: {r}")

    core_dir = root / "rtl/core"
    if core_dir.exists():
        forbidden_terms = [
            "trecap_packet_pkg",
            "trecap_csr_pkg",
            "RING_",
            "UDP",
            "packet_type",
            "payload_bytes",
            "avmm",
        ]
        for path in sorted(core_dir.rglob("*.sv")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for term in forbidden_terms:
                if term in text:
                    reporter.error(f"rtl/core must not depend on transport term {term!r}: {rel(root, path)}")
                    break

    telemetry_dir = root / "rtl/telemetry"
    if telemetry_dir.exists():
        for path in sorted(telemetry_dir.rglob("*.sv")):
            name = path.name.lower()
            if "ddr_ring_writer" in name or "avmm_write_master" in name:
                reporter.error(f"DDR/Avalon write master belongs in rtl/hps_bridge, not telemetry: {rel(root, path)}")


def check_line_endings(root: Path, reporter: Reporter, max_files: int | None = None) -> None:
    count = 0
    for path in iter_text_files(root):
        data = path.read_bytes()
        r = rel(root, path)
        if b"\r\n" in data or b"\r" in data:
            reporter.error(f"CRLF/CR line ending detected in source text file: {r}")
        if data and not data.endswith(b"\n"):
            reporter.error(f"source text file missing final newline: {r}")
        count += 1
        if max_files is not None and count >= max_files:
            break


def check_executable_policy(root: Path, reporter: Reporter) -> None:
    for path in REQUIRED_SCRIPTS:
        p = root / path
        if not p.exists():
            continue
        first = p.read_bytes()[:2]
        mode = p.stat().st_mode
        executable = bool(mode & stat.S_IXUSR)
        if first == b"#!" and not executable:
            reporter.error(f"script has shebang but is not executable: {path}")
        if path.endswith(".py") and first != b"#!":
            reporter.error(f"Python tool script missing shebang: {path}")
        if path.endswith(".sh") and first != b"#!":
            reporter.error(f"shell script missing shebang: {path}")


def check_reference_model_staging(root: Path, reporter: Reporter) -> None:
    ref = root / "sw/reference_model"
    if not ref.exists():
        reporter.error("sw/reference_model directory is missing")
        return
    for junk in [".venv", "build", "out", "runs", ".pytest_cache"]:
        if (ref / junk).exists():
            reporter.error(f"do not keep local reference-model output in repo source tree: sw/reference_model/{junk}")
    if (root / "sw/golden").exists() and not (root / "sw/reference_model").exists():
        reporter.warn("sw/golden exists without sw/reference_model; current repo naming should use reference_model")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint the T-RECAP Phase 2 repository layout.")
    parser.add_argument("--root", default=None, help="Repository root. Default: parent of this script directory.")
    parser.add_argument("--verbose", action="store_true", help="Print an OK summary even when no findings exist.")
    parser.add_argument("--skip-line-endings", action="store_true", help="Skip source-text CRLF/final-newline checks.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else repo_root_from_script()
    reporter = Reporter()
    if not (root / "Makefile").is_file():
        reporter.error(f"repository root does not look valid: {root}")
        reporter.emit(verbose=True)
        return 2

    check_required_paths(root, reporter)
    check_root_pollution(root, reporter)
    check_json_contracts(root, reporter)
    check_generated_banners(root, reporter)
    check_filelists(root, reporter)
    check_layer_ownership(root, reporter)
    check_reference_model_staging(root, reporter)
    check_executable_policy(root, reporter)
    if not args.skip_line_endings:
        check_line_endings(root, reporter)

    reporter.emit(verbose=args.verbose)
    return 0 if reporter.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
