#!/usr/bin/env python3
"""Check the Step-5 Avalon-MM CSR adapter source contract.

This is a dependency-free structural/source-consistency gate.  It checks the
raw RTL freeze, exact contract values, schema identity, selected RTL semantics,
logical top-chain wiring, generated filelists, Step-4 address-map parity, and
the human architecture document.  If ``jsonschema`` happens to be installed,
schema validation is added, but it is never required for the manual gate.

Passing this script is not functional verification, Platform Designer
generation evidence, a Quartus compile, SOPCINFO evidence, or hardware signoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

try:
    import jsonschema  # type: ignore[import-not-found]
except ImportError:
    jsonschema = None


CONTRACT_REL = Path("platform/de1soc/address_map/avalon_csr_adapter.json")
SCHEMA_REL = Path("spec/schemas/avalon_csr_adapter.schema.json")
DOC_REL = Path("docs/architecture/avalon_mm_csr_adapter.md")
RTL_REL = Path("rtl/hps_bridge/trecap_avmm_csr_adapter.sv")
CSR_BANK_REL = Path("rtl/hps_bridge/trecap_csr_bank.sv")
HPS_TOP_REL = Path("rtl/hps_bridge/trecap_hps_bridge_top.sv")
FULL_TOP_REL = Path("rtl/top/trecap_de1soc_full_top.sv")
BOARD_TOP_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
PLATFORM_WRAPPER_REL = Path("rtl/platform/de1soc/platform_designer_wrapper.sv")
STEP4_MAP_REL = Path("platform/de1soc/address_map/hps_bridge_regions.json")
QSYS_REL = Path("platform/de1soc/qsys/system.qsys")
GENERATOR_REL = Path("scripts/gen_filelists.py")
FILELIST_RELS = (
    Path("filelists/rtl_hps_bridge.f"),
    Path("filelists/rtl_de1soc_full.f"),
    Path("filelists/quartus_de1soc.qsf.inc"),
)

EXPECTED_SCHEMA = "trecap_phase2_de1soc_avalon_csr_adapter_v1"
EXPECTED_STAGE = "step5_avalon_mm_csr_adapter_source_implemented"
EXPECTED_STATUS = (
    "source_implemented_and_board_source_connected_pending_generation_compile_and_hardware_evidence"
)
EXPECTED_RTL_SHA256 = (
    "ba096b8203fafae8099e830506c14f4eead8f95c6c0667ebd422e998de9fe40c"
)

EXPECTED_SOURCE_FREEZE: dict[str, object] = {
    "scope": "raw_adapter_rtl_source_only",
    "rtl_file": RTL_REL.as_posix(),
    "raw_sha256": EXPECTED_RTL_SHA256,
    "hash_algorithm": "sha256_raw_file_bytes",
    "source_implemented": True,
    "platform_designer_connected": True,
    "functional_verification_complete": False,
    "hardware_signoff": False,
}

EXPECTED_ADDRESS: dict[str, object] = {
    "address_unit": "byte",
    "avalon_address_width_bits": 21,
    "lightweight_aperture_span_bytes": 2_097_152,
    "csr_base_offset_bytes": 0,
    "csr_window_span_bytes": 4_096,
    "csr_leaf_byte_address_width_bits": 12,
    "forwarded_leaf_address_bits": "avs_address_i[11:0]",
    "all_avalon_address_bits_decoded": True,
    "full_decode_required": True,
    "accepted_offset_range": "[0x000000,0x001000)",
    "unused_aperture_policy": "decode_error_no_csr_aliasing",
}

EXPECTED_TRANSFER: dict[str, object] = {
    "data_width_bits": 32,
    "byte_order": "little_endian",
    "alignment_bytes": 4,
    "read_byteenable_required": "0xf",
    "write_byteenable_required": "0xf",
    "burstcount_width_bits": 1,
    "burstcount_required": 1,
    "read_write_mutually_exclusive": True,
    "maximum_outstanding_transactions": 1,
    "request_fields_stable_while_waitrequest": True,
    "waitrequest_asserted_during_reset": True,
    "waitrequest_asserted_while_busy": True,
    "response_never_in_acceptance_cycle": True,
    "local_rejects_forwarded_to_leaf": False,
}

EXPECTED_RESPONSE: dict[str, object] = {
    "shared_response_width_bits": 2,
    "codes": {"okay": 0, "slave_error": 2, "decode_error": 3},
    "out_of_window_response": "decode_error",
    "misaligned_response": "slave_error",
    "partial_byteenable_response": "slave_error",
    "unsupported_burst_response": "slave_error",
    "leaf_error_response": "slave_error",
    "missing_read_valid_response": "slave_error",
    "read_error_data": "0x00000000",
    "write_response_required_for_every_accepted_write": True,
    "read_response_required_for_every_accepted_read": True,
    "read_and_write_response_valid_mutually_exclusive": True,
    "illegal_simultaneous_read_write_policy": (
        "read_priority_single_read_response_address_classification_still_applies"
    ),
    "illegal_simultaneous_read_write_forwarded_to_leaf": False,
}

EXPECTED_LEAF: dict[str, object] = {
    "request_interface": "private_valid_ready_request",
    "request_held_until_ready": True,
    "request_fields_stable_until_ready": True,
    "result_latency_cycles_after_acceptance": 1,
    "read_success_requires_rvalid": True,
    "write_success_requires_no_error": True,
    "leaf_error_maps_to": "slave_error",
    "local_reject_pulse_scope": "pre_leaf_adapter_rejects_only",
    "local_reject_counting_path": "dedicated_csr_bank_input_no_leaf_double_count",
    "leaf_command_reject_accounting_owner": CSR_BANK_REL.as_posix(),
}

EXPECTED_INTEGRATION: dict[str, object] = {
    "adapter_rtl": RTL_REL.as_posix(),
    "csr_leaf_rtl": CSR_BANK_REL.as_posix(),
    "adapter_owner": HPS_TOP_REL.as_posix(),
    "logical_top": FULL_TOP_REL.as_posix(),
    "board_top": BOARD_TOP_REL.as_posix(),
    "board_top_current_state": "platform_designer_wrapper_source_connected",
    "current_hps_export": "trecap_csr_bridge.m0",
    "current_hps_export_protocol": "avalon_mm_after_qsys_axi_to_avalon_adaptation",
    "required_pending_platform_graph": "quartus_normalized_generated_interconnect_evidence",
    "required_platform_wrapper_source": PLATFORM_WRAPPER_REL.as_posix(),
    "required_pending_hardware_evidence": "platform/de1soc/qsys/system.sopcinfo",
    "board_connectivity_complete": False,
}

EXPECTED_EVIDENCE: dict[str, object] = {
    "source_checker": "scripts/check_csr_adapter.py",
    "human_document": DOC_REL.as_posix(),
    "schema_file": SCHEMA_REL.as_posix(),
    "compile_evidence_present": False,
    "platform_designer_generation_evidence_present": False,
    "functional_verification_present": False,
    "hardware_evidence_present": False,
}

EXPECTED_RULES = [
    "Decode all 21 byte-address bits before forwarding the lower 12 bits to the CSR leaf.",
    "Accept only aligned, full-width, little-endian, single-beat 32-bit transfers.",
    "Never issue a CSR leaf request for an out-of-window or malformed Avalon request.",
    "Permit at most one outstanding transaction and emit exactly one response for it.",
    "Return DECODEERROR for an address outside the 4 KiB window and SLVERR for malformed or leaf-rejected accesses.",
    "Return zero read data with every error response.",
    "Use one read response for an illegal simultaneous read/write assertion: SLVERR in-window, or DECODEERROR when the address is also outside the window.",
    "Count local_reject_pulse_o only for requests rejected before the CSR leaf.",
    "Count adapter-local rejects through a dedicated CSR-bank input so concurrent external rejects do not coalesce them.",
    "Do not claim board connectivity complete until generated HDL, SOPCINFO, Quartus compile, and hardware evidence exist.",
    "Functional verification is intentionally deferred beyond Step 6.",
]


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def read_bytes(root: Path, rel: Path, errors: list[str]) -> bytes:
    try:
        return (root / rel).read_bytes()
    except OSError as exc:
        add_error(errors, f"cannot read {rel}: {exc}")
        return b""


def read_text(root: Path, rel: Path, errors: list[str]) -> str:
    raw = read_bytes(root, rel, errors)
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        add_error(errors, f"{rel} is not UTF-8: {exc}")
        return ""


def load_json(root: Path, rel: Path, errors: list[str]) -> dict[str, Any]:
    text = read_text(root, rel, errors)
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        add_error(errors, f"cannot parse {rel}: {exc}")
        return {}
    if not isinstance(value, dict):
        add_error(errors, f"{rel} root must be a JSON object")
        return {}
    return value


def require_equal(
    errors: list[str], label: str, actual: object, expected: object
) -> None:
    if actual != expected:
        add_error(errors, f"{label}: expected {expected!r}, got {actual!r}")


def require_exact_mapping(
    errors: list[str], label: str, actual: object, expected: Mapping[str, object]
) -> None:
    if not isinstance(actual, Mapping):
        add_error(errors, f"{label} must be an object")
        return
    require_equal(errors, label, dict(actual), dict(expected))


def require_tokens(
    errors: list[str], rel: Path, text: str, tokens: tuple[str, ...]
) -> None:
    for token in tokens:
        if token not in text:
            add_error(errors, f"{rel} lacks required token: {token!r}")


def check_contract(
    root: Path, contract: Mapping[str, Any], errors: list[str]
) -> None:
    expected_top_keys = {
        "schema",
        "file_class",
        "project",
        "board",
        "contract_stage",
        "status",
        "source_freeze",
        "address_contract",
        "transfer_contract",
        "response_contract",
        "csr_leaf_contract",
        "integration",
        "evidence_policy",
        "validation_rules",
    }
    require_equal(errors, "contract keys", set(contract), expected_top_keys)
    require_equal(errors, "contract schema", contract.get("schema"), EXPECTED_SCHEMA)
    require_equal(
        errors,
        "contract file_class",
        contract.get("file_class"),
        "[1] hand-written Step-5 interface contract",
    )
    require_equal(errors, "contract project", contract.get("project"), "T_RECAP_Phase2")
    require_equal(errors, "contract board", contract.get("board"), "de1soc")
    require_equal(errors, "contract stage", contract.get("contract_stage"), EXPECTED_STAGE)
    require_equal(errors, "contract status", contract.get("status"), EXPECTED_STATUS)
    require_exact_mapping(
        errors, "source_freeze", contract.get("source_freeze"), EXPECTED_SOURCE_FREEZE
    )
    require_exact_mapping(
        errors, "address_contract", contract.get("address_contract"), EXPECTED_ADDRESS
    )
    require_exact_mapping(
        errors, "transfer_contract", contract.get("transfer_contract"), EXPECTED_TRANSFER
    )
    require_exact_mapping(
        errors, "response_contract", contract.get("response_contract"), EXPECTED_RESPONSE
    )
    require_exact_mapping(
        errors, "csr_leaf_contract", contract.get("csr_leaf_contract"), EXPECTED_LEAF
    )
    require_exact_mapping(
        errors, "integration", contract.get("integration"), EXPECTED_INTEGRATION
    )
    require_exact_mapping(
        errors, "evidence_policy", contract.get("evidence_policy"), EXPECTED_EVIDENCE
    )
    require_equal(errors, "validation_rules", contract.get("validation_rules"), EXPECTED_RULES)

    rtl = read_bytes(root, RTL_REL, errors)
    if rtl:
        actual_hash = hashlib.sha256(rtl).hexdigest()
        require_equal(errors, "adapter RTL raw SHA-256", actual_hash, EXPECTED_RTL_SHA256)
        freeze = contract.get("source_freeze")
        pinned = freeze.get("raw_sha256") if isinstance(freeze, Mapping) else None
        require_equal(errors, "contract-pinned RTL SHA-256", pinned, actual_hash)


def schema_const(schema: Mapping[str, Any], property_name: str) -> object:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return None
    node = properties.get(property_name)
    if not isinstance(node, Mapping):
        return None
    return node.get("const")


def definition_const(
    schema: Mapping[str, Any], definition: str, property_name: str
) -> object:
    definitions = schema.get("$defs")
    if not isinstance(definitions, Mapping):
        return None
    block = definitions.get(definition)
    if not isinstance(block, Mapping):
        return None
    properties = block.get("properties")
    if not isinstance(properties, Mapping):
        return None
    node = properties.get(property_name)
    if not isinstance(node, Mapping):
        return None
    return node.get("const")


def check_schema(
    schema: Mapping[str, Any], contract: Mapping[str, Any], errors: list[str]
) -> None:
    require_equal(
        errors,
        "JSON Schema dialect",
        schema.get("$schema"),
        "https://json-schema.org/draft/2020-12/schema",
    )
    require_equal(
        errors,
        "JSON Schema id",
        schema.get("$id"),
        "https://trecap.local/schemas/avalon_csr_adapter.schema.json",
    )
    require_equal(errors, "schema root additionalProperties", schema.get("additionalProperties"), False)
    require_equal(errors, "schema identity const", schema_const(schema, "schema"), EXPECTED_SCHEMA)
    require_equal(errors, "schema stage const", schema_const(schema, "contract_stage"), EXPECTED_STAGE)
    require_equal(errors, "schema status const", schema_const(schema, "status"), EXPECTED_STATUS)
    require_equal(
        errors,
        "schema RTL hash const",
        definition_const(schema, "sourceFreeze", "raw_sha256"),
        EXPECTED_RTL_SHA256,
    )
    require_equal(
        errors,
        "schema address width const",
        definition_const(schema, "addressContract", "avalon_address_width_bits"),
        21,
    )
    require_equal(
        errors,
        "schema CSR span const",
        definition_const(schema, "addressContract", "csr_window_span_bytes"),
        4096,
    )
    require_equal(
        errors,
        "schema byteenable const",
        definition_const(schema, "transferContract", "read_byteenable_required"),
        "0xf",
    )
    require_equal(
        errors,
        "schema outstanding const",
        definition_const(schema, "transferContract", "maximum_outstanding_transactions"),
        1,
    )
    require_equal(
        errors,
        "schema board connectivity const",
        definition_const(schema, "integration", "board_connectivity_complete"),
        False,
    )

    if jsonschema is not None:
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(contract)
        except Exception as exc:  # pragma: no cover - optional dependency path
            add_error(errors, f"contract does not validate against {SCHEMA_REL}: {exc}")


def check_rtl(root: Path, errors: list[str]) -> None:
    rtl = read_text(root, RTL_REL, errors)
    if not rtl:
        return
    require_tokens(
        errors,
        RTL_REL,
        rtl,
        (
            "module trecap_avmm_csr_adapter #(",
            "parameter int unsigned AVMM_ADDR_W       = 21",
            "parameter int unsigned CSR_ADDR_W        = 12",
            "parameter int unsigned BURSTCOUNT_W      = 1",
            "parameter logic [AVMM_ADDR_W-1:0] CSR_BASE_ADDR = '0",
            "localparam logic [1:0] AVMM_RESPONSE_OKAY        = 2'b00;",
            "localparam logic [1:0] AVMM_RESPONSE_SLVERR      = 2'b10;",
            "localparam logic [1:0] AVMM_RESPONSE_DECODEERROR = 2'b11;",
            "ASTATE_IDLE",
            "ASTATE_ISSUE",
            "ASTATE_WAIT_RESULT",
            "ASTATE_RESPOND",
            "assign dual_request = avs_read_i && avs_write_i;",
            "assign address_in_window = (((avs_address_i ^ CSR_BASE_ADDR) >> CSR_ADDR_W) == '0);",
            "assign address_aligned = (avs_address_i[1:0] == 2'b00);",
            "assign byteenable_full = (avs_byteenable_i == 4'b1111);",
            "assign burstcount_one = (avs_burstcount_i == one_burst());",
            "assign request_legal = !dual_request && address_in_window && address_aligned &&",
            "local_error_response = AVMM_RESPONSE_DECODEERROR;",
            "if (address_in_window) begin",
            "local_error_response = AVMM_RESPONSE_SLVERR;",
            "assign avs_waitrequest_o = !rst_n || (state_q != ASTATE_IDLE);",
            "assign busy_o = (state_q != ASTATE_IDLE);",
            "assign csr_valid_o = rst_n && (state_q == ASTATE_ISSUE);",
            "assign avs_readdata_o = (state_q == ASTATE_RESPOND) ? response_data_q : 32'd0;",
            "assign avs_readdatavalid_o = rst_n && (state_q == ASTATE_RESPOND) &&",
            "assign avs_writeresponsevalid_o = rst_n && (state_q == ASTATE_RESPOND) &&",
            "transaction_is_read_q <= avs_read_i;",
            "csr_addr_q <= CSR_ADDR_W'(avs_address_i);",
            "if (request_legal) begin",
            "local_reject_pulse_o <= 1'b1;",
            "if (csr_ready_i) begin",
            "if (csr_error_i) begin",
            "else if (transaction_is_read_q && !csr_rvalid_i) begin",
            "response_code_q <= AVMM_RESPONSE_SLVERR;",
            "response_data_q <= csr_rdata_i;",
            "((CSR_BASE_ADDR >> CSR_ADDR_W) << CSR_ADDR_W) != CSR_BASE_ADDR",
        ),
    )

    # These combinations would contradict the frozen single-outstanding response contract.
    if "assign csr_valid_o = request_present" in rtl:
        add_error(errors, f"{RTL_REL} bypasses the serialized ISSUE state")
    if "avs_readdatavalid_o && avs_writeresponsevalid_o" in rtl:
        add_error(errors, f"{RTL_REL} appears to combine both response-valid outputs")

    bank = read_text(root, CSR_BANK_REL, errors)
    if bank:
        require_tokens(
            errors,
            CSR_BANK_REL,
            bank,
            (
                "assign csr_ready_o = csr_valid_i;",
                "input  logic                    csr_adapter_reject_pulse_i,",
                "csr_rvalid_o <= read_req && addr_aligned && known_addr;",
                "csr_error_o <= (read_req && (!addr_aligned || !known_addr)) || write_reject;",
                "if (csr_adapter_reject_pulse_i) begin",
                "reject_increment_comb = reject_increment_comb + 2'd1;",
            ),
        )


def check_top_chain(root: Path, errors: list[str]) -> None:
    hps_top = read_text(root, HPS_TOP_REL, errors)
    full_top = read_text(root, FULL_TOP_REL, errors)
    board_top = read_text(root, BOARD_TOP_REL, errors)

    if hps_top:
        require_tokens(
            errors,
            HPS_TOP_REL,
            hps_top,
            (
                "parameter int unsigned CSR_AVMM_ADDR_W     = 21",
                "parameter int unsigned CSR_ADDR_W          = 12",
                "parameter int unsigned CSR_BURSTCOUNT_W    = 1",
                "input  logic [CSR_AVMM_ADDR_W-1:0]   csr_avs_address_i",
                "output logic                         csr_avs_waitrequest_o",
                "output logic                         csr_avs_readdatavalid_o",
                "output logic                         csr_avs_writeresponsevalid_o",
                "output logic [1:0]                   csr_avs_response_o",
                "trecap_avmm_csr_adapter #(",
                ".AVMM_ADDR_W(CSR_AVMM_ADDR_W)",
                ".CSR_ADDR_W(CSR_ADDR_W)",
                ".BURSTCOUNT_W(CSR_BURSTCOUNT_W)",
                ".CSR_BASE_ADDR('0)",
                ") u_avmm_csr_adapter (",
                ".csr_valid_o(csr_leaf_valid)",
                ".csr_ready_i(csr_leaf_ready)",
                ".csr_rvalid_i(csr_leaf_rvalid)",
                ".csr_error_i(csr_leaf_error)",
                ".local_reject_pulse_o(csr_adapter_local_reject_pulse)",
                ".csr_adapter_reject_pulse_i(csr_adapter_local_reject_pulse)",
                "CSR_AVMM_ADDR_W must be >= CSR_ADDR_W",
                "CSR_BURSTCOUNT_W must be at least 1",
                "trecap_csr_bank #(",
                ".csr_valid_i(csr_leaf_valid)",
                ".csr_ready_o(csr_leaf_ready)",
                "csr_adapter_local_reject_pulse),",
            ),
        )
        adapter_index = hps_top.find("trecap_avmm_csr_adapter #(")
        bank_index = hps_top.find("trecap_csr_bank #(")
        if adapter_index < 0 or bank_index < 0 or adapter_index >= bank_index:
            add_error(errors, f"{HPS_TOP_REL} must instantiate adapter before CSR bank")

    if full_top:
        require_tokens(
            errors,
            FULL_TOP_REL,
            full_top,
            (
                "parameter int unsigned CSR_AVMM_ADDR_W            = 21",
                "input  logic [CSR_AVMM_ADDR_W-1:0]   csr_avs_address_i",
                "output logic                         csr_avs_readdatavalid_o",
                "output logic                         csr_avs_writeresponsevalid_o",
                "trecap_hps_bridge_top #(",
                ".CSR_AVMM_ADDR_W(CSR_AVMM_ADDR_W)",
                ".csr_avs_address_i(csr_avs_address_i)",
                ".csr_avs_readdatavalid_o(csr_avs_readdatavalid_o)",
                ".csr_avs_writeresponsevalid_o(csr_avs_writeresponsevalid_o)",
                ".csr_avs_response_o(csr_avs_response_o)",
                "CSR address widths violate aperture/leaf contract",
            ),
        )

    if board_top:
        require_tokens(
            errors,
            BOARD_TOP_REL,
            board_top,
            (
                "platform_designer_wrapper #(",
                ") u_platform_designer_wrapper (",
                ".csr_avs_address_o(csr_avs_address)",
                ".csr_avs_read_o(csr_avs_read)",
                ".csr_avs_write_o(csr_avs_write)",
                ".csr_avs_address_i(csr_avs_address)",
                ".csr_avs_readdatavalid_o(csr_avs_readdatavalid)",
                ".csr_avs_writeresponsevalid_o(csr_avs_writeresponsevalid)",
                ".csr_avs_response_i(csr_avs_response)",
                "CSR address widths violate aperture/leaf contract",
            ),
        )
        if "_stub" in board_top:
            add_error(errors, f"{BOARD_TOP_REL} must not retain Step-5 safe-idle bus stubs")

    wrapper = read_text(root, PLATFORM_WRAPPER_REL, errors)
    if wrapper:
        require_tokens(
            errors,
            PLATFORM_WRAPPER_REL,
            wrapper,
            (
                "module platform_designer_wrapper #(",
                "system u_platform_designer_system (",
                ".trecap_csr_lw_master_address(csr_avs_address_o)",
                ".trecap_csr_lw_master_writeresponsevalid(csr_avs_writeresponsevalid_i)",
            ),
        )
    else:
        add_error(
            errors,
            f"{PLATFORM_WRAPPER_REL} is required by the Step-6 source integration",
        )


def check_filelists(root: Path, errors: list[str]) -> None:
    adapter_path = RTL_REL.as_posix()
    bank_path = CSR_BANK_REL.as_posix()
    generator = read_text(root, GENERATOR_REL, errors)
    if generator:
        if generator.count(f'"{adapter_path}"') != 1:
            add_error(errors, f"{GENERATOR_REL} must list {adapter_path} exactly once")
        if generator.find(f'"{adapter_path}"') >= generator.find(f'"{bank_path}"'):
            add_error(errors, f"{GENERATOR_REL} must place adapter before CSR bank")

    for rel in FILELIST_RELS:
        text = read_text(root, rel, errors)
        if not text:
            continue
        if text.count(adapter_path) != 1:
            add_error(errors, f"{rel} must list {adapter_path} exactly once")
        if text.find(adapter_path) >= text.find(bank_path):
            add_error(errors, f"{rel} must place adapter before CSR bank")


def check_step4_parity(root: Path, errors: list[str]) -> None:
    step4 = load_json(root, STEP4_MAP_REL, errors)
    bridges = step4.get("bridges")
    csr = bridges.get("csr_bridge") if isinstance(bridges, Mapping) else None
    if not isinstance(csr, Mapping):
        add_error(errors, f"{STEP4_MAP_REL} lacks bridges.csr_bridge")
    else:
        expected = {
            "hps_lw_span_bytes": 2_097_152,
            "csr_offset_in_lw": "0x0000000000000000",
            "csr_span_bytes": 4_096,
            "data_width_bits": 32,
            "master_byte_address_width_bits": 21,
            "csr_leaf_byte_address_width_bits": 12,
            "byte_order": "little_endian",
            "access_alignment_bytes": 4,
            "full_decode_required": True,
            "unused_aperture_policy": "unmapped_decode_error_no_csr_aliasing",
        }
        for key, value in expected.items():
            require_equal(errors, f"Step-4 csr_bridge.{key}", csr.get(key), value)

    qsys = read_text(root, QSYS_REL, errors)
    if qsys:
        require_tokens(
            errors,
            QSYS_REL,
            qsys,
            (
                'export name="trecap_csr_lw_master"',
                'internal="trecap_csr_bridge.m0"',
                'source="hps_0.h2f_lw_axi_master" sink="trecap_csr_bridge.s0"',
            ),
        )


def check_document(root: Path, errors: list[str]) -> None:
    doc = read_text(root, DOC_REL, errors)
    if not doc:
        return
    require_tokens(
        errors,
        DOC_REL,
        doc,
        (
            "21-bit byte address",
            "12-bit byte offset",
            "4'b1111",
            "Maximum outstanding transactions | 1",
            "`2'b00` | `OKAY`",
            "`2'b10` | `SLVERR`",
            "`2'b11` | `DECODEERROR`",
            "An error read always returns",
            "read response channel wins",
            "Address classification owns the response-code precedence",
            "local_reject_pulse_o",
            "one cycle after request acceptance",
            "source-connected",
            "raw HPS",
            "AXI-to-Avalon",
            "platform_designer_wrapper.sv",
            "system.sopcinfo",
            "no functional testbench or behavioral verification result",
            "structural/source-consistency gate only",
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    errors: list[str] = []
    contract = load_json(root, CONTRACT_REL, errors)
    schema = load_json(root, SCHEMA_REL, errors)
    if contract:
        check_contract(root, contract, errors)
    if schema and contract:
        check_schema(schema, contract, errors)
    check_rtl(root, errors)
    check_top_chain(root, errors)
    check_filelists(root, errors)
    check_step4_parity(root, errors)
    check_document(root, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"check_csr_adapter: FAIL ({len(errors)} errors)", file=sys.stderr)
        return 1

    if not args.quiet:
        optional = " + jsonschema" if jsonschema is not None else ""
        print(
            "check_csr_adapter: OK "
            f"(Step-5 source contract, RTL sha256={EXPECTED_RTL_SHA256}{optional}; "
            "no functional/compile/hardware claim)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
