#!/usr/bin/env python3
"""Check the Step-9 DE1-SoC board-top source-integration contract.

This dependency-free gate checks committed JSON, SystemVerilog structure, and
generated filelist ownership.  It is not an RTL compiler, simulation,
Platform Designer generation, Quartus/timing result, or hardware-signoff result.
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


CONTRACT_REL = Path("config/boards/de1soc_board_top_integration.json")
SCHEMA_REL = Path("spec/schemas/de1soc_board_top_integration.schema.json")
DOC_REL = Path("docs/architecture/de1soc_board_top_integration.md")
BOARD_TOP_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
CLOCK_RESET_REL = Path("rtl/platform/de1soc/clock_reset_ctrl.sv")
PD_WRAPPER_REL = Path("rtl/platform/de1soc/platform_designer_wrapper.sv")
AUDIO_WRAPPER_REL = Path("rtl/platform/de1soc/audio_codec_wrapper.sv")
ADC_WRAPPER_REL = Path("rtl/platform/de1soc/adc_wrapper.sv")
SOURCE_CORE_REL = Path("rtl/top/trecap_source_core_integration.sv")
FULL_TOP_REL = Path("rtl/top/trecap_de1soc_full_top.sv")
FULL_FILELIST_REL = Path("filelists/rtl_de1soc_full.f")
QUARTUS_FILELIST_REL = Path("filelists/quartus_de1soc.qsf.inc")

EXPECTED_TOP_LEVEL = {
    "schema": "trecap_phase2_de1soc_board_top_integration_v1",
    "file_class": "[1] hand-written Step-9 board-top integration contract",
    "project": "T_RECAP_Phase2",
    "board": "de1soc",
    "contract_stage": "step9_board_top_scaffolds_replaced_source_implemented",
    "status": (
        "source_implemented_pending_rtl_compile_functional_verification_"
        "platform_designer_generation_quartus_and_hardware_evidence"
    ),
}

EXPECTED_OWNERSHIP = {
    "physical_board_top": BOARD_TOP_REL.as_posix(),
    "clock_reset_controller": CLOCK_RESET_REL.as_posix(),
    "platform_designer_boundary": PD_WRAPPER_REL.as_posix(),
    "generated_platform_designer_module": "system",
    "audio_platform_wrapper": AUDIO_WRAPPER_REL.as_posix(),
    "adc_platform_wrapper": ADC_WRAPPER_REL.as_posix(),
    "source_core_integration": SOURCE_CORE_REL.as_posix(),
    "telemetry_hps_integration": FULL_TOP_REL.as_posix(),
    "full_board_filelist": FULL_FILELIST_REL.as_posix(),
    "quartus_filelist": QUARTUS_FILELIST_REL.as_posix(),
}

EXPECTED_INSTANCES = {
    "clock_reset_ctrl": "u_clock_reset_ctrl",
    "platform_designer_wrapper": "u_platform_designer_wrapper",
    "audio_codec_wrapper": "u_audio_codec_wrapper",
    "adc_wrapper": "u_adc_wrapper",
    "trecap_source_core_integration": "u_source_core_integration",
    "trecap_de1soc_full_top": "u_full_top",
}

EXPECTED_CLOCK_RESET = {
    "active_fabric_clock_source": "CLOCK_50",
    "active_fabric_clock_domain_count": 1,
    "canonical_reset_owner": "clock_reset_ctrl",
    "canonical_reset_output": "rst_n_platform",
    "physical_reset_source": "KEY[0]",
    "board_reset_release_qualification_cycles": 1_000_000,
    "hps_reset_source": "h2f_reset_n",
    "canonical_reset_combination": "qualified_KEY0_and_h2f_reset_n",
    "board_top_reset_synchronizer_permitted": False,
    "pseudo_clock_domain_outputs_permitted": False,
    "pseudo_reset_domain_outputs_permitted": False,
    "tick_generation": "fractional_accumulator_clock_enables",
    "ticks_used_as_clocks_permitted": False,
    "audio_rx_reset_sync_instance": "u_bclk_rx_reset_sync",
    "audio_tx_reset_sync_instance": "u_bclk_tx_reset_sync",
    "audio_rx_reset_release_edge": "posedge_AUD_BCLK",
    "audio_tx_reset_release_edge": "negedge_AUD_BCLK",
    "synthetic_frame_boundary_output_permitted": False,
    "synthetic_source_safe_boundary_output_permitted": False,
    "real_frame_boundary_owner": "trecap_source_core_integration",
    "real_source_safe_boundary_owner": "trecap_source_core_integration",
    "direct_clock_baseline_claims_pll_lock": False,
    "reset_may_depend_on_hardwired_pll_locked_true": False,
}

EXPECTED_EVIDENCE = {
    "source_checker": "scripts/check_de1soc_board_top.py",
    "human_document": DOC_REL.as_posix(),
    "schema_file": SCHEMA_REL.as_posix(),
    "default_checker_scope": "source_only",
    "source_check_is_rtl_compile": False,
    "source_check_is_functional_verification": False,
    "source_check_is_platform_designer_generation": False,
    "source_check_is_quartus_compile": False,
    "source_check_is_hardware_signoff": False,
}


class CheckFailure(RuntimeError):
    """Raised when the checked-in Step-9 source contract is inconsistent."""


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


def compact_sv(text: str) -> str:
    return re.sub(r"\s+", "", strip_sv_comments(text))


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CheckFailure(f"{context} differs from the frozen Step-9 value")


def require_token(text: str, token: str, context: str) -> None:
    if token not in text:
        raise CheckFailure(f"{context}: required source token is missing: {token}")


def forbid_token(text: str, token: str, context: str) -> None:
    if token in text:
        raise CheckFailure(f"{context}: forbidden scaffold token is present: {token}")


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
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise CheckFailure(f"{location}: array items are not unique")
        child = schema.get("items")
        if isinstance(child, dict):
            for index, item in enumerate(value):
                validate_schema_fallback(item, child, schema_root, f"{location}[{index}]")
    if isinstance(value, str) and len(value) < int(schema.get("minLength", 0)):
        raise CheckFailure(f"{location}: string is shorter than minLength")


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


def one_instance(text: str, module_name: str, expected_name: str) -> dict[str, str]:
    instances = parse_instances(text, module_name)
    if len(instances) != 1:
        raise CheckFailure(
            f"board top: found {len(instances)} {module_name} instances; expected exactly one"
        )
    instance_name, body = instances[0]
    if instance_name != expected_name:
        raise CheckFailure(
            f"board top: {module_name} instance is {instance_name}; expected {expected_name}"
        )
    return parse_named_ports(body)


def require_same_binding(
    producer: dict[str, str], producer_port: str, consumer: dict[str, str], consumer_port: str
) -> None:
    producer_signal = producer.get(producer_port)
    consumer_signal = consumer.get(consumer_port)
    if producer_signal is None or consumer_signal is None:
        raise CheckFailure(f"missing binding {producer_port} -> {consumer_port}")
    if producer_signal != consumer_signal:
        raise CheckFailure(
            f"binding mismatch: {producer_port}={producer_signal}, "
            f"{consumer_port}={consumer_signal}"
        )


def constant_tieoff(expression: str) -> bool:
    compact = re.sub(r"\s+", "", expression)
    if compact in {"'0", "'1", "0", "1", "1'b0", "1'b1"}:
        return True
    return bool(re.fullmatch(r"(?:\d+)?'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+", compact))


def validate_contract_values(contract: dict[str, Any]) -> None:
    for name, expected in EXPECTED_TOP_LEVEL.items():
        require_equal(contract.get(name), expected, f"contract.{name}")
    require_equal(contract.get("source_ownership"), EXPECTED_OWNERSHIP, "contract.source_ownership")
    composition = contract.get("board_composition", {})
    require_equal(
        composition.get("required_instances"), EXPECTED_INSTANCES, "contract required instances"
    )
    require_equal(
        contract.get("clock_reset_scaffold_contract"),
        EXPECTED_CLOCK_RESET,
        "contract.clock_reset_scaffold_contract",
    )
    require_equal(contract.get("evidence_policy"), EXPECTED_EVIDENCE, "contract.evidence_policy")
    state = contract.get("implementation_state", {})
    for key in (
        "rtl_compile",
        "functional_verification",
        "platform_designer_generation",
        "quartus_compile",
        "hardware_signoff",
    ):
        require_equal(state.get(key), False, f"contract.implementation_state.{key}")
    rules = contract.get("validation_rules")
    if not isinstance(rules, list) or len(rules) < 12:
        raise CheckFailure("contract.validation_rules must contain at least twelve rules")


def validate_board_top(text: str) -> None:
    clean = strip_sv_comments(text)
    compact = re.sub(r"\s+", "", clean)
    require_token(clean, "module de1_soc_trecap_top", "board-top RTL")

    ports_by_module = {
        module_name: one_instance(text, module_name, instance_name)
        for module_name, instance_name in EXPECTED_INSTANCES.items()
    }
    if parse_instances(text, "trecap_core_top"):
        raise CheckFailure("board top directly instantiates trecap_core_top outside its owner")
    if parse_instances(text, "trecap_core_telemetry_top"):
        raise CheckFailure("board top instantiates the standalone second-core composition")

    pd_ports = ports_by_module["platform_designer_wrapper"]
    full_ports = ports_by_module["trecap_de1soc_full_top"]
    audio_ports = ports_by_module["audio_codec_wrapper"]
    adc_ports = ports_by_module["adc_wrapper"]
    source_ports = ports_by_module["trecap_source_core_integration"]
    clock_ports = ports_by_module["clock_reset_ctrl"]

    for removed_scaffold_port in (
        "frame_boundary_o",
        "source_safe_boundary_o",
        "pll_locked_o",
        "reset_request_n_o",
        "clk_core_o",
        "clk_telemetry_o",
        "clk_hps_bridge_o",
        "rst_n_fabric_o",
        "rst_n_core_o",
        "rst_n_telemetry_o",
        "rst_n_hps_bridge_o",
    ):
        if removed_scaffold_port in clock_ports:
            raise CheckFailure(
                f"clock_reset_ctrl board instance retains scaffold port .{removed_scaffold_port}"
            )

    for port, signal in {
        "CLOCK_50": "CLOCK_50",
        "h2f_reset_n_i": "h2f_reset_n",
        "clk_fabric_o": "clk_fabric",
        "rst_n_platform_o": "rst_n_platform",
    }.items():
        require_equal(clock_ports.get(port), signal, f"clock/reset binding .{port}")

    require_equal(pd_ports.get("clk_50_i"), "clk_fabric", "PD fabric-clock binding")
    require_equal(pd_ports.get("bridge_reset_n_i"), "rst_n_platform", "PD reset binding")
    require_equal(source_ports.get("clk"), "clk_fabric", "source/core clock binding")
    require_equal(source_ports.get("rst_n"), "rst_n_platform", "source/core reset binding")
    require_equal(full_ports.get("clk"), "clk_fabric", "telemetry/HPS clock binding")
    require_equal(full_ports.get("rst_n"), "rst_n_platform", "telemetry/HPS reset binding")

    for name in (
        "address",
        "read",
        "write",
        "writedata",
        "byteenable",
        "burstcount",
    ):
        require_same_binding(pd_ports, f"csr_avs_{name}_o", full_ports, f"csr_avs_{name}_i")
    for name in (
        "waitrequest",
        "readdata",
        "readdatavalid",
        "writeresponsevalid",
        "response",
    ):
        require_same_binding(full_ports, f"csr_avs_{name}_o", pd_ports, f"csr_avs_{name}_i")
    for name in ("address", "write", "writedata", "byteenable", "burstcount"):
        require_same_binding(full_ports, f"avm_{name}_o", pd_ports, f"avm_{name}_i")
    for name in ("waitrequest", "writeresponsevalid", "response"):
        require_same_binding(pd_ports, f"avm_{name}_o", full_ports, f"avm_{name}_i")

    for producer_port, consumer_port in (
        ("audio_sample_valid_o", "audio_sample_valid_i"),
        ("audio_left_o", "audio_left_i"),
        ("audio_right_o", "audio_right_i"),
        ("audio_sample_count_o", "audio_sample_count_i"),
    ):
        require_same_binding(audio_ports, producer_port, source_ports, consumer_port)
    for producer_port, consumer_port in (
        ("sample_raw_o", "adc_sample_raw_i"),
        ("sample_count_o", "adc_sample_count_i"),
    ):
        require_same_binding(adc_ports, producer_port, source_ports, consumer_port)
    # Raw valid reaches the supervisor so its physical-sample accounting is complete.
    # Manual ADC isolation is owned by readiness/periodic source admission there.
    require_same_binding(adc_ports, "sample_valid_o", source_ports, "adc_sample_valid_i")
    require_equal(
        source_ports.get("adc_ready_i"), "adc_config_supported&&!sw_sync[7]",
        "manual ADC supervisor readiness gate",
    )
    require_equal(
        source_ports.get("live_periodic_i"),
        "(active_source_mode==TSRC_AUDIO_WRAPPER)||((active_source_mode==TSRC_ADC_LIVE)&&!sw_sync[7])",
        "manual ADC supervisor periodic-source gate",
    )

    tap_bindings = (
        ("tap_sample_o", "tap_sample_i"),
        ("tap_frame_o", "tap_frame_i"),
        ("tap_bin_valid_o", "tap_bin_valid_i"),
        ("tap_bin_frame_idx_o", "tap_bin_frame_idx_i"),
        ("tap_bin_idx_o", "tap_bin_idx_i"),
        ("tap_bin_mag2_o", "tap_bin_mag2_i"),
        ("tap_bin_mask_o", "tap_bin_mask_i"),
        ("tap_bin_eligible_o", "tap_bin_eligible_i"),
        ("tap_bin_last_o", "tap_bin_last_i"),
        ("core_sample_count_o", "core_sample_count_i"),
        ("core_frame_count_o", "core_frame_count_i"),
        ("core_sum_abs_err_lo_o", "core_sum_abs_err_lo_i"),
        ("core_sum_sq_err_lo_o", "core_sum_sq_err_lo_i"),
        ("core_metric_overflow_sticky_o", "core_metric_truncated_i"),
        ("core_config_safe_boundary_o", "frame_boundary_i"),
        ("source_safe_boundary_o", "source_safe_boundary_i"),
        ("source_discontinuity_pulse_o", "source_discontinuity_i"),
        ("clear_metrics_apply_pulse_o", "clear_metrics_apply_pulse_i"),
    )
    for producer_port, consumer_port in tap_bindings:
        require_same_binding(source_ports, producer_port, full_ports, consumer_port)

    # The core output is an observation fanout at board level, not a codec-backpressured path.
    # It remains always accepted while the audio wrapper best-effort FIFO absorbs valid/data and
    # records an overrun if that monitor queue is full.
    require_equal(source_ports.get("y_ready_i"), "1'b1", "non-stalling core y sink")
    require_same_binding(source_ports, "y_valid_o", audio_ports, "lineout_valid_i")
    y_data_signal = source_ports.get("y_data_o")
    if not y_data_signal:
        raise CheckFailure("source/core y_data_o is unbound")
    left_expression = audio_ports.get("lineout_left_i", "")
    right_expression = audio_ports.get("lineout_right_i", "")
    if not left_expression or left_expression != right_expression or constant_tieoff(left_expression):
        raise CheckFailure("audio lineout channels must share one nonconstant dual-mono y source")
    if y_data_signal not in left_expression:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", left_expression):
            raise CheckFailure("derived audio lineout expression is not a traceable named net")
        derived_match = re.search(
            rf"\b{re.escape(left_expression)}\s*=\s*([^;]+);", clean
        )
        if derived_match is None or y_data_signal not in re.sub(r"\s+", "", derived_match.group(1)):
            raise CheckFailure("derived audio lineout net does not consume the real core y data")
        derived_expression = re.sub(r"\s+", "", derived_match.group(1))
    else:
        derived_expression = left_expression
    if "AUDIO_SAMPLE_W-T_SAMPLE_W" not in derived_expression or "<<<" not in derived_expression:
        raise CheckFailure(
            "core-y audio mapping must use the frozen signed left-shift width conversion"
        )
    for token in (
        "assignaudio_capture_enable=(active_source_mode==TSRC_AUDIO_WRAPPER)&&audio_codec_ready;",
        "assignaudio_lineout_monitor_enable=AUDIO_LINEOUT_ALLOWED&&sw_sync[3]&&!source_discontinuity&&audio_codec_ready;",
        "assignadc_source_enable=(active_source_mode==TSRC_ADC_LIVE);",
        "assignadc_epoch_ready=adc_source_enable&&adc_source_enable_d_q&&!adc_sampling_mode_change;",
        "assignadc_continuous_enable=adc_epoch_ready&&!sw_sync[7];",
        "assignadc_manual_request=adc_epoch_ready&&sw_sync[7]&&key_press_pulse[2];",
        "assignadc_command=ltc2308_single_ended_command(adc_channel_active_q);",
        "if(adc_source_enable&&!adc_source_enable_d_q)",
        "adc_channel_active_q<=sw_sync[6:4];",
        ".FRAME_BITS(12)",
        ".COMMAND_BITS(6)",
        ".command_i(adc_command)",
        ".command_valid_i(1'b1)",
    ):
        require_token(compact, token, "board audio/LTC2308 control binding")
    if compact.count("adc_channel_active_q<=") != 2:
        raise CheckFailure(
            "board top must update the LTC2308 channel only on reset and ADC-epoch entry"
        )
    if constant_tieoff(audio_ports.get("lineout_enable_i", "")):
        raise CheckFailure("audio lineout_enable_i remains a constant scaffold tie-off")

    adc_command = adc_ports.get("command_i", "")
    if not adc_command or constant_tieoff(adc_command):
        raise CheckFailure("ADC command_i remains a constant scaffold tie-off")
    adc_request = adc_ports.get("sample_request_i", "")
    adc_continuous = adc_ports.get("continuous_enable_i", "")
    if (not adc_request or constant_tieoff(adc_request)) and (
        not adc_continuous or constant_tieoff(adc_continuous)
    ):
        raise CheckFailure("ADC has neither a real explicit request nor a real continuous-mode path")

    for pin in ("AUD_DACDAT", "ADC_CS_N", "ADC_DIN", "ADC_SCLK"):
        if re.search(rf"\bassign\s+{pin}\s*=\s*(?:'0|'1|\d+'[bBoOdDhH][^;]+)\s*;", clean):
            raise CheckFailure(f"board top directly ties physical output {pin} to a constant")

    for token in ("assignHEX0=", "assignHEX1=", "assignHEX2=", "assignHEX3=", "assignHEX4=", "assignHEX5="):
        require_token(compact, token, "board status display")
    for index in range(10):
        require_token(compact, f"assignLEDR[{index}]=", "board LED status")
    for token in ("core_sample_count", "core_frame_count", "status", "overflow_flags", "writer_busy"):
        require_token(clean, token, "real board status path")
    for scaffold in (
        "synthetic_sample_counter",
        "synthetic_frame_counter",
        "synthetic_tap",
        "activity_counter_q",
        "fake_core",
        "safe_idle_csr",
        "safe_idle_ddr",
    ):
        forbid_token(clean, scaffold, "board-top RTL")

    for forbidden in (
        "trecap_reset_sync",
        "u_platform_reset_sync",
        "reset_request_n",
        "clk_core",
        "clk_telemetry",
        "clk_hps_bridge",
        "rst_n_fabric",
        "rst_n_core",
        "rst_n_telemetry",
        "rst_n_hps_bridge",
    ):
        forbid_token(clean, forbidden, "board-top canonical reset ownership")

    require_token(
        compact,
        "unused_reserved_clocks=CLOCK2_50^CLOCK3_50^CLOCK4_50;",
        "reserved alternate board clocks",
    )
    for tick_name in ("sample_tick", "status_tick", "metrics_tick", "heartbeat_toggle"):
        if re.search(rf"(?:posedge|negedge)\s+{tick_name}\b", clean):
            raise CheckFailure(f"board top illegally uses {tick_name} as a generated clock")
        if re.search(rf"\.clk\s*\(\s*{tick_name}\s*\)", clean):
            raise CheckFailure(f"board top illegally binds {tick_name} to a clock port")


def validate_platform_wrapper(text: str) -> None:
    instances = parse_instances(text, "system")
    if len(instances) != 1 or instances[0][0] != "u_platform_designer_system":
        raise CheckFailure("Platform Designer wrapper must instantiate generated system exactly once")
    clean = strip_sv_comments(text)
    if re.search(r"\bmodule\s+system\b", clean):
        raise CheckFailure("hand-written Platform Designer wrapper contains a local system stub")


def validate_clock_reset_source(text: str) -> None:
    clean = strip_sv_comments(text)
    compact = re.sub(r"\s+", "", clean)
    for removed in (
        "frame_boundary_o",
        "source_safe_boundary_o",
        "pll_locked_o",
        "reset_request_n_o",
        "clk_core_o",
        "clk_telemetry_o",
        "clk_hps_bridge_o",
        "rst_n_fabric_o",
        "rst_n_core_o",
        "rst_n_telemetry_o",
        "rst_n_hps_bridge_o",
        "SAMPLE_TICK_DIV",
        "STATUS_TICK_DIV",
        "METRICS_TICK_DIV",
        "HEARTBEAT_DIV",
    ):
        forbid_token(clean, removed, "clock/reset RTL")
    forbid_token(compact, "assignpll_locked", "clock/reset RTL")
    for token in (
        "parameterintunsignedBOARD_RESET_RELEASE_CYCLES=1_000_000",
        "parameterlongintunsignedFABRIC_CLK_HZ=50_000_000",
        "parameterlongintunsignedSAMPLE_TICK_HZ=48_000",
        "parameterlongintunsignedSTATUS_TICK_HZ=10",
        "parameterlongintunsignedMETRICS_TICK_HZ=30",
        "parameterlongintunsignedHEARTBEAT_TOGGLE_HZ=2",
        "assignclk_fabric_o=CLOCK_50;",
        "always_ff@(posedgeCLOCK_50ornegedgeKEY[0])begin",
        "assignplatform_async_rst_n=board_reset_release_qualified_n_q&h2f_reset_n_i;",
        "trecap_reset_sync#(.STAGES(RESET_SYNC_STAGES),.RELEASE_ON_NEGEDGE(1'b0))u_platform_reset_sync(",
        ".async_rst_n(platform_async_rst_n)",
        ".rst_n(rst_n_platform_o)",
        "assignsample_tick_sum={1'b0,sample_tick_accum_q}+SAMPLE_TICK_RATE;",
        "assignstatus_tick_sum={1'b0,status_tick_accum_q}+STATUS_TICK_RATE;",
        "assignmetrics_tick_sum={1'b0,metrics_tick_accum_q}+METRICS_TICK_RATE;",
        "assignheartbeat_toggle_sum={1'b0,heartbeat_toggle_accum_q}+HEARTBEAT_TOGGLE_RATE;",
    ):
        require_token(compact, token, "single-domain canonical clock/reset source")

    reset_sync_instances = parse_instances(text, "trecap_reset_sync")
    if len(reset_sync_instances) != 1 or reset_sync_instances[0][0] != "u_platform_reset_sync":
        raise CheckFailure(
            "clock/reset RTL must own exactly one canonical u_platform_reset_sync instance"
        )


def validate_audio_source(text: str) -> None:
    clean = strip_sv_comments(text)
    compact = re.sub(r"\s+", "", clean)
    require_token(clean, "module audio_codec_wrapper", "audio wrapper RTL")
    for forbidden in (
        "DRIVE_XCK_DEBUG_DIVIDER",
        "XCK_DIVIDE",
        "g_xck_debug_divider",
    ):
        forbid_token(clean, forbidden, "audio wrapper fail-closed XCK contract")
    for token in (
        "assignAUD_XCK=audio_mclk_i;",
        "trecap_reset_sync#(.STAGES(SYNC_SAFE),.RELEASE_ON_NEGEDGE(1'b0))u_bclk_rx_reset_sync(",
        ".rst_n(rst_n_bclk_rx)",
        "trecap_reset_sync#(.STAGES(SYNC_SAFE),.RELEASE_ON_NEGEDGE(1'b1))u_bclk_tx_reset_sync(",
        ".rst_n(rst_n_bclk_tx)",
        "always_ff@(posedgeaud_bclkornegedgerst_n_bclk_rx)begin",
        "always_ff@(negedgeaud_bclkornegedgerst_n_bclk_tx)begin",
        "trecap_async_fifo#(.DATA_W(RX_FIFO_DATA_W),.DEPTH(RX_FIFO_DEPTH),.SYNC_STAGES(SYNC_SAFE))u_audio_rx_fifo(",
        "trecap_async_fifo#(.DATA_W(TX_FIFO_DATA_W),.DEPTH(TX_FIFO_DEPTH),.SYNC_STAGES(SYNC_SAFE))u_audio_tx_fifo(",
        "assignrx_fifo_out_ready=rx_fifo_out_valid;",
        "assignlineout_ready_o=lineout_enable_i&&codec_ready_i&&tx_fifo_in_ready;",
        "audio_sample_valid_o<=enable_i&&codec_ready_i;",
        ".src_pulse_i(rx_fifo_wr_overflow_pulse)",
        ".src_pulse_i(bclk_tx_underflow_pulse_q)",
        "audio_rx_overflow_count_o<=sat_inc64(audio_rx_overflow_count_o);",
        "audio_tx_overflow_count_o<=sat_inc64(audio_tx_overflow_count_o);",
        "audio_tx_underflow_count_o<=sat_inc64(audio_tx_underflow_count_o);",
        "bclk_rx_armed_q<=1'b0;",
        "elseif(!bclk_rx_armed_q)begin",
        "bclk_rx_armed_q<=1'b1;",
        "if(!codec_ready_bclk_tx||!bclk_lineout_enabled_q)",
        "elseif(bclk_tx_control_lrck_q!=bclk_tx_lrck_q)begin",
        "bclk_tx_bit_count_q<=BIT_COUNT_W'(1);",
        "bclk_dacdat_q<=bclk_lineout_left_q[AUDIO_SAMPLE_W-1];",
        "bclk_dacdat_q<=bclk_lineout_right_q[AUDIO_SAMPLE_W-1];",
        "elseif(!bclk_lineout_primed_q)begin",
        "bclk_dacdat_q<=1'b0;",
    ):
        require_token(compact, token, "audio wrapper non-stalling/mute contract")
    if compact.count("trecap_reset_sync#(") != 2:
        raise CheckFailure(
            "audio wrapper must own exactly the separate receive- and transmit-edge reset synchronizers"
        )


def validate_adc_source(text: str) -> None:
    clean = strip_sv_comments(text)
    compact = re.sub(r"\s+", "", clean)
    require_token(clean, "module adc_wrapper", "LTC2308 wrapper RTL")

    # Structural transaction ordering: idle-low -> active-high CONVST -> distinct conversion
    # wait -> twelve-clock shift -> acquisition guard. These checks do not prove edge timing.
    for token in (
        "ADC_IDLE,ADC_CONVST,ADC_CONVERT,ADC_SHIFT,ADC_ACQUIRE",
        "ADC_CS_N<=1'b0;",
        "state_q<=ADC_CONVST;ADC_CS_N<=1'b1;",
        "ADC_CONVST:beginADC_CS_N<=1'b1;",
        "ADC_CS_N<=1'b0;state_q<=ADC_CONVERT;",
        "ADC_CONVERT:beginADC_CS_N<=1'b0;ADC_SCLK<=1'b0;",
        "state_q<=ADC_SHIFT;",
        "if(!ADC_SCLK)begin",
        "parameterintunsignedDOUT_SYNC_STAGES=2,",
        "logic[DOUT_SYNC_SAFE-1:0]adc_dout_sync_q;",
        "adc_dout_sync_q<={adc_dout_sync_q[DOUT_SYNC_SAFE-2:0],ADC_DOUT};",
        "ADC_SCLK<=1'b1;rx_shift_q<={rx_shift_q[FRAME_BITS-2:0],adc_dout_sync_q[DOUT_SYNC_SAFE-1]};",
        "if(bit_idx_q==FRAME_LAST)",
        "configured_command_q<=transaction_command_q;",
        "configured_valid_q<=1'b1;",
        "if(result_eligible_q)begin",
        "sample_valid_o<=1'b1;",
        "result_eligible_q<=configured_valid_q&&(configured_command_q==requested_command);",
        "if(ADC_BITS!=12)",
        "if(FRAME_BITS!=ADC_BITS)",
        "if(COMMAND_BITS!=6)",
        "if(DOUT_SYNC_STAGES<2)",
        "if(SCLK_HALF_DIV<(DOUT_SYNC_STAGES+1))",
        "sample_count_o<=sat_inc64(sample_count_o);",
    ):
        require_token(compact, token, "LTC2308 transaction/priming contract")
    for attribute in (
        'async_reg = "true"',
        'preserve = "true"',
        'SYNCHRONIZER_IDENTIFICATION FORCED',
    ):
        require_token(clean, attribute, "LTC2308 ADC_DOUT synchronizer attributes")
    forbid_token(
        compact,
        "rx_shift_q[FRAME_BITS-2:0],ADC_DOUT",
        "LTC2308 raw asynchronous ADC_DOUT capture",
    )

    # Cycle parameters remain tunable, but the source must validate them against CLK_HZ using
    # overflow-resistant 64-bit cross-products. Literal defaults alone are not evidence.
    for token in (
        "localparamlogic[63:0]CLK_HZ_U64=CLK_HZ;",
        "CONVST_HIGH_TIME_SCALED=CONVST_PULSE_CYCLES_U64*NS_PER_SECOND_U64;",
        "CONVERSION_TO_FIRST_SCLK_TIME_SCALED=CONVERSION_TO_FIRST_SCLK_CYCLES_U64*NS_PER_SECOND_U64;",
        "ACQUISITION_FROM_SEVENTH_RISE_TIME_SCALED=ACQUISITION_FROM_SEVENTH_RISE_CYCLES_U64*NS_PER_SECOND_U64;",
        "if(CONVST_HIGH_TIME_SCALED<(CLK_HZ_U64*64'd20))",
        "if(CONVST_HIGH_TIME_SCALED>(CLK_HZ_U64*64'd40))",
        "if(CONVERSION_TO_FIRST_SCLK_TIME_SCALED<(CLK_HZ_U64*64'd1_600))",
        "if(CLK_HZ_U64>(SCLK_HALF_DIV_U64*64'd80_000_000))",
        "if(ACQUISITION_FROM_SEVENTH_RISE_TIME_SCALED<(CLK_HZ_U64*64'd240))",
        "localparamlogic[63:0]SAMPLE_INTERVAL_MIN_CYCLES_U64=(SAMPLE_RATE_HZ==0)?64'd1:(CLK_HZ/SAMPLE_RATE_HZ);",
        "assignsample_rate_sum={1'b0,sample_rate_accum_q}+SAMPLE_EVENT_RATE;",
        "if(sample_rate_sum>=SAMPLE_CLK_RATE)",
        "if(TRANSACTION_CYCLES_U64>=SAMPLE_INTERVAL_MIN_CYCLES_U64)",
    ):
        require_token(compact, token, "LTC2308 wide timing assertion contract")
    for stale_divider in ("SAMPLE_DIV_SAFE", "SAMPLE_DIV_LAST", "sample_div_cnt_q"):
        forbid_token(clean, stale_divider, "LTC2308 exact-average sample scheduler")


def active_filelist_entries(text: str, quartus: bool = False) -> list[str]:
    entries: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "+")):
            continue
        if quartus:
            match = re.fullmatch(r"set_global_assignment\s+-name\s+SYSTEMVERILOG_FILE\s+(.+)", stripped)
            if match:
                entries.append(match.group(1).strip().strip('"'))
        else:
            entries.append(stripped)
    return entries


def validate_filelist(text: str, context: str, quartus: bool = False) -> None:
    entries = active_filelist_entries(text, quartus)
    required = [
        SOURCE_CORE_REL.as_posix(),
        FULL_TOP_REL.as_posix(),
        CLOCK_RESET_REL.as_posix(),
        PD_WRAPPER_REL.as_posix(),
        AUDIO_WRAPPER_REL.as_posix(),
        ADC_WRAPPER_REL.as_posix(),
        BOARD_TOP_REL.as_posix(),
    ]
    for item in required:
        if entries.count(item) != 1:
            raise CheckFailure(f"{context}: must list {item} exactly once")
        if entries.index(item) > entries.index(BOARD_TOP_REL.as_posix()):
            raise CheckFailure(f"{context}: {item} must precede the physical board top")
    if "rtl/top/trecap_core_telemetry_top.sv" in entries:
        raise CheckFailure(f"{context}: includes the standalone second-core composition")
    if any(Path(item).name == "system.sv" for item in entries):
        raise CheckFailure(f"{context}: hand-written filelist claims generated system HDL ownership")


def validate_document(text: str) -> None:
    text = re.sub(r"\s+", " ", text)
    for token in (
        "Step 9",
        "source-only",
        "platform_designer_wrapper",
        "trecap_source_core_integration",
        "trecap_de1soc_full_top",
        "audio_codec_wrapper",
        "adc_wrapper",
        "core y",
        "not functional verification",
        "not a Quartus compile",
        "hardware evidence",
    ):
        require_token(text, token, "Step-9 architecture document")


def check_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise CheckFailure(f"cannot stat checker {path}: {exc}") from exc
    if not mode & stat.S_IXUSR:
        raise CheckFailure(f"checker is not executable: {path}")


def run_checks(repo_root: Path) -> dict[str, Any]:
    paths = (
        CONTRACT_REL,
        SCHEMA_REL,
        DOC_REL,
        BOARD_TOP_REL,
        CLOCK_RESET_REL,
        PD_WRAPPER_REL,
        AUDIO_WRAPPER_REL,
        ADC_WRAPPER_REL,
        SOURCE_CORE_REL,
        FULL_TOP_REL,
        FULL_FILELIST_REL,
        QUARTUS_FILELIST_REL,
    )
    for relative in paths:
        if not (repo_root / relative).is_file():
            raise CheckFailure(f"required Step-9 source file is missing: {relative}")

    contract = load_json(repo_root / CONTRACT_REL)
    schema = load_json(repo_root / SCHEMA_REL)
    schema_engine = validate_contract_schema(contract, schema)
    validate_contract_values(contract)
    validate_board_top(read_text(repo_root / BOARD_TOP_REL))
    validate_clock_reset_source(read_text(repo_root / CLOCK_RESET_REL))
    validate_audio_source(read_text(repo_root / AUDIO_WRAPPER_REL))
    validate_adc_source(read_text(repo_root / ADC_WRAPPER_REL))
    validate_platform_wrapper(read_text(repo_root / PD_WRAPPER_REL))
    validate_filelist(read_text(repo_root / FULL_FILELIST_REL), FULL_FILELIST_REL.as_posix())
    validate_filelist(
        read_text(repo_root / QUARTUS_FILELIST_REL),
        QUARTUS_FILELIST_REL.as_posix(),
        quartus=True,
    )
    validate_document(read_text(repo_root / DOC_REL))
    check_executable(Path(__file__).resolve())
    return {"schema_engine": schema_engine, "scope": "source_only"}


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="Repository root")
    parser.add_argument("--quiet", action="store_true", help="Suppress success output")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve() if args.root else repo_root_from_script()
    try:
        summary = run_checks(root)
    except CheckFailure as exc:
        print(f"check_de1soc_board_top: FAIL: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(
            "check_de1soc_board_top: OK "
            f"scope={summary['scope']} schema={summary['schema_engine']} "
            "(no RTL/functional/PD-generation/Quartus/hardware claim)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
