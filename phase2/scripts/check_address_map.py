#!/usr/bin/env python3
"""Validate the Step-4 DE1-SoC source-only address-map freeze.

This gate proves that the reviewed source assignments are complete, internally
legal, cross-file consistent, and protected by a semantic SHA-256 freeze.  It
does not claim that Intel Platform Designer accepted the assignments, Linux
reserved the DDR interval, or the board on the desk matches the Rev-H preset.

Use ``--require-hardware-evidence`` only in an environment containing a real
Quartus-produced SOPCINFO and normalized ``system.qsys``.  Even that option is
an evidence-presence/identity gate, not Linux, board, or functional signoff.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
import xml.etree.ElementTree as ET

try:
    import jsonschema  # type: ignore[import-not-found]
except ImportError:  # The deterministic manual gate below has no third-party dependency.
    jsonschema = None

from address_map_contract import (
    ADDRESS_MAP_REL,
    BLUEPRINT_REL,
    CANONICALIZATION,
    FREEZE_REVISION,
    FREEZE_SCOPE,
    AddressMapContractError,
    build_freeze_record,
    load_json,
)


CSR_MAP_REL = Path("spec/generated/csr_map.json")
PACKET_MAP_REL = Path("spec/generated/packet_layouts.json")
RUNTIME_REL = Path("sw/hps/config/trecap_hps_config.json")
HPS_CONFIG_TCL_REL = Path("platform/de1soc/qsys/hps_config.tcl")
QSYS_REL = Path("platform/de1soc/qsys/system.qsys")
C_HEADER_REL = Path("sw/hps/include/generated/trecap_csr.h")
SV_HEADER_REL = Path("rtl/include/generated/trecap_csr_pkg.sv")
HPS_DEFAULTS_REL = Path("sw/hps/src/config.c")
DASHBOARD_REL = Path("sw/pc_dashboard/configs/dashboard_direct_link.json")
SCHEMA_REL = Path("spec/schemas/hps_bridge_regions.schema.json")
CSR_BANK_RTL_REL = Path("rtl/hps_bridge/trecap_csr_bank.sv")
HPS_BRIDGE_RTL_REL = Path("rtl/hps_bridge/trecap_hps_bridge_top.sv")

EXPECTED_SCHEMA = "trecap_phase2_de1soc_hps_bridge_regions_v2"
EXPECTED_STAGE = "step4_address_map_source_frozen"
EXPECTED_STATUS = "source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff"

EXPECTED_EXPORTS = {
    "fabric_clock": "clk_50",
    "fabric_reset": "reset_n",
    "h2f_lw_master": "trecap_csr_lw_master",
    "f2h_sdram0": "trecap_f2h_sdram0",
    "h2f_reset": "h2f_reset",
    "h2f_reset_direction": "source",
    "h2f_reset_serialized_direction": "start",
    "hps_io": "hps_io",
    "hps_memory": "memory",
}
EXPECTED_INTERNAL_INTERFACES = {
    "fabric_clock_input": "clk_0.clk_in",
    "fabric_clock_internal": "clk_0.clk",
    "fabric_reset_input": "clk_0.clk_in_reset",
    "h2f_lw_master": "trecap_csr_bridge.m0",
    "h2f_lw_master_raw": "hps_0.h2f_lw_axi_master",
    "f2h_sdram0": "trecap_f2h_sdram_bridge.s0",
    "f2h_sdram0_raw": "hps_0.f2h_sdram0_data",
    "h2f_reset": "hps_0.h2f_reset",
    "hps_io": "hps_0.hps_io",
    "hps_memory": "hps_0.memory",
}
EXPECTED_CLOCK_CONNECTIONS = {
    ("clk_0.clk", "hps_0.f2h_sdram0_clock"),
    ("clk_0.clk", "hps_0.h2f_axi_clock"),
    ("clk_0.clk", "hps_0.f2h_axi_clock"),
    ("clk_0.clk", "hps_0.h2f_lw_axi_clock"),
}

EXPECTED_CSR_BASE = 0xFF20_0000
EXPECTED_LW_SPAN = 0x0020_0000
EXPECTED_CSR_SPAN = 0x0000_1000
EXPECTED_RING_BASE = 0x3E00_0000
EXPECTED_RING_SIZE = 0x0200_0000
EXPECTED_RING_END = 0x4000_0000
EXPECTED_RING_GUARD = 64
EXPECTED_RING_ALIGNMENT = 64
EXPECTED_RING_MINIMUM = 0x0010_0000


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def require_equal(
    errors: list[str], label: str, actual: object, expected: object
) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, got {actual!r}")


def require_mapping(
    errors: list[str], value: object, label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        errors.append(f"{label} must be an object")
        return {}
    return value


def parse_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().replace("_", "")
        if not text:
            raise ValueError("empty integer string")
        return int(text, 0)
    raise ValueError(f"unsupported integer value {value!r}")


def checked_int(errors: list[str], label: str, value: object) -> int | None:
    try:
        result = parse_int(value)
    except (TypeError, ValueError) as exc:
        errors.append(f"{label}: invalid integer: {exc}")
        return None
    if result < 0 or result > 0xFFFF_FFFF_FFFF_FFFF:
        errors.append(f"{label}: integer is outside unsigned 64-bit range: {result}")
        return None
    return result


def read_text(root: Path, rel: Path, errors: list[str]) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read {rel}: {exc}")
        return ""


def safe_load_json(root: Path, rel: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return load_json(root / rel)
    except AddressMapContractError as exc:
        errors.append(str(exc))
        return {}


def parse_tcl_cfg(text: str, errors: list[str]) -> dict[str, str]:
    match = re.search(r"array\s+set\s+cfg\s+\{(?P<body>.*?)\n\s*\}", text, re.DOTALL)
    if match is None:
        errors.append(f"cannot locate cfg array in {HPS_CONFIG_TCL_REL}")
        return {}
    values: dict[str, str] = {}
    for line_number, raw in enumerate(match.group("body").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            errors.append(
                f"{HPS_CONFIG_TCL_REL}:cfg-line-{line_number}: expected key/value"
            )
            continue
        key, value = parts
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1]
        values[key] = value
    return values


def region_by_name(
    address_map: Mapping[str, Any], name: str, errors: list[str]
) -> Mapping[str, Any]:
    raw = address_map.get("regions")
    if not isinstance(raw, list):
        errors.append("regions must be an array")
        return {}
    found: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        row = require_mapping(errors, item, f"regions[{index}]")
        row_name = row.get("name")
        if not isinstance(row_name, str) or not row_name:
            errors.append(f"regions[{index}].name must be a non-empty string")
            continue
        if row_name in seen:
            errors.append(f"duplicate address-map region name: {row_name}")
        seen.add(row_name)
        if row_name == name:
            found.append(row)
    if len(found) != 1:
        errors.append(f"expected exactly one region named {name}; found {len(found)}")
        return {}
    return found[0]


def check_freeze(
    root: Path, address_map: Mapping[str, Any], errors: list[str]
) -> None:
    require_equal(errors, "address-map schema", address_map.get("schema"), EXPECTED_SCHEMA)
    require_equal(errors, "address-map project", address_map.get("project"), "T_RECAP_Phase2")
    require_equal(errors, "address-map board", address_map.get("board"), "de1soc")
    require_equal(errors, "address-map contract_stage", address_map.get("contract_stage"), EXPECTED_STAGE)
    require_equal(errors, "address-map status", address_map.get("status"), EXPECTED_STATUS)

    actual = require_mapping(errors, address_map.get("address_map_freeze"), "address_map_freeze")
    try:
        expected = build_freeze_record(root, address_map)
    except AddressMapContractError as exc:
        errors.append(f"cannot compute address-map freeze: {exc}")
        return
    require_equal(errors, "address-map freeze record", dict(actual), expected)
    require_equal(errors, "freeze revision", actual.get("revision"), FREEZE_REVISION)
    require_equal(errors, "freeze scope", actual.get("scope"), FREEZE_SCOPE)
    require_equal(errors, "freeze hardware_signoff", actual.get("hardware_signoff"), False)
    require_equal(
        errors, "freeze canonicalization", actual.get("canonicalization"), CANONICALIZATION
    )


def check_json_schema(
    root: Path, address_map: Mapping[str, Any], errors: list[str]
) -> None:
    schema = safe_load_json(root, SCHEMA_REL, errors)
    if not schema:
        return
    require_equal(
        errors,
        "address-map JSON Schema dialect",
        schema.get("$schema"),
        "https://json-schema.org/draft/2020-12/schema",
    )
    schema_const = (
        schema.get("properties", {}).get("schema", {}).get("const")
        if isinstance(schema.get("properties"), Mapping)
        else None
    )
    require_equal(errors, "address-map JSON Schema identity", schema_const, EXPECTED_SCHEMA)
    if jsonschema is not None:
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(address_map)
        except Exception as exc:
            errors.append(f"address map does not validate against {SCHEMA_REL}: {exc}")


def check_platform_identity(
    address_map: Mapping[str, Any], errors: list[str]
) -> None:
    source_spec = require_mapping(errors, address_map.get("source_spec"), "source_spec")
    for key, expected in (
        ("active_pdf_repository_target", "docs/specs/t_recap_phase2_integrated_spec.pdf"),
        ("active_pdf_original_name", "doneeeeeeeeee.pdf"),
        ("active_pdf_status", "external_upload_verified_not_bundled_in_source_snapshot"),
        (
            "active_pdf_sha256",
            "7de45d2764bacc090d2837501382c82a7f081884b7c929b8b4aa4b536bff2aaf",
        ),
    ):
        require_equal(errors, f"source_spec.{key}", source_spec.get(key), expected)

    related = require_mapping(errors, address_map.get("related_files"), "related_files")
    for key, expected in (
        ("human_document", "platform/de1soc/address_map/address_map.md"),
        ("sopcinfo_location_document", "platform/de1soc/address_map/sopcinfo_location.md"),
        ("address_map_checker", "scripts/check_address_map.py"),
        ("address_map_freeze_helper", "scripts/freeze_address_map.py"),
        ("platform_config_tcl", HPS_CONFIG_TCL_REL.as_posix()),
        ("sopcinfo_target", "platform/de1soc/qsys/system.sopcinfo"),
        ("hps_runtime_config", RUNTIME_REL.as_posix()),
        ("csr_contract", CSR_MAP_REL.as_posix()),
        ("packet_contract", PACKET_MAP_REL.as_posix()),
    ):
        require_equal(errors, f"related_files.{key}", related.get(key), expected)

    board = require_mapping(errors, address_map.get("board_profile"), "board_profile")
    require_equal(
        errors,
        "board preset",
        board.get("preset"),
        "terasic_de1soc_revh_qp20_1_trecap_f2sdram64",
    )
    require_equal(errors, "board source revision", board.get("source_revision"), "H")
    require_equal(
        errors,
        "physical board evidence status",
        board.get("physical_board_revision_status"),
        "unverified_requires_board_label_confirmation",
    )

    pd = require_mapping(errors, address_map.get("platform_designer"), "platform_designer")
    for label, key, expected in (
        ("Platform Designer system name", "system_name", "system"),
        (
            "Platform Designer contract status",
            "contract_status",
            "source_implemented_pending_quartus_normalization_generation_compile",
        ),
        ("address contract status", "address_contract_status", "source_frozen_hardware_evidence_pending"),
        ("Quartus release", "quartus_release", "20.1"),
        ("Qsys API version", "qsys_api_version", "16.0"),
        ("HPS component version", "hps_component_version", "20.1"),
        ("F2SDRAM type", "f2sdram_type", "Avalon-MM Bidirectional"),
        ("F2SDRAM width", "f2sdram_width_bits", 64),
        ("SOPCINFO path", "sopcinfo_file", "platform/de1soc/qsys/system.sopcinfo"),
        ("SOPCINFO source-package policy", "sopcinfo_source_package_policy", "excluded_generated_hardware_evidence"),
    ):
        require_equal(errors, label, pd.get(key), expected)

    exports = require_mapping(errors, address_map.get("exports"), "exports")
    require_equal(errors, "address-map exports", dict(exports), EXPECTED_EXPORTS)
    internal = require_mapping(
        errors, address_map.get("internal_interfaces"), "internal_interfaces"
    )
    require_equal(
        errors, "address-map internal interfaces", dict(internal), EXPECTED_INTERNAL_INTERFACES
    )
    connections: set[tuple[object, object]] = set()
    raw_connections = address_map.get("required_clock_connections")
    if not isinstance(raw_connections, list):
        errors.append("required_clock_connections must be an array")
    else:
        for index, raw in enumerate(raw_connections):
            row = require_mapping(errors, raw, f"required_clock_connections[{index}]")
            connections.add((row.get("source"), row.get("sink")))
    require_equal(errors, "required HPS bridge clocks", connections, EXPECTED_CLOCK_CONNECTIONS)


def check_geometry(
    address_map: Mapping[str, Any], errors: list[str]
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    bridges = require_mapping(errors, address_map.get("bridges"), "bridges")
    csr_bridge = require_mapping(errors, bridges.get("csr_bridge"), "bridges.csr_bridge")
    ddr_bridge = require_mapping(
        errors, bridges.get("ddr_writer_bridge"), "bridges.ddr_writer_bridge"
    )
    csr_region = region_by_name(address_map, "trecap_csr_window", errors)
    ring_region = region_by_name(address_map, "telemetry_ddr_ring", errors)

    values: dict[str, int | None] = {}
    for key, source in {
        "lw_base": csr_bridge.get("hps_lw_base_phys"),
        "lw_span": csr_bridge.get("hps_lw_span_bytes"),
        "csr_offset": csr_bridge.get("csr_offset_in_lw"),
        "csr_base": csr_bridge.get("csr_base_hps_phys"),
        "csr_span": csr_bridge.get("csr_span_bytes"),
        "csr_region_base": csr_region.get("hps_physical_base"),
        "csr_region_span": csr_region.get("span_bytes"),
        "csr_region_end": csr_region.get("end_exclusive"),
        "ring_hps_base": ring_region.get("hps_physical_base"),
        "ring_fpga_base": ring_region.get("fpga_visible_base"),
        "ring_size": ring_region.get("size_bytes"),
        "ring_end": ring_region.get("end_exclusive"),
        "ring_guard": ring_region.get("guard_bytes"),
        "ring_alignment": ring_region.get("alignment_bytes"),
        "ring_natural_alignment": ring_region.get("natural_alignment_bytes"),
        "ring_minimum": ring_region.get("minimum_size_bytes"),
    }.items():
        values[key] = checked_int(errors, key, source)

    expected_values = {
        "lw_base": EXPECTED_CSR_BASE,
        "lw_span": EXPECTED_LW_SPAN,
        "csr_offset": 0,
        "csr_base": EXPECTED_CSR_BASE,
        "csr_span": EXPECTED_CSR_SPAN,
        "csr_region_base": EXPECTED_CSR_BASE,
        "csr_region_span": EXPECTED_CSR_SPAN,
        "csr_region_end": EXPECTED_CSR_BASE + EXPECTED_CSR_SPAN,
        "ring_hps_base": EXPECTED_RING_BASE,
        "ring_fpga_base": EXPECTED_RING_BASE,
        "ring_size": EXPECTED_RING_SIZE,
        "ring_end": EXPECTED_RING_END,
        "ring_guard": EXPECTED_RING_GUARD,
        "ring_alignment": EXPECTED_RING_ALIGNMENT,
        "ring_natural_alignment": EXPECTED_RING_SIZE,
        "ring_minimum": EXPECTED_RING_MINIMUM,
    }
    for key, expected in expected_values.items():
        require_equal(errors, key, values.get(key), expected)

    lw_base = values["lw_base"]
    lw_span = values["lw_span"]
    csr_offset = values["csr_offset"]
    csr_base = values["csr_base"]
    csr_span = values["csr_span"]
    if None not in (lw_base, lw_span, csr_offset, csr_base, csr_span):
        assert lw_base is not None and lw_span is not None
        assert csr_offset is not None and csr_base is not None and csr_span is not None
        require_equal(
            errors,
            "CSR HPS translation",
            csr_base,
            lw_base + csr_offset,
        )
        if csr_offset + csr_span > lw_span:
            errors.append("CSR window escapes the HPS lightweight bridge span")

    require_equal(errors, "CSR bridge export", csr_bridge.get("export"), "trecap_csr_lw_master")
    require_equal(
        errors,
        "CSR typed bridge instance",
        csr_bridge.get("platform_designer_bridge_instance"),
        "trecap_csr_bridge",
    )
    require_equal(
        errors,
        "CSR raw HPS interface",
        csr_bridge.get("raw_hps_interface"),
        "hps_0.h2f_lw_axi_master",
    )
    require_equal(
        errors,
        "CSR export internal",
        csr_bridge.get("export_internal"),
        "trecap_csr_bridge.m0",
    )
    require_equal(
        errors,
        "CSR Qsys protocol adaptation",
        csr_bridge.get("qsys_protocol_adaptation"),
        "axi3_to_avalon_mm",
    )
    require_equal(errors, "CSR bridge data width", csr_bridge.get("data_width_bits"), 32)
    require_equal(
        errors,
        "HPS lightweight master byte-address width",
        csr_bridge.get("master_byte_address_width_bits"),
        21,
    )
    require_equal(
        errors,
        "CSR leaf byte-address width",
        csr_bridge.get("csr_leaf_byte_address_width_bits"),
        12,
    )
    if "address_width_bits" in csr_bridge:
        errors.append(
            "bridges.csr_bridge.address_width_bits is ambiguous; use the explicit master/leaf byte-address widths"
        )
    require_equal(errors, "CSR bridge byte order", csr_bridge.get("byte_order"), "little_endian")
    require_equal(errors, "CSR bridge alignment", csr_bridge.get("access_alignment_bytes"), 4)
    require_equal(errors, "CSR full-decode policy", csr_bridge.get("full_decode_required"), True)
    require_equal(
        errors,
        "unused lightweight aperture policy",
        csr_bridge.get("unused_aperture_policy"),
        "unmapped_decode_error_no_csr_aliasing",
    )
    csr_translation = require_mapping(
        errors, csr_bridge.get("address_translation"), "csr_bridge.address_translation"
    )
    require_equal(
        errors,
        "CSR translation policy",
        csr_translation.get("policy"),
        "hps_lw_window_plus_offset",
    )
    require_equal(
        errors,
        "CSR translation formula",
        csr_translation.get("formula"),
        "csr_base_hps_phys = hps_lw_base_phys + csr_offset_in_lw",
    )
    require_equal(errors, "CSR translation offset", csr_translation.get("offset_bytes"), 0)
    master_address_width = checked_int(
        errors,
        "HPS lightweight master byte-address width",
        csr_bridge.get("master_byte_address_width_bits"),
    )
    leaf_address_width = checked_int(
        errors,
        "CSR leaf byte-address width",
        csr_bridge.get("csr_leaf_byte_address_width_bits"),
    )
    if lw_span is not None and master_address_width is not None and master_address_width < 64:
        require_equal(
            errors,
            "lightweight master byte-address-width coverage",
            1 << master_address_width,
            lw_span,
        )
    if csr_span is not None and leaf_address_width is not None and leaf_address_width < 64:
        require_equal(
            errors,
            "CSR leaf byte-address-width coverage",
            1 << leaf_address_width,
            csr_span,
        )

    require_equal(errors, "DDR bridge export", ddr_bridge.get("export"), "trecap_f2h_sdram0")
    require_equal(
        errors,
        "DDR typed bridge instance",
        ddr_bridge.get("platform_designer_bridge_instance"),
        "trecap_f2h_sdram_bridge",
    )
    require_equal(
        errors,
        "DDR raw HPS interface",
        ddr_bridge.get("raw_hps_interface"),
        "hps_0.f2h_sdram0_data",
    )
    require_equal(
        errors,
        "DDR export internal",
        ddr_bridge.get("export_internal"),
        "trecap_f2h_sdram_bridge.s0",
    )
    require_equal(errors, "DDR wrapper address width", ddr_bridge.get("wrapper_byte_address_width_bits"), 32)
    require_equal(errors, "DDR repository address width", ddr_bridge.get("repository_address_width_bits"), 64)
    require_equal(
        errors,
        "DDR out-of-range policy",
        ddr_bridge.get("out_of_range_policy"),
        "registered_one_cycle_slave_error_no_platform_designer_write",
    )
    require_equal(errors, "DDR bridge data width", ddr_bridge.get("data_width_bits"), 64)
    require_equal(errors, "DDR byte-enable width", ddr_bridge.get("byteenable_width_bits"), 8)
    require_equal(errors, "DDR burstcount width", ddr_bridge.get("burstcount_width_bits"), 1)
    require_equal(
        errors,
        "DDR burst policy",
        ddr_bridge.get("current_burst_policy"),
        "single_beat_baseline_burstcount_1",
    )
    wait_policy = ddr_bridge.get("waitrequest_policy")
    if not isinstance(wait_policy, str) or not all(
        token in wait_policy for token in ("address", "data", "byteenable", "write", "waitrequest")
    ):
        errors.append("DDR waitrequest policy must freeze address/data/byteenable/write stability")
    require_equal(
        errors,
        "DDR write-response policy",
        ddr_bridge.get("write_response_policy"),
        "generated_hps_f2sdram_has_no_write_response_legal_writes_idle_okay_"
        "wrapper_out_of_range_registered_one_cycle_slave_error_producer_commit_blocked",
    )

    translation = require_mapping(
        errors, ring_region.get("address_translation"), "telemetry_ddr_ring.address_translation"
    )
    require_equal(errors, "ring translation policy", translation.get("policy"), "identity")
    require_equal(
        errors,
        "ring FPGA-to-HPS translation offset",
        translation.get("fpga_to_hps_offset_bytes"),
        0,
    )
    require_equal(
        errors,
        "ring boot remap requirement",
        translation.get("required_boot_remap"),
        "non_mpu_address_zero_maps_to_sdram",
    )
    require_equal(
        errors,
        "ring translation evidence status",
        translation.get("evidence_status"),
        "pending_hardware_confirmation",
    )

    ring_hps = values["ring_hps_base"]
    ring_fpga = values["ring_fpga_base"]
    ring_size = values["ring_size"]
    ring_end = values["ring_end"]
    ring_guard = values["ring_guard"]
    ring_align = values["ring_alignment"]
    if None not in (ring_hps, ring_fpga, ring_size, ring_end, ring_guard, ring_align):
        assert ring_hps is not None and ring_fpga is not None
        assert ring_size is not None and ring_end is not None
        assert ring_guard is not None and ring_align is not None
        require_equal(errors, "ring identity translation", ring_fpga, ring_hps)
        require_equal(errors, "ring end-exclusive arithmetic", ring_end, ring_hps + ring_size)
        if ring_size == 0 or ring_size & (ring_size - 1):
            errors.append("ring size must be a nonzero power of two")
        if ring_hps % ring_align or ring_fpga % ring_align or ring_size % ring_align:
            errors.append("ring bases and size must satisfy the frozen ring alignment")
        if ring_hps % ring_size:
            errors.append("ring base must be naturally aligned to the frozen ring size")
        if ring_guard < ring_align or ring_guard >= ring_size or ring_guard % ring_align:
            errors.append("ring guard must be aligned, at least one record, and smaller than the ring")
        if csr_base is not None and csr_span is not None:
            csr_end = csr_base + csr_span
            if not (ring_end <= csr_base or csr_end <= ring_hps):
                errors.append("CSR and DDR ring HPS physical intervals overlap")

    require_equal(errors, "ring power-of-two policy", ring_region.get("power_of_two_size_required"), True)
    require_equal(errors, "ring allocation policy", ring_region.get("linux_allocation_policy"), "reserved_ddr_or_dma_coherent")
    require_equal(errors, "ring cache policy", ring_region.get("hps_cache_policy"), "non_cacheable_or_explicit_invalidate")
    return csr_region, ring_region


def check_csr_contract(
    root: Path,
    csr_region: Mapping[str, Any],
    ring_region: Mapping[str, Any],
    errors: list[str],
) -> None:
    csr = safe_load_json(root, CSR_MAP_REL, errors)
    bus = require_mapping(errors, csr.get("bus_contract"), "csr_map.bus_contract")
    constants = require_mapping(errors, csr.get("constants"), "csr_map.constants")
    require_equal(errors, "CSR bus endianness", bus.get("endianness"), "little")
    require_equal(errors, "CSR word bits", bus.get("word_bits"), 32)
    require_equal(errors, "CSR word alignment", bus.get("word_alignment_bytes"), 4)
    require_equal(errors, "CSR recommended span", bus.get("csr_window_span_recommended_bytes"), EXPECTED_CSR_SPAN)

    registers = csr.get("registers")
    if not isinstance(registers, list) or not registers:
        errors.append("csr_map.registers must be a non-empty array")
        return
    offsets: dict[str, int] = {}
    occupied: set[int] = set()
    for index, raw in enumerate(registers):
        reg = require_mapping(errors, raw, f"csr_map.registers[{index}]")
        name = reg.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"csr_map.registers[{index}].name must be non-empty")
            continue
        offset = checked_int(errors, f"CSR {name} offset", reg.get("offset"))
        offset_hex = checked_int(errors, f"CSR {name} offset_hex", reg.get("offset_hex"))
        if offset is None:
            continue
        require_equal(errors, f"CSR {name} offset/offset_hex", offset_hex, offset)
        if offset % 4:
            errors.append(f"CSR {name} offset 0x{offset:x} is not 4-byte aligned")
        if offset in occupied:
            errors.append(f"duplicate CSR byte offset 0x{offset:x}")
        occupied.add(offset)
        offsets[name] = offset
        require_equal(errors, f"CSR {name} width", reg.get("width_bits"), 32)

    span = checked_int(errors, "CSR region span", csr_region.get("span_bytes"))
    if span is not None and offsets and max(offsets.values()) + 4 > span:
        errors.append("frozen CSR region does not cover the last generated CSR word")
    for required in (
        "ID",
        "VERSION",
        "RING_BASE_LO",
        "RING_BASE_HI",
        "RING_SIZE_BYTES",
        "RING_CONFIG_COMMIT",
        "RING_RD_LO_SHADOW",
        "RING_RD_HI_SHADOW",
        "RING_RD_COMMIT",
    ):
        if required not in offsets:
            errors.append(f"CSR map is missing required address-map register {required}")

    identity = require_mapping(errors, constants.get("ID"), "csr_map.constants.ID")
    version = require_mapping(errors, constants.get("VERSION"), "csr_map.constants.VERSION")
    required_id = checked_int(errors, "address-map required ID", csr_region.get("required_id_value"))
    required_version = checked_int(
        errors, "address-map required VERSION", csr_region.get("required_version_value")
    )
    identity_value = checked_int(errors, "CSR contract ID", identity.get("value_hex"))
    require_equal(errors, "CSR ID parity", required_id, identity_value)
    version_major = checked_int(errors, "CSR VERSION major", version.get("major"))
    version_minor = checked_int(errors, "CSR VERSION minor", version.get("minor"))
    packed_field = checked_int(errors, "CSR VERSION packed field", version.get("packed_hex"))
    if version_major is not None and version_minor is not None:
        packed_version = (version_major << 16) | version_minor
        require_equal(errors, "CSR VERSION parity", required_version, packed_version)
        require_equal(errors, "CSR VERSION packed field parity", packed_field, packed_version)

    require_equal(
        errors,
        "ring minimum parity",
        ring_region.get("minimum_size_bytes"),
        constants.get("RING_SIZE_MIN_BYTES"),
    )
    require_equal(
        errors,
        "ring alignment parity",
        ring_region.get("alignment_bytes"),
        constants.get("RING_ALIGNMENT_BYTES"),
    )
    require_equal(
        errors,
        "ring guard parity",
        ring_region.get("guard_bytes"),
        constants.get("RING_GUARD_BYTES_MIN"),
    )

    c_header = read_text(root, C_HEADER_REL, errors)
    sv_header = read_text(root, SV_HEADER_REL, errors)
    c_offsets = {
        name: int(value, 16)
        for name, value in re.findall(
            r"#define\s+TCSR_([A-Z0-9_]+)_OFFSET\s+UINT32_C\(0x([0-9a-fA-F]+)\)",
            c_header,
        )
    }
    sv_offsets = {
        name: int(value, 16)
        for name, value in re.findall(
            r"TCSR_([A-Z0-9_]+)_OFFSET\s*=\s*32'h([0-9a-fA-F]+)", sv_header
        )
    }
    require_equal(errors, "generated C CSR offsets", c_offsets, offsets)
    require_equal(errors, "generated SV CSR offsets", sv_offsets, offsets)


def check_packet_ring_contract(
    root: Path, ring_region: Mapping[str, Any], errors: list[str]
) -> None:
    packet = safe_load_json(root, PACKET_MAP_REL, errors)
    transport = require_mapping(errors, packet.get("transport"), "packet_layouts.transport")
    record = require_mapping(errors, ring_region.get("record_contract"), "ring record_contract")
    require_equal(errors, "DDR record header bytes", record.get("header_bytes"), transport.get("telemetry_header_bytes"))
    require_equal(errors, "DDR record alignment", record.get("normal_record_alignment_bytes"), transport.get("ddr_record_alignment_bytes"))
    require_equal(errors, "DDR padding UDP policy", record.get("udp_forwards_padding"), transport.get("send_ddr_padding_over_udp"))
    wrap_codes = []
    raw_types = packet.get("packet_types")
    if isinstance(raw_types, list):
        for raw in raw_types:
            if isinstance(raw, Mapping) and raw.get("name") == "WRAP":
                code = checked_int(errors, "WRAP packet type", raw.get("code"))
                if code is not None:
                    wrap_codes.append(code)
    if len(wrap_codes) != 1:
        errors.append(f"packet contract must contain exactly one WRAP type; found {len(wrap_codes)}")
    else:
        wrap_record = checked_int(
            errors, "ring WRAP packet type", record.get("wrap_packet_type")
        )
        require_equal(errors, "WRAP packet-type parity", wrap_record, wrap_codes[0])


def check_runtime_parity(
    root: Path,
    address_map: Mapping[str, Any],
    csr_region: Mapping[str, Any],
    ring_region: Mapping[str, Any],
    errors: list[str],
) -> None:
    runtime = safe_load_json(root, RUNTIME_REL, errors)
    network = require_mapping(errors, address_map.get("runtime_network"), "runtime_network")
    require_equal(
        errors,
        "runtime address-contract path",
        runtime.get("address_contract"),
        ADDRESS_MAP_REL.as_posix(),
    )
    require_equal(
        errors,
        "runtime address-contract stage",
        runtime.get("address_contract_stage"),
        EXPECTED_STAGE,
    )
    comparisons = {
        "csr_base_phys": (runtime.get("csr_base_phys"), csr_region.get("hps_physical_base")),
        "csr_span_bytes": (runtime.get("csr_span_bytes"), csr_region.get("span_bytes")),
        "ring_base_hps_phys": (runtime.get("ring_base_hps_phys"), ring_region.get("hps_physical_base")),
        "ring_base_fpga": (runtime.get("ring_base_fpga"), ring_region.get("fpga_visible_base")),
        "ring_size_bytes": (runtime.get("ring_size_bytes"), ring_region.get("size_bytes")),
        "ring_guard_bytes": (runtime.get("ring_guard_bytes"), ring_region.get("guard_bytes")),
        "telemetry_dst_port": (runtime.get("telemetry_dst_port"), network.get("telemetry_dst_port")),
        "command_listen_port": (runtime.get("command_listen_port"), network.get("command_listen_port")),
        "transport_version_major": (runtime.get("transport_version_major"), network.get("transport_version_major")),
        "transport_version_minor": (runtime.get("transport_version_minor"), network.get("transport_version_minor")),
    }
    for label, (left_raw, right_raw) in comparisons.items():
        left = checked_int(errors, f"runtime {label}", left_raw)
        right = checked_int(errors, f"address-map {label}", right_raw)
        require_equal(errors, f"runtime/address-map {label}", left, right)
    for runtime_key, map_key in (
        ("telemetry_dst_ip", "pc_direct_ip"),
        ("hps_static_ip", "hps_direct_ip"),
        ("netmask", "netmask"),
        ("trusted_command_peer", "trusted_command_peer"),
    ):
        require_equal(
            errors,
            f"runtime/address-map {runtime_key}",
            runtime.get(runtime_key),
            network.get(map_key),
        )

    tcl = parse_tcl_cfg(read_text(root, HPS_CONFIG_TCL_REL, errors), errors)
    tcl_comparisons = {
        "h2f_lw_base_hps_phys": ("h2f_lw_base_hps_phys", EXPECTED_CSR_BASE),
        "h2f_lw_span_bytes": ("h2f_lw_span_bytes", EXPECTED_LW_SPAN),
        "csr_offset_in_lw": ("csr_offset_in_lw", 0),
        "csr_base_hps_phys": ("csr_base_hps_phys", EXPECTED_CSR_BASE),
        "csr_span_bytes": ("csr_span_bytes", EXPECTED_CSR_SPAN),
        "csr_data_width": ("csr_data_width", 32),
        "h2f_lw_master_byte_addr_width": ("h2f_lw_master_byte_addr_width", 21),
        "csr_leaf_byte_addr_width": ("csr_leaf_byte_addr_width", 12),
        "ring_base_hps_phys": ("ring_base_hps_phys", EXPECTED_RING_BASE),
        "ring_base_fpga": ("ring_base_fpga", EXPECTED_RING_BASE),
        "ring_size_bytes": ("ring_size_bytes", EXPECTED_RING_SIZE),
        "ring_guard_bytes": ("ring_guard_bytes", EXPECTED_RING_GUARD),
        "ddr_writer_data_width": ("ddr_writer_data_width", 64),
        "ddr_writer_byteenable_width": ("ddr_writer_byteenable_width", 8),
        "ddr_writer_burstcount_width": ("ddr_writer_burstcount_width", 1),
    }
    for label, (key, expected) in tcl_comparisons.items():
        actual = checked_int(errors, f"Tcl cfg {key}", tcl.get(key))
        require_equal(errors, f"Tcl/address-map {label}", actual, expected)
    for key, expected in (
        ("sopcinfo_file_rel", "platform/de1soc/qsys/system.sopcinfo"),
        ("h2f_lw_master_export", "trecap_csr_lw_master"),
        ("f2h_sdram0_export", "trecap_f2h_sdram0"),
        ("memory_mapping_policy", "reserved_ddr_or_dma_coherent"),
        ("hps_ring_cache_policy", "non_cacheable_or_explicit_invalidate"),
        ("address_map_contract_stage", EXPECTED_STAGE),
        ("address_map_contract_status", EXPECTED_STATUS),
    ):
        require_equal(errors, f"Tcl cfg {key}", tcl.get(key), expected)

    defaults = read_text(root, HPS_DEFAULTS_REL, errors)
    default_patterns = {
        "csr_base_phys": (r"cfg->csr_base_phys\s*=\s*UINT64_C\((0x[0-9a-fA-F]+)\)", EXPECTED_CSR_BASE),
        "csr_span_bytes": (r"cfg->csr_span_bytes\s*=\s*UINT32_C\((\d+)\)", EXPECTED_CSR_SPAN),
        "ring_base_hps_phys": (r"cfg->ring_base_hps_phys\s*=\s*UINT64_C\((0x[0-9a-fA-F]+)\)", EXPECTED_RING_BASE),
        "ring_base_fpga": (r"cfg->ring_base_fpga\s*=\s*UINT64_C\((0x[0-9a-fA-F]+)\)", EXPECTED_RING_BASE),
        "ring_size_bytes": (r"cfg->ring_size_bytes\s*=\s*UINT32_C\((\d+)\)", EXPECTED_RING_SIZE),
    }
    for label, (pattern, expected) in default_patterns.items():
        match = re.search(pattern, defaults)
        if match is None:
            errors.append(f"cannot find HPS software default for {label}")
        else:
            require_equal(errors, f"HPS software default {label}", parse_int(match.group(1)), expected)

    for rel in (CSR_BANK_RTL_REL, HPS_BRIDGE_RTL_REL):
        rtl = read_text(root, rel, errors)
        if re.search(r"parameter\s+int\s+unsigned\s+CSR_ADDR_W\s*=\s*12\b", rtl) is None:
            errors.append(f"{rel} must freeze CSR_ADDR_W=12 as a byte-offset leaf width")

    dashboard = safe_load_json(root, DASHBOARD_REL, errors)
    topology = require_mapping(errors, dashboard.get("default_topology"), "dashboard.default_topology")
    dashboard_network = require_mapping(errors, dashboard.get("network"), "dashboard.network")
    command = require_mapping(errors, dashboard.get("command"), "dashboard.command")
    require_equal(errors, "dashboard PC IP", topology.get("pc_static_ip"), network.get("pc_direct_ip"))
    require_equal(errors, "dashboard HPS IP", topology.get("hps_static_ip"), network.get("hps_direct_ip"))
    require_equal(errors, "dashboard netmask", topology.get("netmask"), network.get("netmask"))
    require_equal(errors, "dashboard telemetry port", dashboard_network.get("bind_port"), network.get("telemetry_dst_port"))
    require_equal(errors, "dashboard telemetry source", dashboard_network.get("expected_source"), network.get("hps_direct_ip"))
    require_equal(errors, "dashboard command host", command.get("host"), network.get("hps_direct_ip"))
    require_equal(errors, "dashboard command port", command.get("port"), network.get("command_listen_port"))


def check_blueprint(root: Path, address_map: Mapping[str, Any], errors: list[str]) -> None:
    try:
        blueprint = ET.parse(root / BLUEPRINT_REL).getroot()
    except (OSError, ET.ParseError) as exc:
        errors.append(f"cannot parse {BLUEPRINT_REL}: {exc}")
        return
    exports = {
        item.get("name"): item.get("internal")
        for instance in blueprint.findall("./planned_instances/instance")
        for item in instance.findall("./export")
    }
    metadata = {
        item.get("key"): item.get("value") for item in blueprint.findall("./metadata")
    }
    for key, expected in (
        ("contract_stage", "step6_platform_designer_typed_bridges_source_implemented"),
        (
            "contract_status",
            "source_implemented_pending_quartus_normalization_generation_compile",
        ),
        ("address_contract_stage", EXPECTED_STAGE),
        ("address_contract_status", EXPECTED_STATUS),
        ("address_contract_file", ADDRESS_MAP_REL.as_posix()),
        ("sopcinfo_location_document", "platform/de1soc/address_map/sopcinfo_location.md"),
        ("address_status", "source_frozen_hardware_evidence_pending"),
    ):
        require_equal(errors, f"blueprint metadata {key}", metadata.get(key), expected)
    for key, expected in (
        ("h2f_lw_base_hps_phys", EXPECTED_CSR_BASE),
        ("h2f_lw_span_bytes", EXPECTED_LW_SPAN),
        ("csr_offset_in_lw", 0),
        ("h2f_lw_master_byte_address_width_bits", 21),
        ("csr_leaf_byte_address_width_bits", 12),
        ("csr_hps_physical_base", EXPECTED_CSR_BASE),
        ("csr_span_bytes", EXPECTED_CSR_SPAN),
        ("ring_base_hps_phys", EXPECTED_RING_BASE),
        ("ring_base_fpga_visible", EXPECTED_RING_BASE),
        ("ring_size_bytes", EXPECTED_RING_SIZE),
        ("ring_alignment_bytes", EXPECTED_RING_ALIGNMENT),
    ):
        require_equal(
            errors,
            f"blueprint metadata {key}",
            checked_int(errors, f"blueprint metadata {key}", metadata.get(key)),
            expected,
        )
    expected_export_internal = {
        EXPECTED_EXPORTS["fabric_clock"]: EXPECTED_INTERNAL_INTERFACES["fabric_clock_input"],
        EXPECTED_EXPORTS["fabric_reset"]: EXPECTED_INTERNAL_INTERFACES["fabric_reset_input"],
        EXPECTED_EXPORTS["h2f_lw_master"]: EXPECTED_INTERNAL_INTERFACES["h2f_lw_master"],
        EXPECTED_EXPORTS["f2h_sdram0"]: EXPECTED_INTERNAL_INTERFACES["f2h_sdram0"],
        EXPECTED_EXPORTS["h2f_reset"]: EXPECTED_INTERNAL_INTERFACES["h2f_reset"],
        EXPECTED_EXPORTS["hps_io"]: EXPECTED_INTERNAL_INTERFACES["hps_io"],
        EXPECTED_EXPORTS["hps_memory"]: EXPECTED_INTERNAL_INTERFACES["hps_memory"],
    }
    require_equal(errors, "blueprint export/internal map", exports, expected_export_internal)
    clocks = {
        (item.get("source"), item.get("sink"))
        for item in blueprint.findall("./planned_connections/connection")
        if item.get("role") == "hps_bridge_clock"
    }
    require_equal(errors, "blueprint HPS bridge clocks", clocks, EXPECTED_CLOCK_CONNECTIONS)
    typed_connections = {
        (item.get("source"), item.get("sink"), item.get("role"), item.get("baseAddress"))
        for item in blueprint.findall("./planned_connections/connection")
        if item.get("role") != "hps_bridge_clock"
    }
    require_equal(
        errors,
        "blueprint typed bridge graph",
        typed_connections,
        {
            ("clk_0.clk", "trecap_csr_bridge.clk", "typed_bridge_clock", None),
            ("clk_0.clk_reset", "trecap_csr_bridge.reset", "typed_bridge_reset", None),
            (
                "hps_0.h2f_lw_axi_master",
                "trecap_csr_bridge.s0",
                "csr_bridge_upstream",
                "0x00000000",
            ),
            ("clk_0.clk", "trecap_f2h_sdram_bridge.clk", "typed_bridge_clock", None),
            (
                "clk_0.clk_reset",
                "trecap_f2h_sdram_bridge.reset",
                "typed_bridge_reset",
                None,
            ),
            (
                "trecap_f2h_sdram_bridge.m0",
                "hps_0.f2h_sdram0_data",
                "f2h_sdram_bridge_downstream",
                "0x00000000",
            ),
        },
    )

    qsys_text = read_text(root, QSYS_REL, errors)
    if "T_RECAP_BOOTSTRAP_QSYS_SOURCE=1" in qsys_text:
        try:
            qsys = ET.fromstring(qsys_text)
        except ET.ParseError as exc:
            errors.append(f"cannot parse bootstrap {QSYS_REL}: {exc}")
            return
        metadata = {item.get("key"): item.get("value") for item in qsys.findall("./metadata")}
        for key, expected in (
            ("address_contract_stage", EXPECTED_STAGE),
            ("address_contract_status", EXPECTED_STATUS),
            ("address_contract_file", ADDRESS_MAP_REL.as_posix()),
            ("address_status", "source_frozen_hardware_evidence_pending"),
            ("csr_full_decode_required", "true"),
        ):
            require_equal(errors, f"bootstrap metadata {key}", metadata.get(key), expected)
        require_equal(
            errors,
            "bootstrap LW base",
            checked_int(errors, "bootstrap LW base", metadata.get("h2f_lw_base_hps_phys")),
            EXPECTED_CSR_BASE,
        )
        require_equal(
            errors,
            "bootstrap LW span",
            checked_int(errors, "bootstrap LW span", metadata.get("h2f_lw_span_bytes")),
            EXPECTED_LW_SPAN,
        )
        require_equal(
            errors,
            "bootstrap CSR offset",
            checked_int(errors, "bootstrap CSR offset", metadata.get("csr_offset_in_lw")),
            0,
        )
        require_equal(
            errors,
            "bootstrap master byte-address width",
            checked_int(
                errors,
                "bootstrap master byte-address width",
                metadata.get("h2f_lw_master_byte_address_width_bits"),
            ),
            21,
        )
        require_equal(
            errors,
            "bootstrap CSR leaf byte-address width",
            checked_int(
                errors,
                "bootstrap CSR leaf byte-address width",
                metadata.get("csr_leaf_byte_address_width_bits"),
            ),
            12,
        )
        require_equal(
            errors,
            "bootstrap CSR HPS base",
            checked_int(errors, "bootstrap CSR HPS base", metadata.get("csr_hps_physical_base")),
            EXPECTED_CSR_BASE,
        )
        require_equal(
            errors,
            "bootstrap CSR span",
            checked_int(errors, "bootstrap CSR span", metadata.get("csr_span_bytes")),
            EXPECTED_CSR_SPAN,
        )
        require_equal(
            errors,
            "bootstrap ring HPS base",
            checked_int(errors, "bootstrap ring HPS base", metadata.get("ring_base_hps_phys")),
            EXPECTED_RING_BASE,
        )
        require_equal(
            errors,
            "bootstrap ring FPGA base",
            checked_int(errors, "bootstrap ring FPGA base", metadata.get("ring_base_fpga_visible")),
            EXPECTED_RING_BASE,
        )
        require_equal(
            errors,
            "bootstrap ring size",
            checked_int(errors, "bootstrap ring size", metadata.get("ring_size_bytes")),
            EXPECTED_RING_SIZE,
        )


def check_profile_references(root: Path, errors: list[str]) -> None:
    profile_dir = root / "config/profiles"
    for path in sorted(profile_dir.glob("*.json")):
        try:
            profile = load_json(path)
        except AddressMapContractError as exc:
            errors.append(str(exc))
            continue
        transport = profile.get("transport")
        if not isinstance(transport, Mapping) or not transport.get("hps_ddr_enable"):
            continue
        rel = path.relative_to(root).as_posix()
        require_equal(errors, f"{rel} address-map reference", transport.get("address_map"), ADDRESS_MAP_REL.as_posix())
        require_equal(errors, f"{rel} HPS-runtime reference", transport.get("hps_runtime_config"), RUNTIME_REL.as_posix())


def check_hardware_evidence(
    root: Path, address_map: Mapping[str, Any], errors: list[str]
) -> None:
    pd = require_mapping(errors, address_map.get("platform_designer"), "platform_designer")
    sopc_rel_raw = pd.get("sopcinfo_file")
    if not isinstance(sopc_rel_raw, str) or not sopc_rel_raw:
        errors.append("platform_designer.sopcinfo_file must name the hardware evidence")
        return
    sopc_rel = Path(sopc_rel_raw)
    if sopc_rel.is_absolute() or ".." in sopc_rel.parts:
        errors.append("SOPCINFO evidence path must be repository-relative and non-escaping")
        return
    path = root / sopc_rel
    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append(f"hardware evidence required but {sopc_rel} cannot be read: {exc}")
        return
    if not raw:
        errors.append(f"hardware evidence required but {sopc_rel} is empty")
        return
    try:
        ET.fromstring(raw)
    except ET.ParseError as exc:
        errors.append(f"hardware evidence {sopc_rel} is not XML: {exc}")
        return
    lowered = raw.lower()
    for label, alternatives in (
        ("HPS instance", (b"hps_0",)),
        ("HPS lightweight master", (b"trecap_csr_lw_master", b"h2f_lw_axi_master")),
        ("FPGA-to-HPS SDRAM interface", (b"trecap_f2h_sdram0", b"f2h_sdram0_data")),
    ):
        if not any(token in lowered for token in alternatives):
            errors.append(f"SOPCINFO hardware evidence lacks {label} identity")
    qsys_raw = (root / QSYS_REL).read_bytes() if (root / QSYS_REL).is_file() else b""
    if b"T_RECAP_BOOTSTRAP_QSYS_SOURCE=1" in qsys_raw:
        errors.append("hardware evidence mode requires a tool-normalized system.qsys, not bootstrap")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--require-hardware-evidence",
        "--require-sopcinfo",
        dest="require_hardware_evidence",
        action="store_true",
        help="also require real SOPCINFO identity and a normalized system.qsys",
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    errors: list[str] = []
    address_map = safe_load_json(root, ADDRESS_MAP_REL, errors)
    if address_map:
        check_json_schema(root, address_map, errors)
        check_freeze(root, address_map, errors)
        check_platform_identity(address_map, errors)
        csr_region, ring_region = check_geometry(address_map, errors)
        check_csr_contract(root, csr_region, ring_region, errors)
        check_packet_ring_contract(root, ring_region, errors)
        check_runtime_parity(root, address_map, csr_region, ring_region, errors)
        check_blueprint(root, address_map, errors)
        check_profile_references(root, errors)
        if args.require_hardware_evidence:
            check_hardware_evidence(root, address_map, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"check_address_map: FAIL ({len(errors)} errors)", file=sys.stderr)
        return 1
    if not args.quiet:
        suffix = "; SOPCINFO identity present" if args.require_hardware_evidence else ""
        print(
            "check_address_map: OK "
            f"(Step-4 source freeze {EXPECTED_CSR_BASE:#x}/0x{EXPECTED_CSR_SPAN:x}, "
            f"ring {EXPECTED_RING_BASE:#x}/0x{EXPECTED_RING_SIZE:x}{suffix})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
