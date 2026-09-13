#!/usr/bin/env python3
"""Validate the source-only Step-12 DDR ring ownership contract.

This checker cross-checks the canonical physical interval, DTS reservation,
machine-readable contract/schema, and structural RTL ownership/WRAP/reset
invariants.  It deliberately does not compile a DTB or RTL, boot Linux, invoke
Quartus, access an HPS, or create hardware evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    import jsonschema  # type: ignore[import-not-found]
except ImportError:
    jsonschema = None  # type: ignore[assignment]


CONTRACT_REL = Path("config/boards/de1soc_ddr_ring_ownership.json")
SCHEMA_REL = Path("spec/schemas/de1soc_ddr_ring_ownership.schema.json")
DTSI_REL = Path("platform/de1soc/linux/trecap_reserved_memory.dtsi")
ADDRESS_MAP_REL = Path("platform/de1soc/address_map/hps_bridge_regions.json")
HPS_CONFIG_TCL_REL = Path("platform/de1soc/qsys/hps_config.tcl")
HPS_RUNTIME_REL = Path("sw/hps/config/trecap_hps_config.json")
RESERVATION_NOTE_REL = Path("sw/hps/scripts/reserve_ddr_region_notes.md")
DOC_REL = Path("docs/architecture/de1soc_ddr_ring_ownership.md")
POINTER_REL = Path("rtl/hps_bridge/trecap_ring_pointer_ctrl.sv")
BUILDER_REL = Path("rtl/hps_bridge/trecap_ddr_record_builder.sv")
WRITER_REL = Path("rtl/hps_bridge/trecap_ddr_ring_writer.sv")
AVMM_MASTER_REL = Path("rtl/hps_bridge/trecap_avmm_write_master.sv")
CSR_REL = Path("rtl/hps_bridge/trecap_csr_bank.sv")
HPS_BRIDGE_REL = Path("rtl/hps_bridge/trecap_hps_bridge_top.sv")
HPS_RING_READER_REL = Path("sw/hps/src/ring_reader.c")
HPS_STREAMER_REL = Path("sw/hps/src/trecap_udp_streamer.c")
HPS_CONFIG_SOURCE_REL = Path("sw/hps/src/config.c")
HPS_CONFIG_HEADER_REL = Path("sw/hps/include/trecap_hps_config.h")
HPS_RUNNER_REL = Path("sw/hps/scripts/run_udp_streamer.sh")

RING_BASE = 0x3E000000
RING_SIZE = 0x02000000
RING_END = 0x40000000
RING_GUARD = 64
RING_ALIGNMENT = 64

EXPECTED_TOP = {
    "schema": "trecap_phase2_de1soc_ddr_ring_ownership_v1",
    "file_class": "[1] hand-written Step-12 DDR ring ownership and Linux reservation contract",
    "project": "T_RECAP_Phase2",
    "board": "de1soc",
    "contract_stage": "step12_ddr_ring_ownership_source_implemented",
    "status": (
        "source_implemented_pending_active_dtb_integration_linux_boot_runtime_"
        "rtl_simulation_quartus_and_hardware_evidence"
    ),
}

FALSE_IMPLEMENTATION_EVIDENCE = (
    "active_board_dtb_integration",
    "compiled_active_dtb_inspection",
    "linux_boot_reservation_evidence",
    "linux_runtime_reservation_evidence",
    "rtl_compile_evidence",
    "rtl_simulation_evidence",
    "platform_designer_generation_evidence",
    "quartus_compile_evidence",
    "timing_closure_evidence",
    "hps_runtime_evidence",
    "hardware_evidence",
    "hardware_signoff",
)

TRUE_SOURCE_IMPLEMENTATION = (
    "reserved_memory_dtsi_source_implemented",
    "ownership_contract_source_implemented",
    "source_checker_implemented",
    "rtl_pointer_ownership_source_implemented",
    "rtl_wrap_boundary_source_implemented",
    "deterministic_transport_reset_source_implemented",
    "directed_rtl_testbench_source_implemented",
)


class CheckFailure(RuntimeError):
    """A checked-in Step-12 source invariant failed."""


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckFailure(f"cannot read {path}: {exc}") from exc


def load_json(path: Path) -> Any:
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise CheckFailure(f"cannot decode JSON {path}: {exc}") from exc


def parse_int(value: Any, context: str) -> int:
    if isinstance(value, bool):
        raise CheckFailure(f"{context}: boolean is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as exc:
            raise CheckFailure(f"{context}: invalid integer {value!r}") from exc
    raise CheckFailure(f"{context}: expected integer or base-prefixed string")


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CheckFailure(f"{context}: expected {expected!r}, got {actual!r}")


def require_token(text: str, token: str, context: str) -> None:
    if token not in text:
        raise CheckFailure(f"{context}: missing required token {token!r}")


def require_ordered_tokens(text: str, tokens: Iterable[str], context: str) -> None:
    cursor = 0
    for token in tokens:
        position = text.find(token, cursor)
        if position < 0:
            raise CheckFailure(
                f"{context}: missing required ordered token {token!r} after byte {cursor}"
            )
        cursor = position + len(token)


def require_regex(text: str, pattern: str, context: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if match is None:
        raise CheckFailure(f"{context}: missing required source pattern: {pattern}")
    return match


def forbid_regex(text: str, pattern: str, context: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL):
        raise CheckFailure(f"{context}: forbidden source pattern is present: {pattern}")


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\r\n]*", "", text)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def resolve_local_ref(schema_root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise CheckFailure(f"fallback schema validator does not support external $ref {ref!r}")
    value: Any = schema_root
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise CheckFailure(f"unresolved local schema reference {ref!r}")
        value = value[part]
    if not isinstance(value, dict):
        raise CheckFailure(f"schema reference {ref!r} does not resolve to an object")
    return value


def matches_json_type(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "null":
        return value is None
    raise CheckFailure(f"fallback schema validator does not support JSON type {type_name!r}")


def validate_schema_fallback(
    value: Any,
    schema: dict[str, Any],
    schema_root: dict[str, Any],
    location: str = "$",
) -> None:
    if "$ref" in schema:
        validate_schema_fallback(
            value, resolve_local_ref(schema_root, str(schema["$ref"])), schema_root, location
        )
        return
    if "const" in schema and value != schema["const"]:
        raise CheckFailure(f"{location}: value does not match schema const")
    if "enum" in schema and value not in schema["enum"]:
        raise CheckFailure(f"{location}: value is not in schema enum")
    expected_type = schema.get("type")
    if expected_type is not None and not matches_json_type(value, str(expected_type)):
        raise CheckFailure(f"{location}: expected JSON type {expected_type}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise CheckFailure(f"{location}: schema properties must be an object")
        for key in schema.get("required", []):
            if key not in value:
                raise CheckFailure(f"{location}: missing required property {key}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise CheckFailure(f"{location}: unexpected properties: {extra}")
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                validate_schema_fallback(value[key], child_schema, schema_root, f"{location}.{key}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise CheckFailure(f"{location}: too few array items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise CheckFailure(f"{location}: too many array items")
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(canonical)) != len(canonical):
                raise CheckFailure(f"{location}: array items are not unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_schema_fallback(item, item_schema, schema_root, f"{location}[{index}]")


def validate_schema_shape(schema: dict[str, Any]) -> None:
    require_equal(schema.get("$schema"), "https://json-schema.org/draft/2020-12/schema", "schema.$schema")
    require_equal(schema.get("type"), "object", "schema.type")

    def walk(node: Any, location: str) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                resolve_local_ref(schema, str(node["$ref"]))
            properties = node.get("properties")
            if properties is not None and not isinstance(properties, dict):
                raise CheckFailure(f"{location}.properties must be an object")
            if node.get("additionalProperties") is False and isinstance(properties, dict):
                missing = sorted(set(node.get("required", [])) - set(properties))
                if missing:
                    raise CheckFailure(f"{location}: required keys absent from properties: {missing}")
            for key, value in node.items():
                walk(value, f"{location}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{location}[{index}]")

    walk(schema, "$schema")


def validate_contract_schema(contract: Any, schema: Any, force_fallback: bool) -> str:
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        raise CheckFailure("contract and schema roots must be objects")
    validate_schema_shape(schema)
    if jsonschema is not None and not force_fallback:
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(contract)
        except Exception as exc:
            raise CheckFailure(f"jsonschema validation failed: {exc}") from exc
        return "jsonschema_draft_2020_12"
    validate_schema_fallback(contract, schema, schema)
    return "dependency_free_draft_2020_12_subset"


def validate_contract_values(root: Path, contract: dict[str, Any]) -> None:
    for key, expected in EXPECTED_TOP.items():
        require_equal(contract.get(key), expected, f"contract.{key}")

    implementation = contract.get("implementation_state")
    if not isinstance(implementation, dict):
        raise CheckFailure("contract.implementation_state must be an object")
    for key in TRUE_SOURCE_IMPLEMENTATION:
        require_equal(implementation.get(key), True, f"contract.implementation_state.{key}")
    for key in FALSE_IMPLEMENTATION_EVIDENCE:
        require_equal(implementation.get(key), False, f"contract.implementation_state.{key}")

    ownership = contract.get("source_ownership")
    if not isinstance(ownership, dict):
        raise CheckFailure("contract.source_ownership must be an object")
    for key, relative in ownership.items():
        if not isinstance(relative, str) or not relative:
            raise CheckFailure(f"contract.source_ownership.{key} must be a non-empty path")
        if not (root / relative).is_file():
            raise CheckFailure(f"contract.source_ownership.{key}: missing file {relative}")

    reservation = contract.get("reserved_memory_contract")
    if not isinstance(reservation, dict):
        raise CheckFailure("contract.reserved_memory_contract must be an object")
    for key, expected in {
        "official_reservation_mechanism": "device_tree_reserved_memory_no_map",
        "official_mechanism_count": 1,
        "kernel_memory_limit_bootarg_is_active_alternative": False,
        "address_cells": 1,
        "size_cells": 1,
        "hps_physical_base": "0x000000003e000000",
        "fpga_visible_base": "0x000000003e000000",
        "size_bytes": RING_SIZE,
        "end_exclusive": "0x0000000040000000",
        "guard_bytes": RING_GUARD,
        "record_alignment_bytes": RING_ALIGNMENT,
        "natural_alignment_bytes": RING_SIZE,
        "no_map": True,
        "reusable": False,
        "shared_dma_pool": False,
        "linux_allocator_may_use_region": False,
        "must_be_present_in_fdt_before_linux_boot": True,
        "runtime_configfs_overlay_is_sufficient": False,
    }.items():
        require_equal(reservation.get(key), expected, f"contract.reserved_memory_contract.{key}")

    evidence = contract.get("evidence_policy")
    if not isinstance(evidence, dict):
        raise CheckFailure("contract.evidence_policy must be an object")
    require_equal(evidence.get("default_checker_scope"), "source_only", "contract.evidence_policy.default_checker_scope")
    for key, value in evidence.items():
        if key.startswith("source_check_is_") or key == "external_tool_execution_performed_by_checker":
            require_equal(value, False, f"contract.evidence_policy.{key}")


def find_ring_region(address_map: dict[str, Any]) -> dict[str, Any]:
    regions = address_map.get("regions")
    if not isinstance(regions, list):
        raise CheckFailure("address map regions must be an array")
    matches = [region for region in regions if isinstance(region, dict) and region.get("name") == "telemetry_ddr_ring"]
    if len(matches) != 1:
        raise CheckFailure(f"address map must contain exactly one telemetry_ddr_ring, got {len(matches)}")
    return matches[0]


def tcl_scalar(text: str, key: str) -> str:
    matches = re.findall(rf"^\s*{re.escape(key)}\s+(\S+)\s*$", text, flags=re.MULTILINE)
    if len(matches) != 1:
        raise CheckFailure(f"hps_config.tcl: expected one baseline {key}, got {len(matches)}")
    return matches[0]


def validate_geometry(root: Path, contract: dict[str, Any]) -> None:
    reservation = contract["reserved_memory_contract"]
    address_map = load_json(root / ADDRESS_MAP_REL)
    runtime = load_json(root / HPS_RUNTIME_REL)
    tcl_text = read_text(root / HPS_CONFIG_TCL_REL)
    if not isinstance(address_map, dict) or not isinstance(runtime, dict):
        raise CheckFailure("address-map and HPS runtime roots must be objects")
    region = find_ring_region(address_map)

    comparisons = {
        "contract HPS base": parse_int(reservation["hps_physical_base"], "contract HPS base"),
        "contract FPGA base": parse_int(reservation["fpga_visible_base"], "contract FPGA base"),
        "contract size": parse_int(reservation["size_bytes"], "contract size"),
        "contract end": parse_int(reservation["end_exclusive"], "contract end"),
        "contract guard": parse_int(reservation["guard_bytes"], "contract guard"),
        "address-map HPS base": parse_int(region.get("hps_physical_base"), "address-map HPS base"),
        "address-map FPGA base": parse_int(region.get("fpga_visible_base"), "address-map FPGA base"),
        "address-map size": parse_int(region.get("size_bytes"), "address-map size"),
        "address-map end": parse_int(region.get("end_exclusive"), "address-map end"),
        "address-map guard": parse_int(region.get("guard_bytes"), "address-map guard"),
        "HPS runtime base": parse_int(runtime.get("ring_base_hps_phys"), "HPS runtime base"),
        "HPS runtime FPGA base": parse_int(runtime.get("ring_base_fpga"), "HPS runtime FPGA base"),
        "HPS runtime size": parse_int(runtime.get("ring_size_bytes"), "HPS runtime size"),
        "HPS runtime guard": parse_int(runtime.get("ring_guard_bytes"), "HPS runtime guard"),
        "hps_config.tcl HPS base": parse_int(tcl_scalar(tcl_text, "ring_base_hps_phys"), "Tcl HPS base"),
        "hps_config.tcl FPGA base": parse_int(tcl_scalar(tcl_text, "ring_base_fpga"), "Tcl FPGA base"),
        "hps_config.tcl size": parse_int(tcl_scalar(tcl_text, "ring_size_bytes"), "Tcl size"),
        "hps_config.tcl guard": parse_int(tcl_scalar(tcl_text, "ring_guard_bytes"), "Tcl guard"),
    }
    for label in (
        "contract HPS base",
        "contract FPGA base",
        "address-map HPS base",
        "address-map FPGA base",
        "HPS runtime base",
        "HPS runtime FPGA base",
        "hps_config.tcl HPS base",
        "hps_config.tcl FPGA base",
    ):
        require_equal(comparisons[label], RING_BASE, label)
    for label in ("contract size", "address-map size", "HPS runtime size", "hps_config.tcl size"):
        require_equal(comparisons[label], RING_SIZE, label)
    require_equal(comparisons["contract end"], RING_END, "contract end")
    require_equal(comparisons["address-map end"], RING_END, "address-map end")
    for label in ("contract guard", "address-map guard", "HPS runtime guard", "hps_config.tcl guard"):
        require_equal(comparisons[label], RING_GUARD, label)
    require_equal(parse_int(region.get("alignment_bytes"), "address-map alignment"), RING_ALIGNMENT, "address-map alignment")
    require_equal(parse_int(region.get("natural_alignment_bytes"), "address-map natural alignment"), RING_SIZE, "address-map natural alignment")
    require_equal(RING_BASE + RING_SIZE, RING_END, "base + size")


def validate_dtsi(root: Path) -> None:
    raw = read_text(root / DTSI_REL)
    text = strip_c_comments(raw)
    require_regex(text, r"#address-cells\s*=\s*<\s*1\s*>\s*;", DTSI_REL.as_posix())
    require_regex(text, r"#size-cells\s*=\s*<\s*1\s*>\s*;", DTSI_REL.as_posix())
    require_regex(text, r"\branges\s*;", DTSI_REL.as_posix())
    node_match = require_regex(
        text,
        r"trecap_telemetry_ring\s*:\s*trecap-ring@3e000000\s*\{(?P<body>[^{}]*)\}",
        DTSI_REL.as_posix(),
    )
    node_body = node_match.group("body")
    require_regex(
        node_body,
        r"\breg\s*=\s*<\s*0x3e000000\s+0x02000000\s*>\s*;",
        "T-RECAP reserved-memory node",
    )
    require_regex(node_body, r"\bno-map\s*;", "T-RECAP reserved-memory node")
    for forbidden in (
        r"\breusable\b",
        r"\bcompatible\s*=",
        r"\bshared-dma-pool\b",
        r"\blinux,cma-default\b",
        r"\balloc-ranges\b",
    ):
        forbid_regex(node_body, forbidden, "T-RECAP reserved-memory node")
    require_equal(len(re.findall(r"\btrecap-ring@", text)), 1, "DTSI T-RECAP node count")


def candidate_policy_files(root: Path) -> Iterable[Path]:
    for relative_root in ("sw", "platform", "config", "docs"):
        start = root / relative_root
        if not start.is_dir():
            continue
        for path in start.rglob("*"):
            if path.is_file() and path.suffix.lower() in {
                ".md", ".txt", ".sh", ".service", ".conf", ".cfg", ".tcl", ".json", ".dts", ".dtsi"
            }:
                yield path
    for name in ("README.md", "Makefile"):
        path = root / name
        if path.is_file():
            yield path


def validate_single_reservation_policy(root: Path) -> None:
    retired_limit_pattern = re.compile(r"\bmem\s*=\s*992[Mm]\b")
    active_bootarg_pattern = re.compile(r"(?im)^\s*(?:setenv\s+bootargs|bootargs\s*=).*?\bmem\s*=")
    violations: list[str] = []
    for path in candidate_policy_files(root):
        text = read_text(path)
        active_reference = active_bootarg_pattern.search(text) is not None
        for match in retired_limit_pattern.finditer(text):
            context = text[max(0, match.start() - 160) : match.end() + 160].lower()
            negative_markers = (
                "not a second",
                "not an active",
                "must not",
                "retired",
                "forbidden",
            )
            if not any(marker in context for marker in negative_markers):
                active_reference = True
                break
        if active_reference:
            violations.append(path.relative_to(root).as_posix())
    if violations:
        raise CheckFailure(
            "DTS-only policy violated by active/legacy kernel memory-limit guidance in: "
            + ", ".join(sorted(set(violations)))
        )


def normalized_assignments(text: str, signal: str) -> list[str]:
    return [compact(rhs) for rhs in re.findall(rf"\b{re.escape(signal)}\s*<=\s*([^;]+);", text)]


def validate_pointer_rtl(root: Path) -> None:
    pointer = strip_c_comments(read_text(root / POINTER_REL))
    pointer_compact = compact(pointer)

    producer_assignments = normalized_assignments(pointer, "producer_ptr_q")
    if not producer_assignments:
        raise CheckFailure("pointer RTL has no producer_ptr_q assignments")
    unexpected_producer = sorted(set(producer_assignments) - {"64'd0", "producer_next_comb"})
    if unexpected_producer:
        raise CheckFailure(f"producer pointer has non-writer assignment sources: {unexpected_producer}")
    require_equal(producer_assignments.count("producer_next_comb"), 1, "producer writer-commit assignment count")

    consumer_assignments = normalized_assignments(pointer, "consumer_ptr_q")
    require_equal(sorted(consumer_assignments), sorted(["64'd0", "ring_rd_commit_ptr_i"]), "consumer pointer assignment sources")

    for token in (
        "assignpointers_valid_comb=config_legal&&rd_epoch_valid_q&&",
        "aligned64(ring_rd_commit_ptr_i)",
        "!rd_epoch_valid_q&&(ring_rd_commit_ptr_i==64'd0)",
        "rd_epoch_valid_q&&(ring_rd_commit_ptr_i>=consumer_ptr_q)",
        "ring_rd_commit_ptr_i<=producer_ptr_q",
        "(producer_ptr_q-ring_rd_commit_ptr_i)<=ring_size_64",
        "consumer_ptr_q<=ring_rd_commit_ptr_i;rd_epoch_valid_q<=1'b1",
        "assignconsumer_ptr_o=rd_epoch_valid_q?consumer_ptr_q:64'd0",
        "producer_advance_is_normal_i&&(producer_advance_bytes_i>=HEADER_BYTES_64)",
        "producer_advance_bytes_i<=current_tail_comb",
        "producer_advance_is_wrap_i&&(current_offset_comb!=64'd0)",
        "producer_advance_bytes_i==current_tail_comb",
        "current_tail_comb+scheduled_record_bytes_i",
        "if(producer_advance_is_normal_i)beginsequence_q<=sequence_q+32'd1",
    ):
        require_token(pointer_compact, token, POINTER_REL.as_posix())

    require_regex(
        pointer_compact,
        r"if\(soft_reset_i\)beginconfig_q<='0;producer_ptr_q<=64'd0;sequence_q<=32'd0;.*?rd_epoch_valid_q<=1'b0;end",
        "pointer soft-reset epoch",
    )
    require_regex(
        pointer_compact,
        r"elseif\(ring_config_commit_pulse_i\)beginconfig_q<=ring_config_i;producer_ptr_q<=64'd0;sequence_q<=32'd0;.*?rd_epoch_valid_q<=1'b0;end",
        "pointer ring-config epoch",
    )
    require_equal(normalized_assignments(pointer, "rd_epoch_valid_q").count("1'b1"), 1, "consumer epoch set count")
    if normalized_assignments(pointer, "rd_epoch_valid_q").count("1'b0") < 3:
        raise CheckFailure("consumer epoch must clear on hardware reset, soft reset, and config commit")


def validate_wrap_writer_rtl(root: Path) -> None:
    builder = compact(strip_c_comments(read_text(root / BUILDER_REL)))
    writer = compact(strip_c_comments(read_text(root / WRITER_REL)))
    avmm_master = compact(strip_c_comments(read_text(root / AVMM_MASTER_REL)))
    for token in (
        "functionautomaticrecord_store_tbuild_wrap_record()",
        "next_record='0",
        "TPKT_WRAP",
        "pending_wrap_bytes_q>=TPKT_DDR_ALIGN_BYTES",
        "is_aligned64(pending_wrap_bytes_q)",
        "record_q<=build_wrap_record()",
        "record_bytes_q<=pending_wrap_bytes_q",
        "record_payload_bytes_q<=16'd0",
        "record_seq_q<=32'd0",
        "packet_type:TPKT_WRAP",
        "payload_bytes:16'd0",
    ):
        require_token(builder, token, BUILDER_REL.as_posix())
    for token in (
        "idle_has_record=(state_q==WSTATE_IDLE)&&record_valid_i&&run_enable&&ptr_ring_configured&&ptr_pointers_valid",
        "if(idle_need_wrap)begin",
        "current_write_addr_q<=schedule_wrap_addr_trunc",
        "current_advance_bytes_q<=schedule_tail_bytes",
        "current_is_wrap_q<=1'b1",
        "if(avmm_done_pulse&&!avmm_response_error_now)",
        "producer_advance_valid=(state_q==WSTATE_COMMIT_REQ)&&!commit_sent_q&&!avmm_response_error_now&&!avmm_response_error_sticky",
        "if(current_is_wrap_q)beginwrap_commit_pulse_o<=1'b1",
    ):
        require_token(writer, token, WRITER_REL.as_posix())
    for token in (
        ".CHECK_RESPONSES(1'b1)",
    ):
        require_token(writer, token, WRITER_REL.as_posix())
    for token in (
        "response_success=CHECK_RESPONSES&&(state_q==MSTATE_WAIT_RESPONSE)&&avm_writeresponsevalid_i&&(avm_response_i==2'b00)",
        "response_unexpected=CHECK_RESPONSES&&avm_writeresponsevalid_i&&(state_q!=MSTATE_WAIT_RESPONSE)",
        "if(response_success)beginif(response_completes_record_q)beginwrite_done_pulse_o<=1'b1",
    ):
        require_token(avmm_master, token, AVMM_MASTER_REL.as_posix())


def validate_csr_reset_rtl(root: Path) -> None:
    csr = compact(strip_c_comments(read_text(root / CSR_REL)))
    bridge = compact(strip_c_comments(read_text(root / HPS_BRIDGE_REL)))
    for token in (
        "inputlogicring_pointers_valid_i",
        "if(!ring_rd_epoch_valid_q)beginreturnvalue==64'd0",
        "if(!ring_pointers_valid_i)beginreturn1'b0",
        "returnvalue>=ring_rd_active",
        "telemetry_enable_q||ring_writer_enable_q||!writer_idle_i",
        "!ring_configured_q||!ring_rd_epoch_valid_q||!ring_pointers_valid_i",
        "ring_rd_state_clear=soft_reset_req||external_transport_clear_i||ring_config_commit_req",
        ".CLEAR_VALUES_ON_CLEAR(1'b1)",
        ".clear_i(ring_rd_state_clear)",
        "if(soft_reset_req||external_transport_clear_i)beginring_configured_q<=1'b0",
        "if(external_transport_clear_i)begintelemetry_enable_q<=1'b0;ring_writer_enable_q<=1'b0",
        "if(soft_reset_req||external_transport_clear_i||ring_config_commit_req)beginring_rd_epoch_valid_q<=1'b0",
        "elseif(ring_rd_commit_pulse_o)beginring_rd_epoch_valid_q<=1'b1",
    ):
        require_token(csr, token, CSR_REL.as_posix())
    for token in (
        "writer_transport_clear=csr_telemetry_soft_reset_pulse|external_transport_clear_i",
        ".external_transport_clear_i(external_transport_clear_i)",
        ".ring_pointers_valid_i(writer_pointers_valid)",
        ".clear_i(writer_transport_clear)",
    ):
        require_token(bridge, token, HPS_BRIDGE_REL.as_posix())


def validate_hps_ownership_source(root: Path) -> None:
    reader = compact(strip_c_comments(read_text(root / HPS_RING_READER_REL)))
    streamer = compact(strip_c_comments(read_text(root / HPS_STREAMER_REL)))
    config_source = compact(strip_c_comments(read_text(root / HPS_CONFIG_SOURCE_REL)))
    config_header = compact(strip_c_comments(read_text(root / HPS_CONFIG_HEADER_REL)))
    runner = compact(read_text(root / HPS_RUNNER_REL))

    for token in (
        "if(cacheable_mapping){returnTRECAP_RING_ERR_CONFIG;}",
        'open("/dev/mem",O_RDONLY|O_SYNC)',
        "mmap(NULL,ring_size_bytes,PROT_READ,MAP_SHARED,fd,(off_t)ring_base_hps_phys)",
        "ring_guard_bytes!=(uint32_t)TCSR_RING_GUARD_BYTES_MIN",
        "if((rd%(uint64_t)TPKT_DDR_ALIGN_BYTES)!=0u)",
        "if(rd<reader->rd)",
        "trecap_ring_pointer_state_is_valid(reader->wr_snapshot,rd,reader->cfg.ring_size_bytes)",
        "trecap_csr_commit_ring_rd(reader->csr,rd)",
    ):
        require_token(reader, token, HPS_RING_READER_REL.as_posix())

    for token in (
        "TRECAP_HPS_DE1SOC_RING_HPS_BASEUINT64_C(0x000000003e000000)",
        "TRECAP_HPS_DE1SOC_RING_FPGA_BASEUINT64_C(0x000000003e000000)",
        "TRECAP_HPS_DE1SOC_RING_SIZE_BYTESUINT32_C(0x02000000)",
    ):
        require_token(config_header, token, HPS_CONFIG_HEADER_REL.as_posix())
    for token in (
        "cfg->ring_base_hps_phys!=TRECAP_HPS_DE1SOC_RING_HPS_BASE",
        "cfg->ring_base_fpga!=TRECAP_HPS_DE1SOC_RING_FPGA_BASE",
        "cfg->ring_size_bytes!=TRECAP_HPS_DE1SOC_RING_SIZE_BYTES",
        "if(cfg->allow_cached_ring_mapping)",
    ):
        require_token(config_source, token, HPS_CONFIG_SOURCE_REL.as_posix())
    require_ordered_tokens(
        reader,
        (
            "if(!reader->cfg.commit_rd_after_each_record){returnTRECAP_RING_ERR_CONFIG;}",
            "trecap_ring_status_tstatus=trecap_ring_reader_commit_rd(reader,view->absolute_next_rd)",
            "if(status!=TRECAP_RING_OK){returnstatus;}",
            "reader->counters.records_seen+=1u",
        ),
        "HPS mandatory atomic local/CSR Rd advance",
    )
    for forbidden in ("--allow-cached-ring-mapping", "--allow-system-ram-overlap"):
        if forbidden in streamer or forbidden in runner:
            raise CheckFailure(f"HPS source retains forbidden unsafe option {forbidden}")
    require_token(
        runner,
        'if[["${SKIP_DDR_CHECK}"-eq1&&"${DRY_RUN}"-eq0&&"${PRE_FLIGHT_ONLY}"-eq0]]',
        "HPS launcher reservation bypass restriction",
    )

    require_ordered_tokens(
        reader,
        (
            "trecap_csr_set_control_levels(reader->csr,false,false)",
            "for(uint32_tpoll=0u;poll<TRECAP_RING_RESET_MAX_POLLS;++poll)",
            "writer_idle&&!writer_busy",
            "if(!writer_drained){returnTRECAP_RING_ERR_TIMEOUT;}",
            "trecap_csr_pulse_control(reader->csr,TCSR_CONTROL_TELEMETRY_SOFT_RESET_MASK)",
        ),
        "HPS bounded reset sequence",
    )
    require_ordered_tokens(
        reader,
        (
            "if((rd%(uint64_t)TPKT_DDR_ALIGN_BYTES)!=0u)",
            "if(rd<reader->rd)",
            "trecap_ring_pointer_state_is_valid(reader->wr_snapshot,rd,reader->cfg.ring_size_bytes)",
            "trecap_csr_commit_ring_rd(reader->csr,rd)",
            "reader->rd=rd",
        ),
        "HPS Rd validation and commit",
    )
    require_ordered_tokens(
        streamer,
        (
            "trecap_ring_reader_reset_transport(&state->ring_reader)",
            "trecap_ring_reader_configure_fpga_ring(&state->ring_reader",
            "trecap_ring_reader_commit_rd(&state->ring_reader,0u)",
            "trecap_ring_reader_snapshot_wr(&state->ring_reader,&producer_ptr)",
            "producer_ptr!=0u",
            "trecap_csr_set_control_levels(&state->csr,false,true)",
            "trecap_csr_set_control_levels(&state->csr,true,true)",
        ),
        "HPS deterministic bring-up sequence",
    )


def validate_documents(root: Path) -> None:
    doc = read_text(root / DOC_REL)
    note = read_text(root / RESERVATION_NOTE_REL)
    for token in (
        "[0x3e000000, 0x40000000)",
        "trecap_reserved_memory.dtsi",
        "no-map",
        "FPGA DDR ring writer",
        "HPS reader",
        "Ttail + Lrec",
        "Commit `Rd=0`",
        "does **not** claim",
    ):
        require_token(doc, token, DOC_REL.as_posix())
    for token in (
        "one official",
        "trecap_reserved_memory.dtsi",
        "no-map",
        "active board DTB",
        "/proc/iomem",
        "unproven reservation",
    ):
        require_token(note, token, RESERVATION_NOTE_REL.as_posix())


def run_checks(root: Path, force_fallback: bool) -> str:
    contract = load_json(root / CONTRACT_REL)
    schema = load_json(root / SCHEMA_REL)
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        raise CheckFailure("contract and schema roots must be JSON objects")
    validator = validate_contract_schema(contract, schema, force_fallback)
    validate_contract_values(root, contract)
    validate_geometry(root, contract)
    validate_dtsi(root)
    validate_single_reservation_policy(root)
    validate_pointer_rtl(root)
    validate_wrap_writer_rtl(root)
    validate_csr_reset_rtl(root)
    validate_hps_ownership_source(root)
    validate_documents(root)
    return validator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repo_root_from_script())
    parser.add_argument(
        "--force-fallback-schema-validator",
        action="store_true",
        help="exercise the dependency-free Draft-2020-12 subset validator",
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    try:
        validator = run_checks(root, args.force_fallback_schema_validator)
    except CheckFailure as exc:
        print(f"ERROR: Step-12 DDR ring ownership source check failed: {exc}", file=sys.stderr)
        return 1
    print("Step-12 DE1-SoC DDR ring ownership source check: PASS")
    print(f"  schema validator : {validator}")
    print("  reserved interval: [0x3e000000, 0x40000000) (32 MiB, no-map)")
    print("  ownership        : FPGA-only W; HPS-commit-only Rd with explicit epoch")
    print("  WRAP/reset       : structural source contracts present")
    print("  HPS mapping/init : read-only no-map access; bounded ordered re-arm")
    print("  evidence         : source-only; DTB/boot/runtime/simulation/Quartus/hardware pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
