#!/usr/bin/env python3
"""Check the frozen DE1-SoC Platform Designer/HPS source contract.

This is a deterministic source/configuration gate.  It does not replace a real
Quartus 20.1 Platform Designer normalization run, SOPCINFO review, pin audit, or
board test.  Those tool-generated checks intentionally remain later steps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import xml.etree.ElementTree as ET


PRESET_REL = Path("platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv")
MANIFEST_REL = Path(
    "platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json"
)
CONFIG_REL = Path("platform/de1soc/qsys/hps_config.tcl")
PD_REL = Path("platform/de1soc/qsys/platform_designer.tcl")
GENERATE_SH_REL = Path("platform/de1soc/qsys/generate_system.sh")
WINDOWS_RUNNER_REL = Path("run_platform_designer.ps1")
QSYS_REL = Path("platform/de1soc/qsys/system.qsys")
BLUEPRINT_REL = Path("platform/de1soc/qsys/system_blueprint.xml")
BRIDGES_REL = Path("platform/de1soc/address_map/hps_bridge_regions.json")
ADDRESS_MD_REL = Path("platform/de1soc/address_map/address_map.md")
SOPCINFO_LOCATION_REL = Path("platform/de1soc/address_map/sopcinfo_location.md")
RUNTIME_REL = Path("sw/hps/config/trecap_hps_config.json")

EXPECTED_BASE_HASH = "57a6d9d4ab09a0b6f88d26908d2f2def38e46a37e2b0f94466411fcabc73be26"
EXPECTED_EFFECTIVE_HASH = "bf0dc533f1a141c2a3d91058501b19b0a6ef5b479619bb4829fe94bea60e0888"
EXPECTED_APPLICATION_HASH = "02c6f1fc1bec86f960d3a7740f38f65ec3931c74458bf338f20c9b9f22f45076"
EXPECTED_UPSTREAM_QSYS_HASH = "e289b9955e64e51fe5a8dc4c4f3f0a82d62eb1741774ae46e989e186504eaf5c"
EXPECTED_PARAMETER_COUNT = 520

REQUIRED_PARAMETERS = {
    "EMAC1_Mode": "RGMII",
    "EMAC1_PinMuxing": "HPS I/O Set 0",
    "F2SDRAM_Type": "Avalon-MM Bidirectional",
    "F2SDRAM_Width": "64",
    "HARD_EMIF": "true",
    "HHP_HPS": "true",
    "LWH2F_Enable": "true",
    "MPU_EVENTS_Enable": "false",
    "SDIO_Mode": "4-bit Data",
    "SDIO_PinMuxing": "HPS I/O Set 0",
    "UART0_Mode": "No Flow Control",
    "UART0_PinMuxing": "HPS I/O Set 0",
    "USB1_Mode": "SDR",
    "USB1_PinMuxing": "HPS I/O Set 0",
}

EXPECTED_PRESET_EXPORTS = {
    "clk_50": ("clk_0.clk_in", "clock", "end", "sink"),
    "reset_n": ("clk_0.clk_in_reset", "reset", "end", "sink"),
    "hps_io": ("hps_0.hps_io", "conduit", "end", "end"),
    "memory": ("hps_0.memory", "conduit", "end", "end"),
    "trecap_csr_lw_master": ("hps_0.h2f_lw_axi_master", "avalon", "start", "master"),
    "trecap_f2h_sdram0": ("hps_0.f2h_sdram0_data", "avalon", "end", "slave"),
    "h2f_reset": ("hps_0.h2f_reset", "reset", "start", "source"),
}

# Active Step-6 graph exports.  The preset manifest above intentionally remains a
# provenance record of the raw HPS boundary and must not be rewritten to match these bridges.
EXPECTED_EXPORTS = {
    **EXPECTED_PRESET_EXPORTS,
    "trecap_csr_lw_master": ("trecap_csr_bridge.m0", "avalon", "start", "master"),
    "trecap_f2h_sdram0": ("trecap_f2h_sdram_bridge.s0", "avalon", "end", "slave"),
    "hps_f2h_cold_reset_req": ("hps_0.f2h_cold_reset_req", "reset", "end", "sink"),
    "hps_f2h_debug_reset_req": ("hps_0.f2h_debug_reset_req", "reset", "end", "sink"),
    "hps_f2h_warm_reset_req": ("hps_0.f2h_warm_reset_req", "reset", "end", "sink"),
    "hps_f2h_stm_hw_events": ("hps_0.f2h_stm_hw_events", "conduit", "end", "end"),
}

EXPECTED_TYPED_CONNECTIONS = {
    ("clk_0.clk", "trecap_csr_bridge.clk", "typed_bridge_clock", None),
    ("clk_0.clk_reset", "trecap_csr_bridge.reset", "typed_bridge_reset", None),
    ("hps_0.h2f_lw_axi_master", "trecap_csr_bridge.s0", "csr_bridge_upstream", "0x00000000"),
    ("clk_0.clk", "trecap_f2h_sdram_bridge.clk", "typed_bridge_clock", None),
    ("clk_0.clk_reset", "trecap_f2h_sdram_bridge.reset", "typed_bridge_reset", None),
    ("trecap_f2h_sdram_bridge.m0", "hps_0.f2h_sdram0_data", "f2h_sdram_bridge_downstream", "0x00000000"),
}

EXPECTED_CLOCK_CONNECTIONS = {
    ("clk_0.clk", "hps_0.f2h_sdram0_clock"),
    ("clk_0.clk", "hps_0.h2f_axi_clock"),
    ("clk_0.clk", "hps_0.f2h_axi_clock"),
    ("clk_0.clk", "hps_0.h2f_lw_axi_clock"),
}


def canonical_parameter_bytes(parameters: dict[str, str]) -> bytes:
    return "".join(f"{name}={parameters[name]}\n" for name in sorted(parameters)).encode(
        "utf-8"
    )


def canonical_application_bytes(modes: dict[str, str]) -> bytes:
    return "".join(f"{name}={modes[name]}\n" for name in sorted(modes)).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an address integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"not an integer: {value!r}")


def require_equal(errors: list[str], label: str, actual: object, expected: object) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, got {actual!r}")


def load_json(root: Path, rel: Path, errors: list[str]) -> dict[str, object]:
    try:
        value = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read {rel}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{rel} must contain a JSON object")
        return {}
    return value


def parse_preset(
    path: Path, errors: list[str]
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    parameters: dict[str, str] = {}
    metadata: dict[str, str] = {}
    modes: dict[str, str] = {}
    previous = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"cannot read {path}: {exc}")
        return parameters, metadata, modes
    for line_number, line in enumerate(lines, 1):
        if not line:
            continue
        if line.startswith("#"):
            match = re.fullmatch(r"# ([A-Za-z0-9_]+)=(.*)", line)
            if match:
                metadata[match.group(1)] = match.group(2)
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            errors.append(f"{path}:{line_number}: preset row must have exactly three columns")
            continue
        name, value, mode = fields
        if mode not in {"set", "readback_only"}:
            errors.append(f"{path}:{line_number}: invalid application mode {mode!r}")
        if name in parameters:
            errors.append(f"{path}:{line_number}: duplicate parameter {name}")
        if previous and name <= previous:
            errors.append(f"{path}:{line_number}: parameters are not strictly sorted")
        parameters[name] = value
        modes[name] = mode
        previous = name
    return parameters, metadata, modes


def parse_cfg(path: Path, errors: list[str]) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read {path}: {exc}")
        return {}
    match = re.search(r"array set cfg \{\n(?P<body>.*?)\n    \}", text, re.DOTALL)
    if not match:
        errors.append(f"cannot locate cfg array in {path}")
        return {}
    cfg: dict[str, str] = {}
    for raw in match.group("body").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            errors.append(f"cannot parse cfg row: {raw}")
            continue
        key, value = parts
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1]
        cfg[key] = value
    return cfg


def check_preset(root: Path, errors: list[str]) -> tuple[dict[str, str], dict[str, object]]:
    parameters, metadata, modes = parse_preset(root / PRESET_REL, errors)
    manifest = load_json(root, MANIFEST_REL, errors)
    require_equal(errors, "preset parameter count", len(parameters), EXPECTED_PARAMETER_COUNT)
    effective_hash = sha256(canonical_parameter_bytes(parameters))
    application_hash = sha256(canonical_application_bytes(modes))
    require_equal(errors, "preset effective hash", effective_hash, EXPECTED_EFFECTIVE_HASH)
    require_equal(
        errors,
        "preset metadata base hash",
        metadata.get("base_parameter_sha256"),
        EXPECTED_BASE_HASH,
    )
    require_equal(errors, "preset application partition hash", application_hash, EXPECTED_APPLICATION_HASH)
    require_equal(
        errors,
        "preset metadata effective hash",
        metadata.get("effective_parameter_sha256"),
        EXPECTED_EFFECTIVE_HASH,
    )
    require_equal(
        errors,
        "preset upstream Qsys hash",
        metadata.get("upstream_qsys_sha256"),
        EXPECTED_UPSTREAM_QSYS_HASH,
    )
    require_equal(
        errors, "preset metadata count", metadata.get("parameter_count"), str(EXPECTED_PARAMETER_COUNT)
    )
    require_equal(errors, "preset applied count", list(modes.values()).count("set"), 476)
    require_equal(
        errors, "preset readback-only count", list(modes.values()).count("readback_only"), 44
    )
    require_equal(
        errors,
        "preset metadata applied count",
        metadata.get("applied_parameter_count"),
        "476",
    )
    require_equal(
        errors,
        "preset metadata readback-only count",
        metadata.get("readback_only_parameter_count"),
        "44",
    )
    require_equal(
        errors,
        "preset metadata application hash",
        metadata.get("application_mode_sha256"),
        EXPECTED_APPLICATION_HASH,
    )
    for name, expected in REQUIRED_PARAMETERS.items():
        require_equal(errors, f"HPS parameter {name}", parameters.get(name), expected)

    snapshot = manifest.get("snapshot", {})
    board = manifest.get("board", {})
    toolchain = manifest.get("toolchain", {})
    hps_component = toolchain.get("hps_component", {}) if isinstance(toolchain, dict) else {}
    if not isinstance(snapshot, dict) or not isinstance(board, dict):
        errors.append("HPS preset manifest snapshot/board sections must be objects")
        return parameters, manifest
    require_equal(errors, "manifest schema", manifest.get("schema"), "trecap_de1soc_hps_preset_manifest_v1")
    require_equal(
        errors,
        "manifest contract stage",
        manifest.get("contract_stage"),
        "step2_platform_designer_hps_source_frozen",
    )
    require_equal(
        errors,
        "manifest address status",
        manifest.get("address_status"),
        "source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff",
    )
    require_equal(errors, "manifest board revision", board.get("source_revision"), "H")
    require_equal(
        errors,
        "manifest physical board status",
        board.get("physical_board_revision_status"),
        "unverified_requires_board_label_confirmation",
    )
    require_equal(errors, "manifest parameter count", snapshot.get("parameter_count"), 520)
    require_equal(
        errors,
        "manifest upstream parameter hash",
        snapshot.get("upstream_parameter_sha256"),
        EXPECTED_BASE_HASH,
    )
    application = snapshot.get("application", {})
    if isinstance(application, dict):
        require_equal(errors, "manifest settable count", application.get("set_parameter_count"), 476)
        require_equal(
            errors,
            "manifest readback-only count",
            application.get("readback_only_parameter_count"),
            44,
        )
        require_equal(
            errors,
            "manifest application hash",
            application.get("application_mode_sha256"),
            EXPECTED_APPLICATION_HASH,
        )
        manifest_readbacks = application.get("readback_only_parameters", [])
        actual_readbacks = sorted(name for name, mode in modes.items() if mode == "readback_only")
        require_equal(errors, "manifest readback-only inventory", manifest_readbacks, actual_readbacks)
    else:
        errors.append("manifest snapshot.application must be an object")
    require_equal(
        errors,
        "manifest effective parameter hash",
        snapshot.get("effective_parameter_sha256"),
        EXPECTED_EFFECTIVE_HASH,
    )
    if isinstance(hps_component, dict):
        require_equal(errors, "manifest HPS kind", hps_component.get("kind"), "altera_hps")
        require_equal(errors, "manifest HPS component version", hps_component.get("version"), "20.1")
    else:
        errors.append("manifest toolchain.hps_component must be an object")

    exports = manifest.get("required_interfaces", {})
    required_interfaces = exports
    clock_parameters = (
        required_interfaces.get("clock_source_parameters", {})
        if isinstance(required_interfaces, dict)
        else {}
    )
    require_equal(
        errors,
        "manifest clock-source parameters",
        clock_parameters,
        {
            "clockFrequency": "50000000",
            "clockFrequencyKnown": "true",
            "resetSynchronousEdges": "NONE",
        },
    )
    exports = exports.get("exports", {}) if isinstance(exports, dict) else {}
    for export_name, (internal, kind, serialized_direction, qsys_tcl_role) in EXPECTED_PRESET_EXPORTS.items():
        entry = exports.get(export_name, {}) if isinstance(exports, dict) else {}
        if not isinstance(entry, dict):
            errors.append(f"manifest export {export_name} must be an object")
            continue
        require_equal(errors, f"manifest {export_name} internal", entry.get("internal"), internal)
        require_equal(errors, f"manifest {export_name} kind", entry.get("kind"), kind)
        require_equal(
            errors,
            f"manifest {export_name} serialized direction",
            entry.get("serialized_direction"),
            serialized_direction,
        )
        require_equal(
            errors,
            f"manifest {export_name} Qsys Tcl role",
            entry.get("qsys_tcl_role"),
            qsys_tcl_role,
        )
    return parameters, manifest


def check_cfg(root: Path, errors: list[str]) -> dict[str, str]:
    cfg = parse_cfg(root / CONFIG_REL, errors)
    expected = {
        "platform_contract_revision": "step6_typed_bridges_source_v1",
        "platform_contract_status": "source_implemented_pending_quartus_normalization_generation_compile",
        "address_map_contract_revision": "step4_frozen_v1",
        "address_map_contract_stage": "step4_address_map_source_frozen",
        "address_map_contract_status": (
            "source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff"
        ),
        "board_revision_profile": "rev_h",
        "physical_board_revision_status": "unverified_requires_board_label_confirmation",
        "quartus_release": "20.1",
        "qsys_api_version": "16.0",
        "qsys_blueprint_rel": "platform/de1soc/qsys/system_blueprint.xml",
        "sopcinfo_location_md_rel": "platform/de1soc/address_map/sopcinfo_location.md",
        "hps_component_type": "altera_hps",
        "hps_component_version": "20.1",
        "hps_preset_parameter_count": "520",
        "hps_preset_base_sha256": EXPECTED_BASE_HASH,
        "hps_preset_effective_sha256": EXPECTED_EFFECTIVE_HASH,
        "hps_preset_application_sha256": EXPECTED_APPLICATION_HASH,
        "hps_preset_applied_parameter_count": "476",
        "hps_preset_readback_parameter_count": "44",
        "transport_version_major": "1",
        "transport_version_minor": "8",
        "fabric_clk_export": "clk_50",
        "fabric_clock_frequency_known": "true",
        "fabric_reset_synchronous_edges": "NONE",
        "fabric_clk_export_role": "sink",
        "fabric_clk_internal": "clk_0.clk",
        "fabric_reset_internal": "clk_0.clk_in_reset",
        "fabric_reset_bridge_internal": "clk_0.clk_reset",
        "hps_bridge_clock_sinks": (
            "f2h_sdram0_clock h2f_axi_clock f2h_axi_clock h2f_lw_axi_clock"
        ),
        "export_hps_io": "1",
        "fabric_reset_export_role": "sink",
        "h2f_lw_master_export_role": "master",
        "f2h_sdram0_export_role": "slave",
        "hps_io_export_role": "end",
        "hps_memory_export_role": "end",
        "h2f_reset_export_direction": "source",
        "f2h_cold_reset_req_export": "hps_f2h_cold_reset_req",
        "f2h_debug_reset_req_export": "hps_f2h_debug_reset_req",
        "f2h_warm_reset_req_export": "hps_f2h_warm_reset_req",
        "f2h_stm_hw_events_export": "hps_f2h_stm_hw_events",
        "h2f_lw_master_export": "trecap_csr_lw_master",
        "h2f_lw_master_internal": "hps_0.h2f_lw_axi_master",
        "h2f_lw_master_export_internal": "trecap_csr_bridge.m0",
        "f2h_sdram0_export": "trecap_f2h_sdram0",
        "f2h_sdram0_internal": "hps_0.f2h_sdram0_data",
        "f2h_sdram0_export_internal": "trecap_f2h_sdram_bridge.s0",
        "csr_bridge_instance": "trecap_csr_bridge",
        "csr_bridge_component_type": "trecap_avalon_csr_bridge",
        "csr_bridge_component_version": "1.0",
        "csr_bridge_upstream_interface": "hps_0.h2f_lw_axi_master",
        "csr_bridge_slave_interface": "trecap_csr_bridge.s0",
        "csr_bridge_master_interface": "trecap_csr_bridge.m0",
        "csr_bridge_address_units": "SYMBOLS",
        "csr_bridge_address_width": "21",
        "csr_bridge_data_width": "32",
        "csr_bridge_symbol_width": "8",
        "csr_bridge_use_response": "1",
        "f2h_sdram_bridge_instance": "trecap_f2h_sdram_bridge",
        "f2h_sdram_bridge_component_type": "altera_avalon_mm_bridge",
        "f2h_sdram_bridge_component_version": "20.1",
        "f2h_sdram_bridge_slave_interface": "trecap_f2h_sdram_bridge.s0",
        "f2h_sdram_bridge_master_interface": "trecap_f2h_sdram_bridge.m0",
        "f2h_sdram_bridge_downstream_interface": "hps_0.f2h_sdram0_data",
        "f2h_sdram_bridge_address_units": "SYMBOLS",
        "f2h_sdram_bridge_address_width": "32",
        "f2h_sdram_bridge_data_width": "64",
        "f2h_sdram_bridge_symbol_width": "8",
        "f2h_sdram_bridge_use_response": "0",
        "ddr_writer_data_width": "64",
        "h2f_lw_master_byte_addr_width": "21",
        "csr_leaf_byte_addr_width": "12",
    }
    for key, value in expected.items():
        require_equal(errors, f"hps_config {key}", cfg.get(key), value)
    for key, value in {
        "h2f_lw_span_bytes": 2 * 1024 * 1024,
        "csr_base_hps_phys": 0xFF200000,
        "csr_span_bytes": 4096,
        "ring_base_hps_phys": 0x3E000000,
        "ring_base_fpga": 0x3E000000,
        "ring_size_bytes": 32 * 1024 * 1024,
    }.items():
        try:
            actual = parse_int(cfg.get(key))
        except (TypeError, ValueError) as exc:
            errors.append(f"hps_config {key} is invalid: {exc}")
        else:
            require_equal(errors, f"hps_config {key}", actual, value)
    return cfg


def check_platform_designer(root: Path, errors: list[str]) -> None:
    try:
        text = (root / PD_REL).read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read {PD_REL}: {exc}")
        return
    required_tokens = [
        "get_instance_parameters",
        "get_instance_parameter_value",
        "set_instance_parameter_value",
        "get_instance_interfaces",
        "validate_instance",
        "validate_system",
        "qsys_validate_strict",
        "reload_ip_catalog",
        "run_static_platform_check",
        "--python-exe",
        "opts(python_exe)",
        "decode_cli_hex",
        "::trecap_pd_cli_hex",
        "qsys_api_value",
        "capture_existing_system_readback",
        "write_hps_readback_capture",
        "hps_readback_pairs",
        "semantic_parameter_value",
        "return {Avalon-MM\\ Bidirectional}",
        "AVL_DATA_WIDTH_PORT",
        "CPORT_TYPE_PORT",
        "DMA_Enable",
        "GPIO_Enable",
        "LOANIO_Enable",
        "PRIORITY_PORT",
        "WEIGHT_PORT",
        "::trecap_hps_config::hps_parameter_pairs",
        "clk_0.clk_in",
        "configure_avalon_mm_bridge",
        "set_connection_parameter_strict",
        "csr_bridge_upstream_interface",
        "csr_bridge_slave_interface",
        "f2h_sdram_bridge_master_interface",
        "f2h_sdram_bridge_downstream_interface",
        "connect HPS lightweight AXI manager to typed CSR bridge",
        "connect typed FPGA write bridge to HPS SDRAM agent",
        "export_interface_strict [::trecap_hps_config::get h2f_lw_master_export]",
        "[::trecap_hps_config::get h2f_lw_master_export_internal]",
        "export_interface_strict [::trecap_hps_config::get f2h_sdram0_export]",
        "[::trecap_hps_config::get f2h_sdram0_export_internal]",
        "${hps}.h2f_reset",
    ]
    for token in required_tokens:
        if token not in text:
            errors.append(f"platform_designer.tcl lacks required strict token: {token}")
    forbidden_tokens = [
        "get_instance_parameter_names",
        "hps_io_hps_io",
        "f2h_sdram0_slave",
        "h2f_lw_axi_reset",
        "h2f_mpu_events_export",
        "add_or_reuse_instance rst_in",
        "proc ::trecap_pd::qsys_try",
        "file delete -force $qsys_file",
        "set_system_property",
    ]
    for token in forbidden_tokens:
        if token in text:
            errors.append(f"platform_designer.tcl still contains guessed/obsolete token: {token}")
    if not re.search(r"strict_exports\s+1", text):
        errors.append("platform_designer.tcl is not strict by default")

    wrapper_contracts = {
        GENERATE_SH_REL: [
            "qsys_tcl_command_for_argv",
            "set ::trecap_pd_cli_hex",
            '"--cmd=${qsys_tcl_cmd}"',
            "QSYS_GENERATE",
            "--mode construct",
            "--mode capture-readback",
            "--synthesis=VERILOG",
            "write_platform_generation_manifest.py",
        ],
        WINDOWS_RUNNER_REL: [
            "Run-QsysScriptLogged",
            "ConvertTo-Utf8Hex",
            "$ForwardedTclArgs",
            '"--python-exe"',
            "-PythonExe $PythonExe",
            "set ::trecap_pd_cli_hex",
            '"--cmd=$TclCommand"',
            "qsys-generate.exe",
            '"construct"',
            '"capture-readback"',
            "write_platform_generation_manifest.py",
        ],
    }
    wrapper_texts: dict[Path, str] = {}
    for rel, required in wrapper_contracts.items():
        try:
            wrapper_text = (root / rel).read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read {rel}: {exc}")
            continue
        wrapper_texts[rel] = wrapper_text
        for token in required:
            if token not in wrapper_text:
                errors.append(f"{rel} lacks documented qsys-script --cmd transport token: {token}")
    bash_wrapper = wrapper_texts.get(GENERATE_SH_REL, "")
    if '--script="${PD_TCL}" -- ' in bash_wrapper:
        errors.append(f"{GENERATE_SH_REL} still uses unsupported bare -- argument forwarding")
    windows_wrapper = wrapper_texts.get(WINDOWS_RUNNER_REL, "")
    if '"--script=$PdTcl", "--"' in windows_wrapper:
        errors.append(f"{WINDOWS_RUNNER_REL} still uses unsupported bare -- argument forwarding")
    if os.name != "nt":
        try:
            generate_mode = (root / GENERATE_SH_REL).stat().st_mode
        except OSError as exc:
            errors.append(f"cannot stat platform/de1soc/qsys/generate_system.sh: {exc}")
        else:
            if not generate_mode & stat.S_IXUSR:
                errors.append("platform/de1soc/qsys/generate_system.sh is not executable")


def check_qsys_blueprint(root: Path, errors: list[str]) -> None:
    try:
        tree = ET.parse(root / BLUEPRINT_REL)
    except (OSError, ET.ParseError) as exc:
        errors.append(f"cannot parse {BLUEPRINT_REL}: {exc}")
        return
    system = tree.getroot()
    require_equal(
        errors,
        "Platform Designer blueprint schema",
        system.get("schema"),
        "trecap_phase2_platform_designer_blueprint_v1",
    )
    metadata = {item.get("key"): item.get("value") for item in system.findall("./metadata")}
    for key, expected in {
        "contract_stage": "step6_platform_designer_typed_bridges_source_implemented",
        "contract_status": "source_implemented_pending_quartus_normalization_generation_compile",
        "board_revision_profile": "rev_h",
        "physical_board_revision_status": "unverified_requires_board_label_confirmation",
        "quartus_release": "20.1",
        "qsys_api_version": "16.0",
        "hps_component_version": "20.1",
        "hps_preset_effective_sha256": EXPECTED_EFFECTIVE_HASH,
        "hps_preset_applied_parameter_count": "476",
        "hps_preset_readback_parameter_count": "44",
        "hps_preset_application_sha256": EXPECTED_APPLICATION_HASH,
        "address_contract_stage": "step4_address_map_source_frozen",
        "address_contract_status": (
            "source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff"
        ),
        "address_contract_file": "platform/de1soc/address_map/hps_bridge_regions.json",
        "sopcinfo_location_document": "platform/de1soc/address_map/sopcinfo_location.md",
        "address_status": "source_frozen_hardware_evidence_pending",
        "h2f_lw_base_hps_phys": "0xff200000",
        "h2f_lw_span_bytes": "2097152",
        "h2f_lw_master_byte_address_width_bits": "21",
        "csr_leaf_byte_address_width_bits": "12",
        "csr_offset_in_lw": "0",
        "csr_hps_physical_base": "0xff200000",
        "csr_span_bytes": "4096",
        "ring_base_hps_phys": "0x3e000000",
        "ring_base_fpga_visible": "0x3e000000",
        "ring_size_bytes": "33554432",
        "ring_alignment_bytes": "64",
        "csr_bridge_instance": "trecap_csr_bridge",
        "csr_bridge_export_internal": "trecap_csr_bridge.m0",
        "csr_bridge_connection_base_address": "0x00000000",
        "f2h_sdram_bridge_instance": "trecap_f2h_sdram_bridge",
        "f2h_sdram_export_internal": "trecap_f2h_sdram_bridge.s0",
        "f2h_sdram_bridge_connection_base_address": "0x00000000",
        "f2h_sdram_bridge_byte_address_width_bits": "32",
    }.items():
        require_equal(errors, f"blueprint metadata {key}", metadata.get(key), expected)
    hps = system.find("./planned_instances/instance[@name='hps_0']")
    if hps is None:
        errors.append("Platform Designer blueprint lacks planned hps_0 instance")
        return
    params = {item.get("name"): item.get("value") for item in hps.findall("./parameter")}
    for name, expected in REQUIRED_PARAMETERS.items():
        require_equal(errors, f"blueprint planned parameter {name}", params.get(name), expected)
    clock = system.find("./planned_instances/instance[@name='clk_0']")
    if clock is None:
        errors.append("Platform Designer blueprint lacks planned clk_0 instance")
    else:
        clock_params = {
            item.get("name"): item.get("value") for item in clock.findall("./parameter")
        }
        require_equal(
            errors,
            "blueprint clock-source parameters",
            clock_params,
            {
                "clockFrequency": "50000000",
                "clockFrequencyKnown": "true",
                "resetSynchronousEdges": "NONE",
            },
        )
    exports = {
        item.get("name"): (item.get("internal"), item.get("kind"), item.get("direction"))
        for inst in system.findall("./planned_instances/instance")
        for item in inst.findall("./export")
    }
    for name, expected in EXPECTED_EXPORTS.items():
        require_equal(errors, f"blueprint export {name}", exports.get(name), expected[:3])

    expected_bridge_parameters = {
        "trecap_csr_bridge": {
            "ADDRESS_UNITS": "SYMBOLS",
            "ADDRESS_WIDTH": "21",
            "DATA_WIDTH": "32",
            "LINEWRAPBURSTS": "0",
            "MAX_BURST_SIZE": "1",
            "MAX_PENDING_RESPONSES": "1",
            "PIPELINE_COMMAND": "0",
            "PIPELINE_RESPONSE": "0",
            "SYMBOL_WIDTH": "8",
            "USE_AUTO_ADDRESS_WIDTH": "0",
            "USE_RESPONSE": "1",
        },
        "trecap_f2h_sdram_bridge": {
            "ADDRESS_UNITS": "SYMBOLS",
            "ADDRESS_WIDTH": "32",
            "DATA_WIDTH": "64",
            "LINEWRAPBURSTS": "0",
            "MAX_BURST_SIZE": "1",
            "MAX_PENDING_RESPONSES": "1",
            "PIPELINE_COMMAND": "1",
            "PIPELINE_RESPONSE": "1",
            "SYMBOL_WIDTH": "8",
            "USE_AUTO_ADDRESS_WIDTH": "0",
            "USE_RESPONSE": "0",
        },
    }
    for instance_name, expected_parameters in expected_bridge_parameters.items():
        instance = system.find(f"./planned_instances/instance[@name='{instance_name}']")
        if instance is None:
            errors.append(f"Platform Designer blueprint lacks {instance_name}")
            continue
        expected_kind, expected_version = (
            ("trecap_avalon_csr_bridge", "1.0")
            if instance_name == "trecap_csr_bridge"
            else ("altera_avalon_mm_bridge", "20.1")
        )
        require_equal(errors, f"{instance_name} kind", instance.get("kind"), expected_kind)
        require_equal(errors, f"{instance_name} version", instance.get("version"), expected_version)
        actual_parameters = {
            item.get("name"): item.get("value") for item in instance.findall("./parameter")
        }
        require_equal(errors, f"{instance_name} parameters", actual_parameters, expected_parameters)
    connections = {
        (item.get("source"), item.get("sink"))
        for item in system.findall("./planned_connections/connection")
        if item.get("role") == "hps_bridge_clock"
    }
    require_equal(errors, "blueprint HPS clock connections", connections, EXPECTED_CLOCK_CONNECTIONS)
    typed_connections = {
        (item.get("source"), item.get("sink"), item.get("role"), item.get("baseAddress"))
        for item in system.findall("./planned_connections/connection")
        if item.get("role") != "hps_bridge_clock"
    }
    require_equal(errors, "blueprint typed bridge connections", typed_connections, EXPECTED_TYPED_CONNECTIONS)


def check_working_qsys_state(root: Path, errors: list[str]) -> None:
    path = root / QSYS_REL
    try:
        data = path.read_bytes()
        system = ET.fromstring(data)
    except (OSError, ET.ParseError) as exc:
        errors.append(f"cannot parse working {QSYS_REL}: {exc}")
        return
    tag = system.tag.rsplit("}", 1)[-1]
    require_equal(errors, "working Qsys root element", tag, "system")
    is_bootstrap = b"T_RECAP_BOOTSTRAP_QSYS_SOURCE=1" in data
    system_name = system.get("name")
    # Quartus 20.1 serializes the filename placeholder, resolved by generation
    # from the canonical source filename. Bootstrap names remain explicit.
    if (
        not is_bootstrap
        and system_name == "$${FILENAME}"
        and path.name == "system.qsys"
        and path.resolve().name == "system.qsys"
    ):
        system_name = path.stem
    require_equal(errors, "working Qsys system name", system_name, "system")
    working_metadata = {
        item.get("key"): item.get("value") for item in system.findall("./metadata")
    }
    if is_bootstrap:
        # Project transport metadata is owned by the bootstrap/configuration;
        # the vendor-normalized format does not serialize this metadata.
        require_equal(
            errors,
            "working Qsys transport version",
            working_metadata.get("transport_version"),
            "1.8",
        )
        require_equal(
            errors,
            "working Qsys bootstrap schema",
            system.get("schema"),
            "trecap_phase2_platform_designer_bootstrap_v2",
        )
        try:
            blueprint = ET.parse(root / BLUEPRINT_REL).getroot()
        except (OSError, ET.ParseError) as exc:
            errors.append(f"cannot compare bootstrap to {BLUEPRINT_REL}: {exc}")
            return
        blueprint_metadata = {
            item.get("key"): item.get("value") for item in blueprint.findall("./metadata")
        }
        for key, value in blueprint_metadata.items():
            require_equal(errors, f"working bootstrap metadata {key}", working_metadata.get(key), value)
        for instance_name in (
            "clk_0",
            "hps_0",
            "trecap_csr_bridge",
            "trecap_f2h_sdram_bridge",
        ):
            blueprint_instance = blueprint.find(
                f"./planned_instances/instance[@name='{instance_name}']"
            )
            working_instance = system.find(
                f"./planned_instances/instance[@name='{instance_name}']"
            )
            if blueprint_instance is None or working_instance is None:
                errors.append(f"working/bootstrap blueprint lacks instance {instance_name}")
                continue
            blueprint_parameters = {
                item.get("name"): item.get("value")
                for item in blueprint_instance.findall("./parameter")
            }
            working_parameters = {
                item.get("name"): item.get("value")
                for item in working_instance.findall("./parameter")
            }
            for name, value in blueprint_parameters.items():
                require_equal(
                    errors,
                    f"working bootstrap {instance_name}.{name}",
                    working_parameters.get(name),
                    value,
                )
            blueprint_exports = {
                item.get("name"): (
                    item.get("internal"),
                    item.get("kind"),
                    item.get("direction"),
                )
                for item in blueprint_instance.findall("./export")
            }
            working_exports = {
                item.get("name"): (
                    item.get("internal"),
                    item.get("kind"),
                    item.get("direction"),
                )
                for item in working_instance.findall("./export")
            }
            require_equal(
                errors,
                f"working bootstrap {instance_name} exports",
                working_exports,
                blueprint_exports,
            )
        blueprint_connections = {
            (item.get("source"), item.get("sink"), item.get("role"))
            for item in blueprint.findall("./planned_connections/connection")
        }
        working_connections = {
            (item.get("source"), item.get("sink"), item.get("role"))
            for item in system.findall("./planned_connections/connection")
        }
        require_equal(
            errors,
            "working bootstrap planned connections",
            working_connections,
            blueprint_connections,
        )
    elif system.get("schema") in {
        "trecap_phase2_platform_designer_bootstrap_v2",
        "trecap_phase2_platform_designer_blueprint_v1",
    }:
        errors.append("working system.qsys claims a hand-written schema without its bootstrap marker")
    else:
        # Inspect the vendor XML directly rather than treating the accepted
        # filename placeholder as evidence of a correctly configured system.
        parameters = {
            item.get("name"): item.get("value") for item in system.findall("./parameter")
        }
        require_equal(errors, "normalized Qsys device", parameters.get("device"), "5CSEMA5F31C6")
        require_equal(errors, "normalized Qsys family", parameters.get("deviceFamily"), "Cyclone V")
        expected_modules = {
            "clk_0": ("clock_source", "20.1", "1"),
            "hps_0": ("altera_hps", "20.1", "1"),
            "trecap_csr_bridge": ("trecap_avalon_csr_bridge", "1.0", "1"),
            "trecap_f2h_sdram_bridge": ("altera_avalon_mm_bridge", "20.1", "1"),
        }
        modules = system.findall("./module")
        require_equal(errors, "normalized Qsys module count", len(modules), len(expected_modules))
        require_equal(
            errors,
            "normalized Qsys modules",
            {item.get("name"): (item.get("kind"), item.get("version"), item.get("enabled")) for item in modules},
            expected_modules,
        )
        interfaces = system.findall("./interface")
        require_equal(errors, "normalized Qsys export count", len(interfaces), len(EXPECTED_EXPORTS))
        require_equal(
            errors,
            "normalized Qsys exports",
            {item.get("name"): (item.get("internal"), item.get("type"), item.get("dir")) for item in interfaces},
            {name: definition[:3] for name, definition in EXPECTED_EXPORTS.items()},
        )
        expected_connections = {
            (start, end, "clock") for start, end in EXPECTED_CLOCK_CONNECTIONS
        } | {
            (start, end, "clock" if role == "typed_bridge_clock" else "reset" if role == "typed_bridge_reset" else "avalon")
            for start, end, role, _ in EXPECTED_TYPED_CONNECTIONS
        }
        connections = system.findall("./connection")
        require_equal(errors, "normalized Qsys connection count", len(connections), len(expected_connections))
        require_equal(
            errors,
            "normalized Qsys connections",
            {(item.get("start"), item.get("end"), item.get("kind")) for item in connections},
            expected_connections,
        )
        for item in connections:
            if item.get("kind") == "avalon":
                base = item.find("./parameter[@name='baseAddress']")
                try:
                    base_value = parse_int(None if base is None else base.get("value"))
                except ValueError:
                    errors.append(f"normalized Qsys connection {item.get('start')} has no valid baseAddress")
                    continue
                require_equal(errors, f"normalized Qsys {item.get('start')} baseAddress", base_value, 0)


def check_address_parity(root: Path, cfg: dict[str, str], errors: list[str]) -> None:
    bridge = load_json(root, BRIDGES_REL, errors)
    runtime = load_json(root, RUNTIME_REL, errors)
    require_equal(
        errors,
        "bridge contract stage",
        bridge.get("contract_stage"),
        "step4_address_map_source_frozen",
    )
    require_equal(
        errors,
        "bridge status",
        bridge.get("status"),
        "source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff",
    )
    board_profile = bridge.get("board_profile", {})
    if isinstance(board_profile, dict):
        require_equal(errors, "bridge board source revision", board_profile.get("source_revision"), "H")
        require_equal(
            errors,
            "bridge physical board status",
            board_profile.get("physical_board_revision_status"),
            "unverified_requires_board_label_confirmation",
        )
    else:
        errors.append("bridge board_profile must be an object")
    pd = bridge.get("platform_designer", {})
    if isinstance(pd, dict):
        require_equal(errors, "bridge HPS component version", pd.get("hps_component_version"), "20.1")
        require_equal(errors, "bridge HPS parameter count", pd.get("hps_parameter_count"), 520)
        require_equal(errors, "bridge HPS applied count", pd.get("hps_applied_parameter_count"), 476)
        require_equal(
            errors,
            "bridge HPS readback-only count",
            pd.get("hps_readback_only_parameter_count"),
            44,
        )
        require_equal(
            errors,
            "bridge HPS application hash",
            pd.get("hps_preset_application_sha256"),
            EXPECTED_APPLICATION_HASH,
        )
        require_equal(errors, "bridge F2SDRAM type", pd.get("f2sdram_type"), "Avalon-MM Bidirectional")
        require_equal(errors, "bridge F2SDRAM width", pd.get("f2sdram_width_bits"), 64)
    else:
        errors.append("bridge platform_designer must be an object")
    exports = bridge.get("exports", {})
    if isinstance(exports, dict):
        require_equal(errors, "bridge reset Qsys Tcl role", exports.get("h2f_reset_direction"), "source")
        require_equal(
            errors,
            "bridge reset serialized direction",
            exports.get("h2f_reset_serialized_direction"),
            "start",
        )
    else:
        errors.append("bridge exports must be an object")

    csr_bridge = bridge.get("bridges", {})
    csr_bridge = csr_bridge.get("csr_bridge", {}) if isinstance(csr_bridge, dict) else {}
    ddr_bridge = bridge.get("bridges", {})
    ddr_bridge = ddr_bridge.get("ddr_writer_bridge", {}) if isinstance(ddr_bridge, dict) else {}
    checks = [
        ("bridge CSR base", csr_bridge.get("csr_base_hps_phys"), 0xFF200000),
        ("bridge lightweight aperture span", csr_bridge.get("hps_lw_span_bytes"), 2 * 1024 * 1024),
        ("bridge CSR span", csr_bridge.get("csr_span_bytes"), 4096),
        ("bridge writer width", ddr_bridge.get("data_width_bits"), 64),
        ("runtime CSR base", runtime.get("csr_base_phys"), 0xFF200000),
        ("runtime CSR span", runtime.get("csr_span_bytes"), 4096),
        ("runtime HPS ring base", runtime.get("ring_base_hps_phys"), 0x3E000000),
        ("runtime FPGA ring base", runtime.get("ring_base_fpga"), 0x3E000000),
        ("runtime ring size", runtime.get("ring_size_bytes"), 32 * 1024 * 1024),
    ]
    for label, actual_raw, expected in checks:
        try:
            actual = parse_int(actual_raw)
        except (TypeError, ValueError) as exc:
            errors.append(f"{label} is invalid: {exc}")
        else:
            require_equal(errors, label, actual, expected)

    require_equal(
        errors,
        "bridge CSR full-decode requirement",
        csr_bridge.get("full_decode_required"),
        True,
    )
    require_equal(
        errors,
        "bridge unused lightweight aperture policy",
        csr_bridge.get("unused_aperture_policy"),
        "unmapped_decode_error_no_csr_aliasing",
    )

    try:
        markdown = (root / ADDRESS_MD_REL).read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read {ADDRESS_MD_REL}: {exc}")
        return
    for phrase in [
        "Step 2 source freeze",
        "Step 4 address-map source freeze",
        "unverified_requires_board_label_confirmation",
        "system.sopcinfo",
        "source-frozen",
        "hps_0.h2f_lw_axi_master",
        "hps_0.f2h_sdram0_data",
        "hps_0.h2f_reset",
    ]:
        if phrase not in markdown:
            errors.append(f"address_map.md lacks required platform/address statement: {phrase}")

    try:
        sopcinfo_policy = (root / SOPCINFO_LOCATION_REL).read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read {SOPCINFO_LOCATION_REL}: {exc}")
        return
    for phrase in [
        "platform/de1soc/qsys/system.sopcinfo",
        "source freeze",
        "hardware evidence",
        "--require-sopcinfo",
        "cumulative architecture source",
    ]:
        if phrase not in sopcinfo_policy:
            errors.append(f"sopcinfo_location.md lacks required policy statement: {phrase}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    errors: list[str] = []

    check_preset(root, errors)
    cfg = check_cfg(root, errors)
    check_platform_designer(root, errors)
    check_qsys_blueprint(root, errors)
    check_working_qsys_state(root, errors)
    check_address_parity(root, cfg, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"check_hps_platform: FAIL ({len(errors)} errors)", file=sys.stderr)
        return 1
    if not args.quiet:
        print(
            "check_hps_platform: OK "
            f"({EXPECTED_PARAMETER_COUNT} frozen HPS parameters; {EXPECTED_EFFECTIVE_HASH})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
