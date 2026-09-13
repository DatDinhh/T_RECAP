#!/usr/bin/env python3
"""Check the Step-10 DE1-SoC clock/reset source architecture.

This gate is intentionally dependency-free when ``jsonschema`` is unavailable.
It checks committed JSON, RTL structure, Platform Designer source, and SDC intent.
It does not compile RTL, run simulation, generate Platform Designer output, invoke
Quartus/TimeQuest, close timing, or establish hardware behavior.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

try:
    import jsonschema  # type: ignore[import-not-found]
except ImportError:
    jsonschema = None  # type: ignore[assignment]


CONTRACT_REL = Path("config/boards/de1soc_clock_reset_architecture.json")
SCHEMA_REL = Path("spec/schemas/de1soc_clock_reset_architecture.schema.json")
CLOCK_RESET_REL = Path("rtl/platform/de1soc/clock_reset_ctrl.sv")
BOARD_TOP_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
RESET_SYNC_REL = Path("rtl/common/reset_sync.sv")
AUDIO_REL = Path("rtl/platform/de1soc/audio_codec_wrapper.sv")
ADC_REL = Path("rtl/platform/de1soc/adc_wrapper.sv")
PD_WRAPPER_REL = Path("rtl/platform/de1soc/platform_designer_wrapper.sv")
FULL_TOP_REL = Path("rtl/top/trecap_de1soc_full_top.sv")
TELEMETRY_REL = Path("rtl/telemetry/trecap_telemetry_top.sv")
WAVE_PACKETIZER_REL = Path("rtl/telemetry/trecap_wave_packetizer.sv")
SPEC_PACKETIZER_REL = Path("rtl/telemetry/trecap_spec_packetizer.sv")
METRICS_PACKETIZER_REL = Path("rtl/telemetry/trecap_metrics_packetizer.sv")
STATUS_PACKETIZER_REL = Path("rtl/telemetry/trecap_status_packetizer.sv")
PACKET_SCHEDULER_REL = Path("rtl/telemetry/trecap_packet_scheduler.sv")
PACKET_FIFO_REL = Path("rtl/telemetry/trecap_packet_fifo.sv")
HPS_BRIDGE_REL = Path("rtl/hps_bridge/trecap_hps_bridge_top.sv")
PD_TCL_REL = Path("platform/de1soc/qsys/platform_designer.tcl")
QSYS_REL = Path("platform/de1soc/qsys/system.qsys")
PRIMARY_SDC_REL = Path("constraints/de1soc/de1soc.sdc")
CLOCKS_SDC_REL = Path("constraints/de1soc/clocks.sdc")

EXPECTED_TOP_LEVEL = {
    "schema": "trecap_phase2_de1soc_clock_reset_architecture_v1",
    "file_class": "[1] hand-written Step-10 clock/reset architecture contract",
    "project": "T_RECAP_Phase2",
    "board": "de1soc",
    "contract_stage": "step10_clock_reset_architecture_source_implemented",
    "status": (
        "source_implemented_pending_rtl_compile_functional_verification_"
        "platform_designer_generation_quartus_timing_and_hardware_evidence"
    ),
}

EXPECTED_OWNERSHIP = {
    "physical_board_top": BOARD_TOP_REL.as_posix(),
    "clock_reset_controller": CLOCK_RESET_REL.as_posix(),
    "reset_synchronizer": RESET_SYNC_REL.as_posix(),
    "audio_platform_wrapper": AUDIO_REL.as_posix(),
    "adc_platform_wrapper": ADC_REL.as_posix(),
    "telemetry_composition": FULL_TOP_REL.as_posix(),
    "telemetry_owner": TELEMETRY_REL.as_posix(),
    "platform_designer_wrapper": PD_WRAPPER_REL.as_posix(),
    "platform_designer_script": PD_TCL_REL.as_posix(),
    "platform_designer_source": QSYS_REL.as_posix(),
    "primary_constraints": PRIMARY_SDC_REL.as_posix(),
    "supplemental_clock_constraints": CLOCKS_SDC_REL.as_posix(),
}

EXPECTED_EVIDENCE = {
    "source_checker": "scripts/check_de1soc_clock_reset.py",
    "schema_file": SCHEMA_REL.as_posix(),
    "default_checker_scope": "source_only",
    "source_check_is_rtl_compile": False,
    "source_check_is_functional_verification": False,
    "source_check_is_platform_designer_generation": False,
    "source_check_is_quartus_compile": False,
    "source_check_is_timing_closure": False,
    "source_check_is_hardware_signoff": False,
}

SHARED_INSTANCE_BINDINGS = {
    "platform_designer_wrapper": ("u_platform_designer_wrapper", "clk_50_i", "bridge_reset_n_i"),
    "audio_codec_wrapper": ("u_audio_codec_wrapper", "clk", "rst_n"),
    "adc_wrapper": ("u_adc_wrapper", "clk", "rst_n"),
    "trecap_source_core_integration": ("u_source_core_integration", "clk", "rst_n"),
    "trecap_de1soc_full_top": ("u_full_top", "clk", "rst_n"),
}

PSEUDO_DOMAIN_IDENTIFIERS = (
    "clk_core",
    "clk_telemetry",
    "clk_hps_bridge",
    "rst_n_fabric",
    "rst_n_core",
    "rst_n_telemetry",
    "rst_n_hps_bridge",
    "reset_request_n",
)

EVIDENCE_FALSE_KEYS = (
    "rtl_compile",
    "functional_verification",
    "platform_designer_generation",
    "quartus_compile",
    "timing_closure",
    "hardware_signoff",
)


class CheckFailure(RuntimeError):
    """Raised when checked-in Step-10 source violates the frozen contract."""


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


def strip_tcl_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CheckFailure(f"{context} differs from the frozen Step-10 value")


def require_regex(text: str, pattern: str, context: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if match is None:
        raise CheckFailure(f"{context}: required source pattern is missing: {pattern}")
    return match


def forbid_regex(text: str, pattern: str, context: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL):
        raise CheckFailure(f"{context}: forbidden source pattern is present: {pattern}")


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
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "null":
        return value is None
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
        raise CheckFailure(f"{location}: value is not in schema enum")
    expected_type = schema.get("type")
    if expected_type is not None and not matches_json_type(value, str(expected_type)):
        raise CheckFailure(f"{location}: expected JSON type {expected_type}")
    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise CheckFailure(f"{location}: missing required property {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise CheckFailure(f"{location}: unexpected properties: {extra}")
        for key, child in properties.items():
            if key in value and isinstance(child, dict):
                validate_schema_fallback(value[key], child, schema_root, f"{location}.{key}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise CheckFailure(f"{location}: too few array items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise CheckFailure(f"{location}: too many array items")
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(canonical)) != len(canonical):
                raise CheckFailure(f"{location}: array items are not unique")
        child = schema.get("items")
        if isinstance(child, dict):
            for index, item in enumerate(value):
                validate_schema_fallback(item, child, schema_root, f"{location}[{index}]")
    if isinstance(value, str) and len(value) < int(schema.get("minLength", 0)):
        raise CheckFailure(f"{location}: string is shorter than minLength")


def validate_contract_schema(contract: Any, schema: Any, force_fallback: bool) -> str:
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        raise CheckFailure("contract and schema roots must both be JSON objects")
    if jsonschema is not None and not force_fallback:
        try:
            jsonschema.Draft202012Validator(schema).validate(contract)
        except Exception as exc:
            raise CheckFailure(f"contract does not validate against schema: {exc}") from exc
        return "jsonschema"
    validate_schema_fallback(contract, schema, schema)
    return "dependency_free_fallback"


def validate_contract_values(contract: dict[str, Any]) -> None:
    for key, expected in EXPECTED_TOP_LEVEL.items():
        require_equal(contract.get(key), expected, f"contract.{key}")
    require_equal(contract.get("source_ownership"), EXPECTED_OWNERSHIP, "contract.source_ownership")
    require_equal(contract.get("evidence_policy"), EXPECTED_EVIDENCE, "contract.evidence_policy")

    implementation = contract.get("implementation_state")
    if not isinstance(implementation, dict):
        raise CheckFailure("contract.implementation_state must be an object")
    for key in EVIDENCE_FALSE_KEYS:
        require_equal(implementation.get(key), False, f"contract.implementation_state.{key}")

    rates = contract.get("clock_enable_architecture", {}).get("clock_enable_rates_hz")
    require_equal(
        rates,
        {
            "sample_tick_o": 48_000,
            "status_tick_o": 10,
            "metrics_tick_o": 30,
            "heartbeat_toggle_o": 2,
        },
        "contract.clock_enable_architecture.clock_enable_rates_hz",
    )
    rules = contract.get("validation_rules")
    if not isinstance(rules, list) or len(rules) < 12:
        raise CheckFailure("contract.validation_rules must contain at least twelve rules")


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


def parse_named_bindings(body: str) -> dict[str, str]:
    bindings: dict[str, str] = {}
    index = 0
    while index < len(body):
        dot = body.find(".", index)
        if dot < 0:
            break
        match = re.match(r"\.([A-Za-z_][A-Za-z0-9_$]*)", body[dot:])
        if match is None:
            index = dot + 1
            continue
        name = match.group(1)
        open_index = skip_space(body, dot + len(match.group(0)))
        if open_index >= len(body) or body[open_index] != "(":
            index = open_index
            continue
        close_index = find_matching_paren(body, open_index)
        expression = compact(body[open_index + 1 : close_index])
        if name in bindings:
            raise CheckFailure(f"duplicate named binding .{name}")
        bindings[name] = expression
        index = close_index + 1
    return bindings


def parse_instances(
    text: str, module_name: str
) -> list[tuple[str, dict[str, str], dict[str, str]]]:
    clean = strip_sv_comments(text)
    instances: list[tuple[str, dict[str, str], dict[str, str]]] = []
    for match in re.finditer(rf"\b{re.escape(module_name)}\b", clean):
        index = skip_space(clean, match.end())
        parameters: dict[str, str] = {}
        if index < len(clean) and clean[index] == "#":
            index = skip_space(clean, index + 1)
            if index >= len(clean) or clean[index] != "(":
                continue
            close_index = find_matching_paren(clean, index)
            parameters = parse_named_bindings(clean[index + 1 : close_index])
            index = skip_space(clean, close_index + 1)
        name_match = re.match(r"[A-Za-z_][A-Za-z0-9_$]*", clean[index:])
        if name_match is None:
            continue
        instance_name = name_match.group(0)
        index = skip_space(clean, index + len(instance_name))
        if index >= len(clean) or clean[index] != "(":
            continue
        close_index = find_matching_paren(clean, index)
        ports = parse_named_bindings(clean[index + 1 : close_index])
        instances.append((instance_name, parameters, ports))
    return instances


def one_instance(
    text: str, module_name: str, expected_name: str, context: str
) -> tuple[dict[str, str], dict[str, str]]:
    instances = parse_instances(text, module_name)
    if len(instances) != 1:
        raise CheckFailure(
            f"{context}: found {len(instances)} {module_name} instances; expected exactly one"
        )
    actual_name, parameters, ports = instances[0]
    if actual_name != expected_name:
        raise CheckFailure(
            f"{context}: {module_name} instance is {actual_name}; expected {expected_name}"
        )
    return parameters, ports


def require_parameter_default(text: str, name: str, value_pattern: str, context: str) -> None:
    require_regex(
        text,
        rf"\bparameter\s+(?:int\s+unsigned|integer|longint\s+unsigned)\s+{name}\s*=\s*{value_pattern}\b",
        context,
    )


def validate_clock_reset_ctrl(text: str) -> None:
    clean = strip_sv_comments(text)
    compact_text = compact(clean)
    require_regex(clean, r"\bmodule\s+clock_reset_ctrl\b", "clock_reset_ctrl")

    require_parameter_default(clean, "FABRIC_CLK_HZ", r"50_?000_?000", "clock_reset_ctrl")
    require_parameter_default(clean, "BOARD_RESET_RELEASE_CYCLES", r"1_?000_?000", "clock_reset_ctrl")
    require_parameter_default(clean, "SAMPLE_TICK_HZ", r"48_?000", "clock_reset_ctrl")
    require_parameter_default(clean, "STATUS_TICK_HZ", r"10", "clock_reset_ctrl")
    require_parameter_default(clean, "METRICS_TICK_HZ", r"30", "clock_reset_ctrl")
    require_parameter_default(clean, "HEARTBEAT_TOGGLE_HZ", r"2", "clock_reset_ctrl")

    for token in (
        "input logic h2f_reset_n_i",
        "output logic clk_fabric_o",
        "output logic rst_n_platform_o",
        "board_reset_release_count_q",
        "board_reset_release_qualified_n_q",
        "platform_async_rst_n",
    ):
        if compact(token) not in compact_text:
            raise CheckFailure(f"clock_reset_ctrl: missing frozen token {token}")

    for identifier in PSEUDO_DOMAIN_IDENTIFIERS:
        forbid_regex(clean, rf"\b{re.escape(identifier)}(?:_o)?\b", "clock_reset_ctrl")
    for old_parameter in (
        "SAMPLE_TICK_DIV",
        "STATUS_TICK_DIV",
        "METRICS_TICK_DIV",
        "HEARTBEAT_TOGGLE_DIV",
    ):
        forbid_regex(clean, rf"\b{old_parameter}\b", "clock_reset_ctrl")

    require_regex(
        clean,
        r"assign\s+clk_fabric_o\s*=\s*CLOCK_50\s*;",
        "clock_reset_ctrl canonical fabric clock",
    )
    require_regex(
        clean,
        r"always_ff\s*@\s*\(\s*posedge\s+CLOCK_50\s+or\s+negedge\s+KEY\s*\[\s*0\s*\]\s*\)",
        "clock_reset_ctrl 20 ms board-release qualifier",
    )
    require_regex(
        compact_text,
        r"assignplatform_async_rst_n=board_reset_release_qualified_n_q&h2f_reset_n_i;",
        "clock_reset_ctrl one reset-request combination",
    )

    parameters, ports = one_instance(
        clean, "trecap_reset_sync", "u_platform_reset_sync", "clock_reset_ctrl"
    )
    if parameters.get("STAGES") != "RESET_SYNC_STAGES":
        raise CheckFailure("clock_reset_ctrl: final reset synchronizer must use RESET_SYNC_STAGES")
    if ports.get("clk") not in {"CLOCK_50", "clk_fabric_o"}:
        raise CheckFailure("clock_reset_ctrl: final reset release must use the CLOCK_50 domain")
    require_equal(
        ports.get("async_rst_n"),
        "platform_async_rst_n",
        "clock_reset_ctrl.u_platform_reset_sync.async_rst_n",
    )
    require_equal(
        ports.get("rst_n"),
        "rst_n_platform_o",
        "clock_reset_ctrl.u_platform_reset_sync.rst_n",
    )

    # Every sequential process in this controller belongs to CLOCK_50. KEY[0] and the canonical
    # reset are permitted only as asynchronous assertion terms, never as clocks.
    for event in re.findall(r"always_ff\s*@\s*\(([^)]*)\)", clean):
        if not re.search(r"\bposedge\s+(?:CLOCK_50|clk_fabric_o)\b", event):
            raise CheckFailure(f"clock_reset_ctrl: non-fabric always_ff event control: {event.strip()}")
        if re.search(r"\b(?:sample_tick|status_tick|metrics_tick|heartbeat|ADC_SCLK)\b", event):
            raise CheckFailure(f"clock_reset_ctrl: clock-enable/protocol signal used as clock: {event.strip()}")

    # Four independent rational accumulators must add a rate numerator against FABRIC_CLK_HZ.
    for stem, rate_name, output_name in (
        ("sample", "SAMPLE_TICK_HZ", "sample_tick_o"),
        ("status", "STATUS_TICK_HZ", "status_tick_o"),
        ("metrics", "METRICS_TICK_HZ", "metrics_tick_o"),
        ("heartbeat", "HEARTBEAT_TOGGLE_HZ", "heartbeat_toggle_o"),
    ):
        require_regex(clean, rf"\b{stem}[A-Za-z0-9_]*accum[A-Za-z0-9_]*\b", f"{stem} accumulator")
        if compact(rate_name) not in compact_text or compact(output_name) not in compact_text:
            raise CheckFailure(f"clock_reset_ctrl: incomplete {stem} rate/output binding")
    require_regex(
        clean,
        r"heartbeat_o\s*<=\s*~\s*heartbeat_o|heartbeat_[A-Za-z0-9_]*\s*<=\s*~\s*heartbeat_[A-Za-z0-9_]*",
        "heartbeat 2 Hz toggle action",
    )

    # Exact-average logic must compare/subtract the reference rate rather than truncate it into
    # fixed integer periods.
    if len(re.findall(r"FABRIC_CLK_HZ", clean)) < 5:
        raise CheckFailure("clock_reset_ctrl: rational tick logic does not consistently reference FABRIC_CLK_HZ")
    forbid_regex(clean, r"\b(?:sample|status|metrics|heartbeat)[A-Za-z0-9_]*_LAST\b", "clock_reset_ctrl")


def validate_reset_sync(text: str) -> None:
    clean = strip_sv_comments(text)
    require_regex(clean, r"\bparameter\s+bit\s+RELEASE_ON_NEGEDGE\s*=\s*1'b0", "reset_sync")
    require_regex(clean, r"if\s*\(\s*RELEASE_ON_NEGEDGE\s*\)", "reset_sync edge selection")
    require_regex(clean, r"always_ff\s*@\s*\(\s*negedge\s+clk\s+or\s+negedge\s+async_rst_n", "reset_sync negedge release")
    require_regex(clean, r"always_ff\s*@\s*\(\s*posedge\s+clk\s+or\s+negedge\s+async_rst_n", "reset_sync posedge release")
    require_regex(clean, r"localparam\s+int\s+unsigned\s+STAGES_SAFE\s*=\s*\(STAGES\s*<\s*2\)\s*\?\s*2", "reset_sync minimum stages")


def validate_board_top(text: str) -> None:
    clean = strip_sv_comments(text)
    compact_text = compact(clean)
    require_regex(clean, r"\bmodule\s+de1_soc_trecap_top\b", "board top")
    if parse_instances(clean, "trecap_reset_sync"):
        raise CheckFailure("board top: a second reset synchronizer is not permitted")
    for identifier in PSEUDO_DOMAIN_IDENTIFIERS:
        forbid_regex(clean, rf"\b{re.escape(identifier)}\b", "board top")

    # Each raw control name occurs once in the top-level port declaration and twice in its
    # same-name controller binding (.KEY(KEY)/.SW(SW)). Any further occurrence is a bypass of
    # the synchronizing/debouncing owner.
    for raw_control in ("KEY", "SW"):
        occurrence_count = len(re.findall(rf"\b{raw_control}\b", clean))
        if occurrence_count != 3:
            raise CheckFailure(
                f"board top: raw {raw_control} appears {occurrence_count} times; expected only "
                "the port declaration and clock_reset_ctrl binding"
            )
    require_regex(
        clean,
        r"wire\s+unused_reserved_clocks\s*=\s*CLOCK2_50\s*\^\s*CLOCK3_50\s*\^\s*CLOCK4_50\s*;",
        "board top inactive alternate clocks",
    )
    for alternate in ("CLOCK2_50", "CLOCK3_50", "CLOCK4_50"):
        if len(re.findall(rf"\b{alternate}\b", clean)) != 2:
            raise CheckFailure(
                f"board top: {alternate} must appear only as a reserved input and unused reduction"
            )

    ctrl_params, ctrl_ports = one_instance(
        clean, "clock_reset_ctrl", "u_clock_reset_ctrl", "board top"
    )
    expected_ctrl_params = {
        "FABRIC_CLK_HZ": "FABRIC_CLK_HZ",
        "BOARD_RESET_RELEASE_CYCLES": "BOARD_RESET_RELEASE_CYCLES",
        "SAMPLE_TICK_HZ": "SAMPLE_TICK_HZ",
        "STATUS_TICK_HZ": "STATUS_TICK_HZ",
        "METRICS_TICK_HZ": "METRICS_TICK_HZ",
        "HEARTBEAT_TOGGLE_HZ": "HEARTBEAT_TOGGLE_HZ",
    }
    for name, expression in expected_ctrl_params.items():
        require_equal(ctrl_params.get(name), expression, f"board top clock_reset_ctrl parameter {name}")
    expected_ctrl_ports = {
        "CLOCK_50": "CLOCK_50",
        "KEY": "KEY",
        "SW": "SW",
        "h2f_reset_n_i": "h2f_reset_n",
        "clk_fabric_o": "clk_fabric",
        "rst_n_platform_o": "rst_n_platform",
    }
    for name, expression in expected_ctrl_ports.items():
        require_equal(ctrl_ports.get(name), expression, f"board top clock_reset_ctrl port {name}")

    for module_name, (instance_name, clock_port, reset_port) in SHARED_INSTANCE_BINDINGS.items():
        _parameters, ports = one_instance(clean, module_name, instance_name, "board top")
        require_equal(ports.get(clock_port), "clk_fabric", f"board top {instance_name}.{clock_port}")
        require_equal(ports.get(reset_port), "rst_n_platform", f"board top {instance_name}.{reset_port}")
        for port_name, expression in ports.items():
            if re.search(r"\b(?:KEY|SW)\b", expression):
                raise CheckFailure(
                    f"board top: raw board control appears outside clock_reset_ctrl at {instance_name}.{port_name}"
                )

    # h2f reset is an input to the sole owner; the final platform reset returns to the generated
    # bridge boundary. This deliberately does not treat the HPS reset output as a fabric reset.
    _pd_params, pd_ports = one_instance(
        clean, "platform_designer_wrapper", "u_platform_designer_wrapper", "board top"
    )
    require_equal(pd_ports.get("h2f_reset_n_o"), "h2f_reset_n", "board top HPS reset export")

    for event in re.findall(r"always_ff\s*@\s*\(([^)]*)\)", clean):
        if not re.search(r"\bposedge\s+clk_fabric\b", event):
            raise CheckFailure(f"board top: non-canonical sequential clock: {event.strip()}")
        if "negedge" in event and not re.search(r"\bnegedge\s+rst_n_platform\b", event):
            raise CheckFailure(f"board top: non-canonical asynchronous reset: {event.strip()}")

    for parameter in (
        "FABRIC_CLK_HZ",
        "BOARD_RESET_RELEASE_CYCLES",
        "SAMPLE_TICK_HZ",
        "STATUS_TICK_HZ",
        "METRICS_TICK_HZ",
        "HEARTBEAT_TOGGLE_HZ",
    ):
        if parameter not in clean:
            raise CheckFailure(f"board top: missing frozen clock/reset parameter {parameter}")
    for old_parameter in (
        "SAMPLE_TICK_DIV",
        "STATUS_TICK_DIV",
        "METRICS_TICK_DIV",
        "HEARTBEAT_DIV",
    ):
        forbid_regex(clean, rf"\b{old_parameter}\b", "board top")
    if ".sample_tick_o(sample_tick)" not in compact_text:
        raise CheckFailure("board top: sample tick must be a clock-enable output from clock_reset_ctrl")


def validate_audio(text: str) -> None:
    clean = strip_sv_comments(text)
    compact_text = compact(clean)
    instances = parse_instances(clean, "trecap_reset_sync")
    if len(instances) != 2:
        raise CheckFailure(f"audio wrapper: found {len(instances)} reset synchronizers; expected two")
    by_name = {name: (parameters, ports) for name, parameters, ports in instances}
    if set(by_name) != {"u_bclk_rx_reset_sync", "u_bclk_tx_reset_sync"}:
        raise CheckFailure("audio wrapper: reset synchronizer instance names do not match RX/TX policy")

    rx_parameters, rx_ports = by_name["u_bclk_rx_reset_sync"]
    tx_parameters, tx_ports = by_name["u_bclk_tx_reset_sync"]
    require_equal(rx_parameters.get("RELEASE_ON_NEGEDGE"), "1'b0", "audio RX reset edge")
    require_equal(tx_parameters.get("RELEASE_ON_NEGEDGE"), "1'b1", "audio TX reset edge")
    require_equal(rx_ports.get("clk"), "aud_bclk", "audio RX reset clock")
    require_equal(tx_ports.get("clk"), "aud_bclk", "audio TX reset clock")
    require_equal(rx_ports.get("async_rst_n"), "rst_n", "audio RX asynchronous assertion")
    require_equal(tx_ports.get("async_rst_n"), "rst_n", "audio TX asynchronous assertion")
    rx_reset = rx_ports.get("rst_n")
    tx_reset = tx_ports.get("rst_n")
    if not rx_reset or not tx_reset or rx_reset == tx_reset:
        raise CheckFailure("audio wrapper: RX and TX require distinct edge-specific reset nets")
    require_regex(
        clean,
        rf"always_ff\s*@\s*\(\s*posedge\s+aud_bclk\s+or\s+negedge\s+{re.escape(rx_reset)}\b",
        "audio RX event/reset edge",
    )
    require_regex(
        clean,
        rf"always_ff\s*@\s*\(\s*negedge\s+aud_bclk\s+or\s+negedge\s+{re.escape(tx_reset)}\b",
        "audio TX event/reset edge",
    )
    if "assignAUD_XCK=audio_mclk_i;" not in compact_text:
        raise CheckFailure("audio wrapper: AUD_XCK must be owned by the reviewed PLL input")
    forbid_regex(clean, r"assign\s+AUD_XCK\s*=\s*[^;]*(?:counter|divider)", "audio wrapper")


def validate_adc(text: str) -> None:
    clean = strip_sv_comments(text)
    compact_text = compact(clean)
    require_regex(clean, r"\bmodule\s+adc_wrapper\b", "ADC wrapper")
    require_regex(clean, r"always_ff\s*@\s*\(\s*posedge\s+clk\s+or\s+negedge\s+rst_n", "ADC fabric-domain state")
    for event in re.findall(r"always(?:_ff)?\s*@\s*\(([^)]*)\)", clean):
        if re.search(r"\bADC_SCLK\b", event):
            raise CheckFailure(f"ADC wrapper: ADC_SCLK is incorrectly used as an RTL clock: {event.strip()}")
    forbid_regex(clean, r"\.(?:clk|clock)\s*\(\s*ADC_SCLK\s*\)", "ADC wrapper")
    for token in (
        "assignsample_rate_sum={1'b0,sample_rate_accum_q}+SAMPLE_EVENT_RATE;",
        "if(sample_rate_sum>=SAMPLE_CLK_RATE)",
        "sample_rate_accum_q<=sample_rate_sum-SAMPLE_CLK_RATE;",
    ):
        if token not in compact_text:
            raise CheckFailure(f"ADC wrapper: exact-average continuous scheduler token is missing: {token}")
    for stale_divider in ("SAMPLE_DIV_SAFE", "SAMPLE_DIV_LAST", "sample_div_cnt_q"):
        forbid_regex(clean, rf"\b{stale_divider}\b", "ADC wrapper integer scheduler")


def validate_telemetry_soft_reset(texts: dict[Path, str]) -> None:
    combined = "\n".join(strip_sv_comments(text) for text in texts.values())
    if "telemetry_soft_reset" not in combined:
        raise CheckFailure("telemetry hierarchy: soft-reset path is missing")
    for rel, text in texts.items():
        clean = strip_sv_comments(text)
        for event in re.findall(r"always(?:_ff)?\s*@\s*\(([^)]*)\)", clean):
            if re.search(r"(?:telemetry_soft_reset|formatter_reset)", event, flags=re.IGNORECASE):
                raise CheckFailure(
                    f"{rel}: telemetry soft reset appears in an event control: {event.strip()}"
                )
        forbid_regex(
            clean,
            r"\.(?:rst_n|async_rst_n)\s*\([^)]*(?:telemetry_soft_reset|formatter_reset)[^)]*\)",
            f"{rel} telemetry reset derivation",
        )
        forbid_regex(
            clean,
            r"assign\s+(?:rst[A-Za-z0-9_]*|[A-Za-z0-9_]*_rst_n|[A-Za-z0-9_]*reset_n)\s*=\s*[^;]*(?:telemetry_soft_reset|formatter_reset)",
            f"{rel} telemetry reset derivation",
        )

    telemetry = strip_sv_comments(texts[TELEMETRY_REL])
    require_regex(
        telemetry,
        r"assign\s+formatter_reset\s*=\s*telemetry_soft_reset_i\s*\|\|\s*formatter_flush_i\s*;",
        "telemetry unified synchronous formatter clear",
    )
    formatter_bindings = re.findall(
        r"\.formatter_reset_i\s*\(\s*formatter_reset\s*\)", telemetry
    )
    if len(formatter_bindings) != 5:
        raise CheckFailure(
            "telemetry synchronous clear/flush: all four packetizers and scheduler must use "
            f"formatter_reset exactly once (found {len(formatter_bindings)})"
        )
    require_regex(
        telemetry,
        r"\.flush_i\s*\(\s*formatter_reset\s*\)",
        "telemetry packet-FIFO unified synchronous formatter clear",
    )
    require_regex(
        telemetry,
        r"always_ff\s*@\s*\(\s*posedge\s+clk\s+or\s+negedge\s+rst_n\s*\)",
        "telemetry platform reset",
    )

    full_top = strip_sv_comments(texts[FULL_TOP_REL])
    require_regex(
        full_top,
        r"assign\s+telemetry_soft_clear_w\s*=\s*telemetry_soft_reset_pulse_w\s*\|\s*"
        r"external_transport_clear_i\s*;",
        "full-top transport-only synchronous-clear derivation",
    )
    require_regex(
        full_top,
        r"\.telemetry_soft_reset_i\s*\(\s*telemetry_soft_clear_w\s*\)",
        "full-top telemetry transport-clear binding",
    )
    require_regex(
        full_top,
        r"\.formatter_flush_i\s*\(\s*formatter_flush_w\s*\)",
        "full-top telemetry discontinuity-flush binding",
    )
    hps_bridge = strip_sv_comments(texts[HPS_BRIDGE_REL])
    require_regex(
        hps_bridge,
        r"assign\s+writer_transport_clear\s*=\s*csr_telemetry_soft_reset_pulse\s*\|\s*external_transport_clear_i\s*;",
        "HPS bridge synchronous transport-clear derivation",
    )
    require_regex(
        hps_bridge,
        r"\.clear_i\s*\(\s*writer_transport_clear\s*\)",
        "DDR writer synchronous transport-clear binding",
    )
    require_regex(
        hps_bridge,
        r"always_ff\s*@\s*\(\s*posedge\s+clk\s+or\s+negedge\s+rst_n\s*\).*?if\s*\(\s*writer_transport_clear\s*\)",
        "HPS bridge synchronous transport status clear",
    )

    for rel in (
        WAVE_PACKETIZER_REL,
        SPEC_PACKETIZER_REL,
        METRICS_PACKETIZER_REL,
        STATUS_PACKETIZER_REL,
        PACKET_SCHEDULER_REL,
    ):
        child = strip_sv_comments(texts[rel])
        require_regex(child, r"\binput\s+logic\s+formatter_reset_i\b", f"{rel} soft-clear input")
        require_regex(
            child,
            r"always_ff\s*@\s*\(\s*posedge\s+clk\s+or\s+negedge\s+rst_n\s*\).*?"
            r"(?:if|else\s+if)\s*\(\s*!?formatter_reset_i\s*\)",
            f"{rel} synchronous formatter clear",
        )
    fifo = strip_sv_comments(texts[PACKET_FIFO_REL])
    require_regex(fifo, r"\binput\s+logic\s+flush_i\b", "packet FIFO synchronous flush input")
    require_regex(
        fifo,
        r"always_ff\s*@\s*\(\s*posedge\s+clk\s+or\s+negedge\s+rst_n\s*\).*?"
        r"(?:if|else\s+if)\s*\(\s*!?flush_i\s*\)",
        "packet FIFO synchronous flush",
    )


def validate_platform_designer(wrapper: str, script: str, qsys_text: str) -> None:
    wrapper_clean = strip_sv_comments(wrapper)
    require_regex(wrapper_clean, r"\.clk_50_clk\s*\(\s*clk_50_i\s*\)", "Platform Designer wrapper clock")
    require_regex(wrapper_clean, r"\.reset_n_reset_n\s*\(\s*bridge_reset_n_i\s*\)", "Platform Designer wrapper reset")
    require_regex(wrapper_clean, r"\.h2f_reset_reset_n\s*\(\s*h2f_reset_n_o\s*\)", "Platform Designer HPS reset")

    script_clean = strip_tcl_comments(script)
    for token in (
        "set_parameter_strict clk_0 clockFrequency",
        "clk_0.clk_in",
        # Reset and downstream clock names are deliberately frozen in hps_config.tcl and
        # consumed symbolically here; the checked-in Qsys XML below proves their resolved values.
        "fabric_clk_internal",
        "fabric_reset_internal",
        "fabric_reset_bridge_internal",
    ):
        if token not in script_clean:
            raise CheckFailure(f"Platform Designer script: missing frozen clock/reset token {token}")

    try:
        root = ET.fromstring(qsys_text)
    except ET.ParseError as exc:
        raise CheckFailure(f"cannot parse checked-in Platform Designer source: {exc}") from exc
    clk_instances = root.findall("./planned_instances/instance[@name='clk_0']")
    if len(clk_instances) != 1:
        raise CheckFailure("Platform Designer source: expected exactly one clk_0 instance")
    clk_instance = clk_instances[0]
    frequency = clk_instance.find("./parameter[@name='clockFrequency']")
    if frequency is None or frequency.attrib.get("value") != "50000000":
        raise CheckFailure("Platform Designer source: clk_0 clockFrequency must be 50000000")
    exports = {
        (item.attrib.get("name"), item.attrib.get("internal"), item.attrib.get("kind"))
        for item in clk_instance.findall("./export")
    }
    required_exports = {
        ("clk_50", "clk_0.clk_in", "clock"),
        ("reset_n", "clk_0.clk_in_reset", "reset"),
    }
    if not required_exports.issubset(exports):
        raise CheckFailure("Platform Designer source: clk_0 clock/reset exports differ from contract")

    connections = {
        (item.attrib.get("source"), item.attrib.get("sink"))
        for item in root.findall("./planned_connections/connection")
    }
    for connection in (
        ("clk_0.clk", "trecap_csr_bridge.clk"),
        ("clk_0.clk_reset", "trecap_csr_bridge.reset"),
        ("clk_0.clk", "trecap_f2h_sdram_bridge.clk"),
        ("clk_0.clk_reset", "trecap_f2h_sdram_bridge.reset"),
    ):
        if connection not in connections:
            raise CheckFailure(f"Platform Designer source: missing typed-bridge connection {connection}")


def validate_sdc(primary: str, supplemental: str) -> None:
    primary_clean = strip_tcl_comments(primary)
    supplemental_clean = strip_tcl_comments(supplemental)
    combined = primary_clean + "\n" + supplemental_clean
    require_regex(
        combined,
        r"(?:create_clock|create_clock_if_port|create_clock_if_port_unclocked)[^\n]*CLOCK_50[^\n]*20\.000|(?:create_clock|create_clock_if_port|create_clock_if_port_unclocked)[^\n]*20\.000[^\n]*CLOCK_50",
        "SDC canonical CLOCK_50 constraint",
    )
    for line in combined.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("proc "):
            continue
        if re.search(r"(?:create_clock|create_clock_if_port|create_clock_if_port_unclocked)", stripped):
            if re.search(r"\b(?:CLOCK2_50|CLOCK3_50|CLOCK4_50|FPGA_CLK[123]_50|AUD_BCLK|AUD_XCK|ADC_SCLK)\b", stripped):
                raise CheckFailure(f"SDC: deferred/noncanonical clock is actively constrained: {stripped}")
        if "create_generated_clock" in stripped:
            raise CheckFailure(f"SDC: generated clock constraint is premature in Step 10: {stripped}")

    # The supplemental policy file must not become a second active source-owned clock creator.
    for line in supplemental_clean.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("proc ") and re.search(
            r"(?:create_clock|create_generated_clock|set_clock_groups)", stripped
        ):
            raise CheckFailure(
                f"SDC: supplemental clock policy contains an active timing command: {stripped}"
            )

    # Cut only the actual first stages of reviewed synchronizers.  These tokens also prevent the
    # former stale async-FIFO register names from silently surviving a source-only review.
    for token in (
        "*|trecap_reset_sync:*|sync_q[0]",
        "*|clock_reset_ctrl:*|key_sync_q[*][0]",
        "*|clock_reset_ctrl:*|sw_sync_q[*][0]",
        "*|trecap_async_fifo:*|rd_gray_sync_wr_q[0]",
        "*|trecap_async_fifo:*|wr_gray_sync_rd_q[0]",
        "*|audio_pll_wrapper:*|pll_locked_sync_q[0]",
        "*|audio_codec_wrapper:*|u_bclk_rx_reset_sync*|sync_q[0]",
        "*|audio_codec_wrapper:*|u_bclk_tx_reset_sync*|sync_q[0]",
        "*|audio_codec_wrapper:*|bclk_codec_ready_sync_q[0]",
        "*|audio_codec_wrapper:*|bclk_capture_enable_sync_q[0]",
        "*|audio_codec_wrapper:*|bclk_tx_codec_ready_sync_q[0]",
        "*|audio_codec_wrapper:*|bclk_lineout_enable_sync_q[0]",
        "*|audio_codec_wrapper:*|bclk_tx_epoch_sync_q[0]",
        "*|audio_codec_wrapper:*|clk_bclk_seen_sync_q[0]",
        "*|audio_codec_wrapper:*|clk_lrck_seen_sync_q[0]",
        "*|de1_soc_trecap_top:*|audio_i2c_bus_grant_sync_q[0]",
    ):
        if token not in primary_clean:
            raise CheckFailure(f"SDC: required first-stage synchronizer cut is missing: {token}")
    for stale_token in (
        "*|trecap_async_fifo:*|wr_gray_sync_q[0]",
        "*|trecap_async_fifo:*|rd_gray_sync_q[0]",
    ):
        if stale_token in combined:
            raise CheckFailure(f"SDC: stale async-FIFO register pattern is present: {stale_token}")


def run_checks(repo_root: Path, force_fallback: bool) -> tuple[str, int]:
    required_paths = (
        CONTRACT_REL,
        SCHEMA_REL,
        CLOCK_RESET_REL,
        BOARD_TOP_REL,
        RESET_SYNC_REL,
        AUDIO_REL,
        ADC_REL,
        PD_WRAPPER_REL,
        FULL_TOP_REL,
        TELEMETRY_REL,
        WAVE_PACKETIZER_REL,
        SPEC_PACKETIZER_REL,
        METRICS_PACKETIZER_REL,
        STATUS_PACKETIZER_REL,
        PACKET_SCHEDULER_REL,
        PACKET_FIFO_REL,
        HPS_BRIDGE_REL,
        PD_TCL_REL,
        QSYS_REL,
        PRIMARY_SDC_REL,
        CLOCKS_SDC_REL,
    )
    missing = [rel.as_posix() for rel in required_paths if not (repo_root / rel).is_file()]
    if missing:
        raise CheckFailure(f"required Step-10 source files are missing: {missing}")

    contract = load_json(repo_root / CONTRACT_REL)
    schema = load_json(repo_root / SCHEMA_REL)
    engine = validate_contract_schema(contract, schema, force_fallback)
    validate_contract_values(contract)

    texts = {rel: read_text(repo_root / rel) for rel in required_paths if rel.suffix != ".json"}
    validate_clock_reset_ctrl(texts[CLOCK_RESET_REL])
    validate_reset_sync(texts[RESET_SYNC_REL])
    validate_board_top(texts[BOARD_TOP_REL])
    validate_audio(texts[AUDIO_REL])
    validate_adc(texts[ADC_REL])
    validate_telemetry_soft_reset(
        {
            FULL_TOP_REL: texts[FULL_TOP_REL],
            TELEMETRY_REL: texts[TELEMETRY_REL],
            WAVE_PACKETIZER_REL: texts[WAVE_PACKETIZER_REL],
            SPEC_PACKETIZER_REL: texts[SPEC_PACKETIZER_REL],
            METRICS_PACKETIZER_REL: texts[METRICS_PACKETIZER_REL],
            STATUS_PACKETIZER_REL: texts[STATUS_PACKETIZER_REL],
            PACKET_SCHEDULER_REL: texts[PACKET_SCHEDULER_REL],
            PACKET_FIFO_REL: texts[PACKET_FIFO_REL],
            HPS_BRIDGE_REL: texts[HPS_BRIDGE_REL],
        }
    )
    validate_platform_designer(
        texts[PD_WRAPPER_REL], texts[PD_TCL_REL], texts[QSYS_REL]
    )
    validate_sdc(texts[PRIMARY_SDC_REL], texts[CLOCKS_SDC_REL])
    return engine, len(required_paths)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the source-only Step-10 DE1-SoC clock/reset architecture contract."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repo_root_from_script(),
        help="repository root (default: inferred from this script)",
    )
    parser.add_argument(
        "--force-fallback-schema",
        action="store_true",
        help="exercise the built-in dependency-free JSON Schema validator",
    )
    parser.add_argument("--quiet", action="store_true", help="print only failures")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = args.repo_root.resolve()
    try:
        engine, checked_count = run_checks(repo_root, args.force_fallback_schema)
    except CheckFailure as exc:
        print(f"check_de1soc_clock_reset: ERROR: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(
            "check_de1soc_clock_reset: PASS "
            f"({checked_count} committed source/contract files; schema={engine}; source-only)"
        )
        print(
            "check_de1soc_clock_reset: no RTL compile, simulation, Platform Designer generation, "
            "Quartus/TimeQuest, timing-closure, or hardware evidence was produced"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
