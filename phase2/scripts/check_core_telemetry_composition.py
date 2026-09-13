#!/usr/bin/env python3
"""Check the Step-8 core plus telemetry composition source contract.

This gate validates checked-in JSON, source structure, ownership, and generated
filelist separation without third-party dependencies.  It is not an RTL
compiler, simulation, synthesis, timing, Quartus, or hardware-signoff result.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    import jsonschema  # type: ignore[import-not-found]
except ImportError:
    jsonschema = None  # type: ignore[assignment]


CONTRACT_REL = Path("config/boards/core_telemetry_composition.json")
SCHEMA_REL = Path("spec/schemas/core_telemetry_composition.schema.json")
DOC_REL = Path("docs/architecture/core_telemetry_composition.md")
COMPOSITION_REL = Path("rtl/top/trecap_core_telemetry_top.sv")
CORE_REL = Path("rtl/core/trecap_core_top.sv")
TELEMETRY_REL = Path("rtl/telemetry/trecap_telemetry_top.sv")
WAVE_REL = Path("rtl/telemetry/trecap_wave_packetizer.sv")
SPEC_REL = Path("rtl/telemetry/trecap_spec_packetizer.sv")
METRICS_REL = Path("rtl/telemetry/trecap_metrics_packetizer.sv")
STATUS_REL = Path("rtl/telemetry/trecap_status_packetizer.sv")
SCHEDULER_REL = Path("rtl/telemetry/trecap_packet_scheduler.sv")
FIFO_REL = Path("rtl/telemetry/trecap_packet_fifo.sv")
SOURCE_CORE_REL = Path("rtl/top/trecap_source_core_integration.sv")
BOARD_TRANSPORT_REL = Path("rtl/top/trecap_de1soc_full_top.sv")
BOARD_TOP_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
HPS_BRIDGE_REL = Path("rtl/hps_bridge/trecap_hps_bridge_top.sv")
PURE_TELEMETRY_FILELIST_REL = Path("filelists/rtl_telemetry.f")
COMPOSED_FILELIST_REL = Path("filelists/rtl_core_telemetry.f")

EXPECTED_TOP_LEVEL = {
    "schema": "trecap_phase2_core_telemetry_composition_v1",
    "file_class": "[1] hand-written Step-8 composition contract",
    "project": "T_RECAP_Phase2",
    "board": "de1soc",
    "contract_stage": "step8_core_telemetry_composition_source_implemented",
    "status": (
        "source_implemented_pending_rtl_compile_functional_verification_"
        "quartus_and_hardware_evidence"
    ),
}

EXPECTED_IMPLEMENTATION_STATE = {
    "composition_rtl_implemented": True,
    "real_core_instantiated": True,
    "telemetry_top_instantiated": True,
    "direct_core_tap_binding": True,
    "pure_telemetry_filelist_separated": True,
    "rtl_compile": False,
    "functional_verification": False,
    "quartus_compile": False,
    "hardware_signoff": False,
}

EXPECTED_OWNERSHIP = {
    "composition_rtl": COMPOSITION_REL.as_posix(),
    "core_rtl": CORE_REL.as_posix(),
    "telemetry_rtl": TELEMETRY_REL.as_posix(),
    "scheduler_rtl": SCHEDULER_REL.as_posix(),
    "packet_fifo_rtl": FIFO_REL.as_posix(),
    "pure_telemetry_filelist": PURE_TELEMETRY_FILELIST_REL.as_posix(),
    "composed_filelist": COMPOSED_FILELIST_REL.as_posix(),
    "board_source_core_rtl": SOURCE_CORE_REL.as_posix(),
    "board_transport_rtl": BOARD_TRANSPORT_REL.as_posix(),
}

EXPECTED_EVIDENCE = {
    "source_checker": "scripts/check_core_telemetry_composition.py",
    "human_document": DOC_REL.as_posix(),
    "schema_file": SCHEMA_REL.as_posix(),
    "default_checker_scope": "source_only",
    "source_check_is_rtl_compile": False,
    "source_check_is_functional_verification": False,
    "source_check_is_quartus_compile": False,
    "source_check_is_hardware_signoff": False,
}

EXPECTED_BIN_BINDINGS = {
    "tap_bin_valid_o": "tap_bin_valid_i",
    "tap_bin_frame_idx_o": "tap_bin_frame_idx_i",
    "tap_bin_idx_o": "tap_bin_idx_i",
    "tap_bin_mag2_o": "tap_bin_mag2_i",
    "tap_bin_mask_o": "tap_bin_mask_i",
    "tap_bin_eligible_o": "tap_bin_eligible_i",
    "tap_bin_last_o": "tap_bin_last_i",
}

EXPECTED_OVERFLOW_OWNERSHIP = {
    "csr_visible_sticky_owner": "trecap_core_telemetry_top.telemetry_overflow_flags_q",
    "w1c_clear_input": "clear_telemetry_flags_w1c_i",
    "set_interface_semantics": "one_cycle_new_fault_event_bitmask",
    "sticky_update_rule": "next=(current&~w1c_clear)|new_fault_events",
    "sticky_level_as_set_source_permitted": False,
    "packet_fifo_set_source": "packet_fifo_drop_pulse_o",
    "packet_fifo_sticky_status": "packet_fifo_overflow_o",
    "packet_fifo_sticky_directly_orred_into_set": False,
    "scheduler_malformed_set_source": "scheduler_illegal_drop_o",
    "w1c_rearms_new_fault_detection": True,
    "w1c_manufactures_event_from_persistent_level": False,
    "fifo_sticky_exposed_separately": True,
    "combined_status_ors_independently_owned_flags": True,
    "external_and_core_sticky_clear_at_their_owners": True,
}

EXPECTED_TELEMETRY_SOFT_CLEAR = {
    "request": "telemetry_soft_reset_i",
    "clock_domain": "clk",
    "semantics": "synchronous_formatter_scheduler_fifo_clear",
    "derived_async_reset_permitted": False,
    "child_rst_n_source": "rst_n",
    "packetizer_clear_port": "formatter_reset_i",
    "scheduler_clear_port": "formatter_reset_i",
    "fifo_clear_port": "flush_i",
    "admission_during_clear_permitted": False,
    "core_state_affected": False,
    "soft_clear_preserves_metrics_aggregates": True,
    "metrics_aggregate_clear_source": "metrics_clear_i",
}


class CheckFailure(RuntimeError):
    """Raised when the checked-in Step-8 source contract is inconsistent."""


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckFailure(f"cannot read valid JSON from {path}: {exc}") from exc


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckFailure(f"cannot read {path}: {exc}") from exc


def strip_sv_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\r\n]*", "", text)


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CheckFailure(f"{context} differs from the frozen Step-8 value")


def require_token(text: str, token: str, context: str) -> None:
    if token not in text:
        raise CheckFailure(f"{context}: required source token is missing: {token}")


def forbid_token(text: str, token: str, context: str) -> None:
    if token in text:
        raise CheckFailure(f"{context}: forbidden source token is present: {token}")


def resolve_local_ref(schema_root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise CheckFailure(f"fallback schema validator does not support external $ref: {ref}")
    value: Any = schema_root
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise CheckFailure(f"schema contains an unresolved local $ref: {ref}")
        value = value[part]
    if not isinstance(value, dict):
        raise CheckFailure(f"schema $ref does not resolve to an object: {ref}")
    return value


def matches_json_type(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "null":
        return value is None
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise CheckFailure(f"fallback schema validator does not support type {type_name!r}")


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
        raise CheckFailure(f"{location}: value is outside schema enum")

    declared_type = schema.get("type")
    if declared_type is not None:
        type_names = declared_type if isinstance(declared_type, list) else [declared_type]
        if not any(matches_json_type(value, str(item)) for item in type_names):
            raise CheckFailure(f"{location}: value does not match schema type {declared_type!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise CheckFailure(f"{location}: missing required properties {missing}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise CheckFailure(f"{location}: unexpected properties {extras}")
        for name, child_schema in properties.items():
            if name in value:
                validate_schema_fallback(
                    value[name], child_schema, schema_root, f"{location}.{name}"
                )

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and len(value) < int(minimum):
            raise CheckFailure(f"{location}: list has fewer than {minimum} items")
        if maximum is not None and len(value) > int(maximum):
            raise CheckFailure(f"{location}: list has more than {maximum} items")
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(canonical) != len(set(canonical)):
                raise CheckFailure(f"{location}: list items are not unique")
        child_schema = schema.get("items")
        if isinstance(child_schema, dict):
            for index, item in enumerate(value):
                validate_schema_fallback(item, child_schema, schema_root, f"{location}[{index}]")

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < int(minimum):
            raise CheckFailure(f"{location}: string is shorter than {minimum}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(str(pattern), value) is None:
            raise CheckFailure(f"{location}: string does not match schema pattern {pattern!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise CheckFailure(f"{location}: number is below schema minimum {minimum}")
        if maximum is not None and value > maximum:
            raise CheckFailure(f"{location}: number is above schema maximum {maximum}")


def validate_contract_schema(contract: Any, schema: Any) -> str:
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        raise CheckFailure("contract and schema roots must both be JSON objects")
    if jsonschema is not None:
        try:
            jsonschema.Draft202012Validator(schema).validate(contract)
        except Exception as exc:
            raise CheckFailure(f"contract does not validate against schema: {exc}") from exc
        return "jsonschema"
    validate_schema_fallback(contract, schema, schema)
    return "dependency_free_fallback"


def find_matching_paren(text: str, open_index: int) -> int:
    if open_index >= len(text) or text[open_index] != "(":
        raise CheckFailure("internal parser expected an opening parenthesis")
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    raise CheckFailure("unterminated parenthesized SystemVerilog construct")


def skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def parse_instances(text: str, module_name: str) -> list[tuple[str, str]]:
    """Return (instance_name, named-port-body) for a module type."""
    clean = strip_sv_comments(text)
    instances: list[tuple[str, str]] = []
    for match in re.finditer(rf"\b{re.escape(module_name)}\b", clean):
        index = skip_space(clean, match.end())
        if index < len(clean) and clean[index] == "#":
            index = skip_space(clean, index + 1)
            if index >= len(clean) or clean[index] != "(":
                continue
            index = skip_space(clean, find_matching_paren(clean, index) + 1)
        name_match = re.match(r"[A-Za-z_][A-Za-z0-9_$]*", clean[index:])
        if name_match is None:
            continue
        instance_name = name_match.group(0)
        index = skip_space(clean, index + len(instance_name))
        if index >= len(clean) or clean[index] != "(":
            continue
        close_index = find_matching_paren(clean, index)
        instances.append((instance_name, clean[index + 1 : close_index]))
    return instances


def parse_named_ports(body: str) -> dict[str, str]:
    ports: dict[str, str] = {}
    index = 0
    while index < len(body):
        dot = body.find(".", index)
        if dot < 0:
            break
        name_match = re.match(r"\.([A-Za-z_][A-Za-z0-9_$]*)", body[dot:])
        if name_match is None:
            index = dot + 1
            continue
        port_name = name_match.group(1)
        open_index = skip_space(body, dot + len(name_match.group(0)))
        if open_index >= len(body) or body[open_index] != "(":
            index = open_index
            continue
        close_index = find_matching_paren(body, open_index)
        expression = re.sub(r"\s+", "", body[open_index + 1 : close_index])
        if port_name in ports:
            raise CheckFailure(f"duplicate named port .{port_name} in instance")
        ports[port_name] = expression
        index = close_index + 1
    return ports


def one_instance(text: str, module_name: str, expected_name: str, context: str) -> dict[str, str]:
    instances = parse_instances(text, module_name)
    if len(instances) != 1:
        raise CheckFailure(
            f"{context}: found {len(instances)} {module_name} instances; expected exactly one"
        )
    instance_name, body = instances[0]
    if instance_name != expected_name:
        raise CheckFailure(
            f"{context}: {module_name} instance is {instance_name}; expected {expected_name}"
        )
    return parse_named_ports(body)


def validate_contract_values(contract: dict[str, Any]) -> None:
    for name, expected in EXPECTED_TOP_LEVEL.items():
        require_equal(contract.get(name), expected, f"contract.{name}")
    require_equal(
        contract.get("implementation_state"),
        EXPECTED_IMPLEMENTATION_STATE,
        "contract.implementation_state",
    )
    require_equal(contract.get("source_ownership"), EXPECTED_OWNERSHIP, "contract.source_ownership")
    require_equal(contract.get("evidence_policy"), EXPECTED_EVIDENCE, "contract.evidence_policy")

    tap_mapping = contract.get("tap_mapping")
    if not isinstance(tap_mapping, dict):
        raise CheckFailure("contract.tap_mapping must be an object")
    unique_bin = tap_mapping.get("unique_bin")
    if not isinstance(unique_bin, dict):
        raise CheckFailure("contract.tap_mapping.unique_bin must be an object")
    require_equal(
        unique_bin.get("bindings"), EXPECTED_BIN_BINDINGS, "contract.tap_mapping.unique_bin.bindings"
    )

    packets = contract.get("packet_contract", {}).get("packets")
    if not isinstance(packets, dict) or set(packets) != {
        "WAVE",
        "SPEC64",
        "SPEC129",
        "METRICS",
        "STATUS",
    }:
        raise CheckFailure("contract.packet_contract.packets must freeze five implemented modes")
    require_equal(
        [packets[name]["priority"] for name in ("WAVE", "SPEC64", "SPEC129", "METRICS", "STATUS")],
        [0, 1, 1, 2, 3],
        "contract packet priorities",
    )

    drop_contract = contract.get("non_stalling_drop_contract")
    if not isinstance(drop_contract, dict):
        raise CheckFailure("contract.non_stalling_drop_contract must be an object")
    require_equal(
        drop_contract.get("observation_epoch_reset_action"),
        "suppress_new_admission_discard_partial_collection_drain_unselected_candidates_and_finish_selected_record",
        "contract.non_stalling_drop_contract.observation_epoch_reset_action",
    )
    require_equal(
        drop_contract.get("disabled_or_illegal_drain_latched_until_record_last"),
        True,
        "contract.non_stalling_drop_contract.disabled_or_illegal_drain_latched_until_record_last",
    )
    require_equal(
        drop_contract.get("observation_epoch_reset_resets_packet_fifo"),
        False,
        "contract.non_stalling_drop_contract.observation_epoch_reset_resets_packet_fifo",
    )
    require_equal(
        drop_contract.get("observation_epoch_reset_retracts_started_record"),
        False,
        "contract.non_stalling_drop_contract.observation_epoch_reset_retracts_started_record",
    )

    boundaries = contract.get("metrics_status_boundary_contract")
    if not isinstance(boundaries, dict):
        raise CheckFailure("contract.metrics_status_boundary_contract must be an object")
    for key in (
        "tap_frame_valid_is_config_boundary",
        "status_tick_is_config_boundary",
        "metrics_tick_is_config_boundary",
        "telemetry_soft_reset_affects_core",
        "status_reconstructs_counts_from_tap_indices",
        "snapshot_packets_are_exact_completion_evidence",
    ):
        require_equal(boundaries.get(key), False, f"contract.metrics_status_boundary_contract.{key}")
    require_equal(
        boundaries.get("board_metrics_clear_core_and_telemetry_same_event"),
        True,
        "contract.metrics_status_boundary_contract.board_metrics_clear_core_and_telemetry_same_event",
    )
    require_equal(
        boundaries.get("source_discontinuity_clears_both_metric_owners"),
        True,
        "contract.metrics_status_boundary_contract.source_discontinuity_clears_both_metric_owners",
    )
    require_equal(
        boundaries.get("standalone_metrics_epoch_reset_sources"),
        ["clear_metrics_w1p", "datapath_clear", "core_disable", "source_discontinuity"],
        "contract.metrics_status_boundary_contract.standalone_metrics_epoch_reset_sources",
    )

    composition = contract.get("composition_contract")
    if not isinstance(composition, dict):
        raise CheckFailure("contract.composition_contract must be an object")
    require_equal(
        composition.get("unique_bin_index_width_parameter_propagated"),
        True,
        "contract.composition_contract.unique_bin_index_width_parameter_propagated",
    )

    require_equal(
        contract.get("overflow_ownership_contract"),
        EXPECTED_OVERFLOW_OWNERSHIP,
        "contract.overflow_ownership_contract",
    )
    require_equal(
        contract.get("telemetry_soft_clear_contract"),
        EXPECTED_TELEMETRY_SOFT_CLEAR,
        "contract.telemetry_soft_clear_contract",
    )

    rules = contract.get("validation_rules")
    if not isinstance(rules, list) or len(rules) < 16:
        raise CheckFailure("contract.validation_rules must contain at least sixteen rules")


def require_same_binding(
    producer_ports: dict[str, str],
    producer_port: str,
    consumer_ports: dict[str, str],
    consumer_port: str,
) -> None:
    producer_signal = producer_ports.get(producer_port)
    consumer_signal = consumer_ports.get(consumer_port)
    if producer_signal is None or consumer_signal is None:
        raise CheckFailure(
            f"composition: missing tap binding {producer_port} -> {consumer_port}"
        )
    if producer_signal != consumer_signal:
        raise CheckFailure(
            f"composition: {producer_port} binds {producer_signal}, but {consumer_port} binds "
            f"{consumer_signal}"
        )


def validate_composition_source(text: str) -> None:
    clean = strip_sv_comments(text)
    compact = re.sub(r"\s+", "", clean)
    require_token(clean, "module trecap_core_telemetry_top", "composition RTL")
    core_ports = one_instance(text, "trecap_core_top", "u_core", "composition RTL")
    telemetry_ports = one_instance(
        text, "trecap_telemetry_top", "u_telemetry", "composition RTL"
    )
    require_token(
        compact,
        ".BIN_IDX_W(BIN_IDX_W)",
        "composition RTL telemetry parameter binding",
    )

    for port in (
        "sample_i",
        "sample_valid_i",
        "sample_ready_o",
        "y_valid_o",
        "y_ready_i",
        "y_sample_o",
        "y_data_o",
        "y_sample_idx_o",
        "frame_boundary_pulse_o",
        "core_busy_o",
        "clear_metrics_i",
    ):
        if port not in core_ports:
            raise CheckFailure(f"composition RTL: u_core omits required port .{port}")

    if "record_ready_i" in core_ports.values() or "record_ready_i" in "".join(core_ports.values()):
        raise CheckFailure("composition RTL: record_ready_i reaches u_core")
    if "record_ready_i" not in telemetry_ports.values():
        raise CheckFailure("composition RTL: record_ready_i does not terminate in telemetry")
    if core_ports["sample_ready_o"] == "record_ready_i":
        raise CheckFailure("composition RTL: sample_ready_o is incorrectly owned by record_ready_i")
    if core_ports["y_ready_i"] == "record_ready_i":
        raise CheckFailure("composition RTL: y_ready_i is incorrectly owned by record_ready_i")

    require_same_binding(core_ports, "tap_sample_o", telemetry_ports, "tap_sample_i")
    require_same_binding(core_ports, "tap_frame_o", telemetry_ports, "tap_frame_i")
    require_same_binding(
        core_ports, "core_sample_count_o", telemetry_ports, "core_sample_count_i"
    )
    require_same_binding(
        core_ports, "core_frame_count_o", telemetry_ports, "core_frame_count_i"
    )
    require_equal(
        telemetry_ports.get("metrics_clear_i"),
        "metrics_epoch_clear_w",
        "composition RTL shared metric-epoch clear binding",
    )
    require_equal(
        telemetry_ports.get("observation_epoch_reset_i"),
        "source_discontinuity_i||clear_i||!enable_i",
        "composition RTL observation-epoch reset binding",
    )
    require_equal(
        telemetry_ports.get("telemetry_soft_reset_i"),
        "telemetry_soft_reset_i",
        "composition RTL telemetry soft-reset binding",
    )
    require_equal(
        telemetry_ports.get("formatter_flush_i"),
        "source_discontinuity_i||clear_i||!enable_i",
        "composition RTL formatter-flush binding",
    )
    require_equal(
        telemetry_ports.get("counter_clear_i"),
        "1'b0",
        "composition RTL separate transport-counter clear binding",
    )
    require_token(
        compact,
        "assignmetrics_epoch_clear_w=ctrl_i.clear_metrics_w1p||clear_i||!enable_i||source_discontinuity_i;",
        "composition RTL metric-epoch reset sources",
    )
    for producer_port, consumer_port in EXPECTED_BIN_BINDINGS.items():
        require_same_binding(core_ports, producer_port, telemetry_ports, consumer_port)

    # The old shell accepted taps from an external core.  Step 8 must remove that ambiguity.
    for forbidden_input in (
        r"\binput\s+trecap_core_tap_sample_t\s+tap_sample_i\b",
        r"\binput\s+trecap_core_tap_frame_t\s+tap_frame_i\b",
        r"\binput\s+logic\s+tap_bin_valid_i\b",
    ):
        if re.search(forbidden_input, clean):
            raise CheckFailure(
                "composition RTL: legacy external-core tap input remains in the public interface"
            )

    for forbidden_owner in (
        "trecap_packet_fifo",
        "trecap_packet_scheduler",
        "trecap_ddr_ring_writer",
        "platform_designer_wrapper",
    ):
        if parse_instances(text, forbidden_owner):
            raise CheckFailure(
                f"composition RTL: {forbidden_owner} is owned by another layer and must not be instantiated"
            )

    # Soft-reset may reset telemetry only.  Its expression must not drive any u_core reset/clear.
    for port in ("rst_n", "clear_i", "clear_sticky_i", "clear_metrics_i"):
        if "telemetry_soft_reset_i" in core_ports.get(port, ""):
            raise CheckFailure(
                f"composition RTL: telemetry_soft_reset_i illegally drives u_core.{port}"
            )

    require_token(
        compact,
        "(telemetry_overflow_flags_q&~clear_telemetry_flags_w1c_i)|telemetry_overflow_set_w",
        "composition RTL W1C sticky update",
    )
    require_token(
        compact,
        "if(packet_fifo_drop_pulse_o)",
        "composition RTL packet-FIFO new-fault set path",
    )
    require_token(
        compact,
        "telemetry_config_illegal_q<=telemetry_config_illegal_o;",
        "composition RTL illegal-config fault-episode history",
    )
    for forbidden in (
        "if(packet_fifo_overflow_o)",
        "if(packet_fifo_drop_pulse_o||packet_fifo_overflow_o)",
        "if(packet_fifo_overflow_o||packet_fifo_drop_pulse_o)",
    ):
        forbid_token(compact, forbidden, "composition RTL W1C packet-FIFO set path")


def validate_telemetry_ownership(text: str) -> None:
    compact = re.sub(r"\s+", "", strip_sv_comments(text))
    require_token(compact, "parameterintunsignedBIN_IDX_W=", "telemetry RTL parameter API")
    require_token(compact, "logic[BIN_IDX_W-1:0]tap_bin_idx_i", "telemetry RTL bin-index API")
    require_token(
        compact,
        "inputlogicobservation_epoch_reset_i",
        "telemetry RTL observation-epoch reset API",
    )
    require_token(
        compact,
        "inputlogicformatter_flush_i",
        "telemetry RTL formatter-flush API",
    )
    require_token(
        compact,
        "inputlogiccounter_clear_i",
        "telemetry RTL separate transport-counter clear API",
    )
    require_token(
        compact,
        "assignformatter_reset=telemetry_soft_reset_i||formatter_flush_i;",
        "telemetry RTL unified synchronous formatter reset",
    )
    require_token(
        compact,
        "assigntelemetry_admit_enable=telemetry_runtime_enable&&!telemetry_soft_reset_i&&!observation_epoch_reset_i;",
        "telemetry RTL synchronous soft-clear and observation-epoch admission gate",
    )
    require_token(
        compact,
        "assigndrop_events=formatter_reset?13'd0:",
        "telemetry RTL formatter-reset drop-accounting suppression",
    )
    require_token(
        compact,
        "if(counter_clear_i)begin",
        "telemetry RTL separate transport-counter clear state transition",
    )
    if compact.count(".enable_i(telemetry_admit_enable&&") != 4:
        raise CheckFailure(
            "telemetry RTL: all four packetizers must use the observation-epoch admission gate"
        )
    require_token(
        compact,
        ".telemetry_enable_i(telemetry_admit_enable)",
        "telemetry RTL scheduler observation-epoch gate",
    )
    if parse_instances(text, "trecap_core_top"):
        raise CheckFailure("telemetry RTL: pure telemetry layer illegally instantiates the core")
    wave_ports = one_instance(
        text, "trecap_wave_packetizer", "u_wave_packetizer", "telemetry RTL"
    )
    spec_ports = one_instance(
        text, "trecap_spec_packetizer", "u_spec_packetizer", "telemetry RTL"
    )
    metrics_ports = one_instance(
        text, "trecap_metrics_packetizer", "u_metrics_packetizer", "telemetry RTL"
    )
    status_ports = one_instance(
        text, "trecap_status_packetizer", "u_status_packetizer", "telemetry RTL"
    )
    require_equal(
        status_ports.get("core_sample_count_i"),
        "core_sample_count_i",
        "telemetry RTL u_status_packetizer.core_sample_count_i",
    )
    require_equal(
        status_ports.get("core_frame_count_i"),
        "core_frame_count_i",
        "telemetry RTL u_status_packetizer.core_frame_count_i",
    )
    scheduler_ports = one_instance(
        text, "trecap_packet_scheduler", "u_packet_scheduler", "telemetry RTL"
    )
    fifo_ports = one_instance(text, "trecap_packet_fifo", "u_packet_fifo", "telemetry RTL")

    for instance_name, ports in (
        ("u_wave_packetizer", wave_ports),
        ("u_spec_packetizer", spec_ports),
        ("u_metrics_packetizer", metrics_ports),
        ("u_status_packetizer", status_ports),
        ("u_packet_scheduler", scheduler_ports),
        ("u_packet_fifo", fifo_ports),
    ):
        require_equal(
            ports.get("rst_n"),
            "rst_n",
            f"telemetry RTL {instance_name} canonical reset binding",
        )
        if "telemetry_soft_reset_i" in ports.get("rst_n", ""):
            raise CheckFailure(
                f"telemetry RTL: telemetry_soft_reset_i illegally derives {instance_name}.rst_n"
            )

    for instance_name, ports in (
        ("u_wave_packetizer", wave_ports),
        ("u_spec_packetizer", spec_ports),
        ("u_metrics_packetizer", metrics_ports),
        ("u_status_packetizer", status_ports),
        ("u_packet_scheduler", scheduler_ports),
    ):
        require_equal(
            ports.get("formatter_reset_i"),
            "formatter_reset",
            f"telemetry RTL {instance_name} unified formatter-reset binding",
        )
    require_equal(
        fifo_ports.get("flush_i"),
        "formatter_reset",
        "telemetry RTL u_packet_fifo unified formatter flush binding",
    )

    for forbidden in (
        "logictelemetry_rst_n",
        "assigntelemetry_rst_n",
        "soft_reset_q",
        "rst_n&&!telemetry_soft_reset_i",
        "rst_n&~telemetry_soft_reset_i",
    ):
        forbid_token(compact, forbidden, "telemetry RTL derived-reset architecture")
    expected_output_bindings = {
        "out_valid_o": "record_valid_o",
        "out_ready_i": "record_ready_i",
        "out_meta_o": "record_meta_o",
        "out_payload_data_o": "record_payload_data_o",
        "out_payload_keep_o": "record_payload_keep_o",
        "out_payload_last_o": "record_payload_last_o",
    }
    for port, signal in expected_output_bindings.items():
        require_equal(fifo_ports.get(port), signal, f"telemetry RTL u_packet_fifo.{port}")


def validate_scheduler_source(text: str) -> None:
    clean = strip_sv_comments(text)
    compact = re.sub(r"\s+", "", clean)
    for token in (
        "TCSR_PACKET_ENABLE_WAVE_EN_MASK",
        "TCSR_PACKET_ENABLE_SPEC_EN_MASK",
        "TCSR_PACKET_ENABLE_METRICS_EN_MASK",
        "TCSR_PACKET_ENABLE_STATUS_EN_MASK",
        "TSPEC_DISABLED",
        "TSPEC_SPEC64",
        "TSPEC_SPEC129",
        "TPKT_WAVE",
        "TPKT_SPEC64",
        "TPKT_SPEC129",
        "TPKT_METRICS",
        "TPKT_STATUS",
        "disabled_candidate_drop_o",
        "illegal_candidate_drop_o",
        "disabled_drain_q",
        "illegal_drain_q",
        "disabled_start_w",
        "illegal_start_w",
    ):
        require_token(clean, token, "packet scheduler RTL")
    require_token(
        compact,
        "inputlogicformatter_reset_i",
        "packet scheduler synchronous formatter-clear API",
    )
    require_token(
        compact,
        "elseif(formatter_reset_i)begin",
        "packet scheduler synchronous formatter-clear state transition",
    )
    forbid_token(
        compact,
        "ornegedgeformatter_reset_i",
        "packet scheduler derived asynchronous reset",
    )


def validate_fifo_source(text: str) -> None:
    clean = strip_sv_comments(text)
    compact = re.sub(r"\s+", "", clean)
    for token in (
        "trecap_priority_dropper",
        "dropper_evict_valid",
        "dropper_drop_incoming",
        "resident_evictable",
        "out_ready_i",
        "out_payload_last_o",
    ):
        require_token(clean, token, "packet FIFO RTL")
    require_token(compact, "inputlogicflush_i", "packet FIFO synchronous flush API")
    require_token(
        compact,
        "elseif(flush_i)begin",
        "packet FIFO synchronous flush state transition",
    )
    forbid_token(compact, "ornegedgeflush_i", "packet FIFO derived asynchronous reset")


def validate_packetizer_soft_clear_source(text: str, relative: Path) -> None:
    compact = re.sub(r"\s+", "", strip_sv_comments(text))
    require_token(
        compact,
        "inputlogicformatter_reset_i",
        f"{relative} synchronous formatter-clear API",
    )
    require_token(
        compact,
        "if(formatter_reset_i)begin",
        f"{relative} synchronous formatter-clear state transition",
    )
    forbid_token(
        compact,
        "ornegedgeformatter_reset_i",
        f"{relative} derived asynchronous reset",
    )


def active_filelist_entries(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "+"))
    ]


def validate_filelists(pure_text: str, composed_text: str) -> None:
    pure = active_filelist_entries(pure_text)
    composed = active_filelist_entries(composed_text)

    require_token("\n".join(pure), TELEMETRY_REL.as_posix(), "pure telemetry filelist")
    if COMPOSITION_REL.as_posix() in pure:
        raise CheckFailure("pure telemetry filelist contains the core+telemetry composition wrapper")
    core_entries = [entry for entry in pure if entry.startswith("rtl/core/") or entry.startswith("rtl/fft/")]
    if core_entries:
        raise CheckFailure(f"pure telemetry filelist contains core/FFT entries: {core_entries}")

    for required in (CORE_REL.as_posix(), TELEMETRY_REL.as_posix(), COMPOSITION_REL.as_posix()):
        if required not in composed:
            raise CheckFailure(f"composed filelist is missing {required}")
    if composed.index(CORE_REL.as_posix()) > composed.index(COMPOSITION_REL.as_posix()):
        raise CheckFailure("composed filelist orders trecap_core_top after the composition wrapper")
    if composed.index(TELEMETRY_REL.as_posix()) > composed.index(COMPOSITION_REL.as_posix()):
        raise CheckFailure("composed filelist orders trecap_telemetry_top after the composition wrapper")


def validate_board_binding(
    source_core_text: str,
    board_transport_text: str,
    board_top_text: str,
    hps_bridge_text: str,
) -> None:
    source_core_instances = parse_instances(source_core_text, "trecap_core_top")
    if len(source_core_instances) != 1:
        raise CheckFailure(
            "DE1-SoC source/core layer must remain the sole board-path trecap_core_top owner"
        )
    if parse_instances(board_transport_text, "trecap_core_telemetry_top"):
        raise CheckFailure(
            "DE1-SoC transport path instantiates the composed wrapper behind an existing core"
        )
    telemetry_instances = parse_instances(board_transport_text, "trecap_telemetry_top")
    if len(telemetry_instances) != 1:
        raise CheckFailure(
            "DE1-SoC transport path must instantiate exactly one pure trecap_telemetry_top"
        )
    board_transport_compact = re.sub(r"\s+", "", strip_sv_comments(board_transport_text))
    require_token(
        board_transport_compact,
        ".BIN_IDX_W(BIN_IDX_W)",
        "DE1-SoC telemetry parameter binding",
    )
    require_token(
        board_transport_compact,
        "telemetry_config_illegal_prior_q<=telemetry_config_illegal_o;",
        "DE1-SoC illegal-config fault-episode history",
    )
    require_token(
        board_transport_compact,
        "assigntelemetry_soft_clear_w=telemetry_soft_reset_pulse_w|external_transport_clear_i;",
        "DE1-SoC telemetry soft-reset ownership",
    )
    require_token(
        board_transport_compact,
        "assignformatter_flush_w=transport_epoch_idle_q&&(external_telemetry_flush_i||(source_discontinuity_i&&source_mode_apply_pulse_w));",
        "DE1-SoC quiescent formatter-flush ownership",
    )
    require_token(
        board_transport_compact,
        "assigntransport_epoch_idle_o=writer_idle_o&&!record_valid_w;",
        "DE1-SoC formatter-flush quiescence proof",
    )
    telemetry_ports = parse_named_ports(telemetry_instances[0][1])
    require_equal(
        telemetry_ports.get("telemetry_soft_reset_i"),
        "telemetry_soft_clear_w",
        "DE1-SoC telemetry soft-reset binding",
    )
    require_equal(
        telemetry_ports.get("formatter_flush_i"),
        "formatter_flush_w",
        "DE1-SoC telemetry formatter-flush binding",
    )
    require_equal(
        telemetry_ports.get("counter_clear_i"),
        "counter_clear_pulse_w",
        "DE1-SoC telemetry separate transport-counter clear binding",
    )
    require_equal(
        telemetry_ports.get("metrics_clear_i"),
        "clear_metrics_apply_pulse_i",
        "DE1-SoC telemetry safe metrics-clear binding",
    )
    require_equal(
        telemetry_ports.get("observation_epoch_reset_i"),
        "source_discontinuity_i",
        "DE1-SoC telemetry observation-epoch reset binding",
    )

    source_core_compact = re.sub(r"\s+", "", strip_sv_comments(source_core_text))
    require_token(
        source_core_compact,
        "assignclear_metrics_apply_pulse_o=core_clear_metrics_w||source_discontinuity_pulse_o;",
        "source/core safe metrics-clear output",
    )
    core_ports = parse_named_ports(source_core_instances[0][1])
    require_equal(
        core_ports.get("clear_metrics_i"),
        "core_clear_metrics_w",
        "source/core mathematical-core metrics-clear binding",
    )

    board_source_ports = one_instance(
        board_top_text,
        "trecap_source_core_integration",
        "u_source_core_integration",
        "DE1-SoC physical top",
    )
    board_full_ports = one_instance(
        board_top_text,
        "trecap_de1soc_full_top",
        "u_full_top",
        "DE1-SoC physical top",
    )
    require_equal(
        board_source_ports.get("clear_metrics_apply_pulse_o"),
        "core_clear_metrics_apply_pulse",
        "DE1-SoC source/core applied metrics-clear output",
    )
    require_equal(
        board_full_ports.get("clear_metrics_apply_pulse_i"),
        "core_clear_metrics_apply_pulse",
        "DE1-SoC transport applied metrics-clear input",
    )
    require_equal(
        board_full_ports.get("source_discontinuity_i"),
        "source_discontinuity",
        "DE1-SoC observation-epoch reset path",
    )
    require_equal(
        board_full_ports.get("external_telemetry_flush_i"),
        "replay_start_accept",
        "DE1-SoC admitted-replay formatter-flush request",
    )
    require_equal(
        board_full_ports.get("counter_clear_pulse_o"),
        "csr_counter_clear",
        "DE1-SoC separate transport-counter clear output",
    )
    require_equal(
        board_source_ports.get("clear_metrics_pulse_i"),
        board_full_ports.get("clear_metrics_pulse_o"),
        "DE1-SoC raw metrics-clear request loop",
    )

    hps_compact = re.sub(r"\s+", "", strip_sv_comments(hps_bridge_text))
    require_token(
        hps_compact,
        "writer_overflow_flags_seen_q<=writer_overflow_flags_set;",
        "HPS writer overflow episode re-arm",
    )
    forbid_token(
        hps_compact,
        "writer_overflow_flags_seen_q<=writer_overflow_flags_seen_q|writer_overflow_flags_set;",
        "HPS writer overflow permanent seen history",
    )


def validate_document(text: str) -> None:
    lowered = re.sub(r"\s+", " ", text.lower())
    for token in (
        "step 8",
        "tap mapping",
        "packet modes",
        "non-stalling",
        "drop",
        "safe boundary",
        "clear_metrics_apply_pulse_o",
        "fifo output ownership",
        "source-only",
        "not functional verification",
    ):
        if token not in lowered:
            raise CheckFailure(f"architecture document is missing required topic: {token}")


def check_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise CheckFailure(f"cannot stat checker script {path}: {exc}") from exc
    if not (mode & stat.S_IXUSR):
        raise CheckFailure(f"checker script is not executable: {path}")


def run_checks(repo_root: Path) -> dict[str, Any]:
    contract_path = repo_root / CONTRACT_REL
    schema_path = repo_root / SCHEMA_REL
    doc_path = repo_root / DOC_REL
    composition_path = repo_root / COMPOSITION_REL
    telemetry_path = repo_root / TELEMETRY_REL
    wave_path = repo_root / WAVE_REL
    spec_path = repo_root / SPEC_REL
    metrics_path = repo_root / METRICS_REL
    status_path = repo_root / STATUS_REL
    scheduler_path = repo_root / SCHEDULER_REL
    fifo_path = repo_root / FIFO_REL
    source_core_path = repo_root / SOURCE_CORE_REL
    board_transport_path = repo_root / BOARD_TRANSPORT_REL
    board_top_path = repo_root / BOARD_TOP_REL
    hps_bridge_path = repo_root / HPS_BRIDGE_REL
    pure_filelist_path = repo_root / PURE_TELEMETRY_FILELIST_REL
    composed_filelist_path = repo_root / COMPOSED_FILELIST_REL

    contract = load_json(contract_path)
    schema = load_json(schema_path)
    schema_engine = validate_contract_schema(contract, schema)
    validate_contract_values(contract)

    validate_composition_source(read_text(composition_path))
    validate_telemetry_ownership(read_text(telemetry_path))
    for relative, path in (
        (WAVE_REL, wave_path),
        (SPEC_REL, spec_path),
        (METRICS_REL, metrics_path),
        (STATUS_REL, status_path),
    ):
        validate_packetizer_soft_clear_source(read_text(path), relative)
    validate_scheduler_source(read_text(scheduler_path))
    validate_fifo_source(read_text(fifo_path))
    validate_filelists(read_text(pure_filelist_path), read_text(composed_filelist_path))
    validate_board_binding(
        read_text(source_core_path),
        read_text(board_transport_path),
        read_text(board_top_path),
        read_text(hps_bridge_path),
    )
    validate_document(read_text(doc_path))
    check_executable(Path(__file__).resolve())

    return {
        "status": "ok",
        "milestone": "architecture_implementation_step_8",
        "scope": "source_only",
        "schema_validation_engine": schema_engine,
        "composition": COMPOSITION_REL.as_posix(),
        "pure_telemetry_filelist": PURE_TELEMETRY_FILELIST_REL.as_posix(),
        "composed_filelist": COMPOSED_FILELIST_REL.as_posix(),
        "contains_step_8_functional_verification_implementation": False,
        "contains_step_8_rtl_compile_evidence": False,
        "contains_step_8_quartus_compile_evidence": False,
        "contains_step_8_hardware_evidence": False,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repo_root_from_script(),
        help="repository root (default: parent of this script)",
    )
    parser.add_argument("--quiet", action="store_true", help="print only failures")
    parser.add_argument("--print-json", action="store_true", help="print the result as JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = args.repo_root.resolve()
    try:
        result = run_checks(repo_root)
    except CheckFailure as exc:
        print(f"check-core-telemetry-composition: FAIL: {exc}", file=sys.stderr)
        return 1

    if args.print_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif not args.quiet:
        print(
            "check-core-telemetry-composition: OK "
            f"(scope={result['scope']}, schema={result['schema_validation_engine']})"
        )
        print("  real core + telemetry composition: source contract present")
        print("  core taps: direct valid-only mapping; no telemetry ready path")
        print("  packet FIFO/output owner: trecap_telemetry_top.u_packet_fifo")
        print("  pure/composed filelists: ownership separated")
        print("  Step-8 functional verification implementation: false")
        print("  Step-8 RTL compile evidence: false")
        print("  Step-8 Quartus compile evidence: false")
        print("  Step-8 hardware evidence: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
