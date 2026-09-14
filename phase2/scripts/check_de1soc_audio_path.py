#!/usr/bin/env python3
"""Check the source-only Step-16 DE1-SoC LINE-IN audio contract.

This dependency-free gate validates the committed contract/schema, WM8731 I2C
initializer, audio PLL wrapper, I2S/CDC wrapper, physical-top ownership, Rev-H
pin bindings, generated filelists, and LINE-IN profile.  It deliberately does
not compile or simulate RTL, invoke Quartus/TimeQuest, measure clocks, observe
I2C acknowledgements, process live audio, or establish hardware signoff.
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


CONTRACT_REL = Path("config/boards/de1soc_audio_linein.json")
SCHEMA_REL = Path("spec/schemas/de1soc_audio_linein.schema.json")
PLL_REL = Path("rtl/platform/de1soc/audio_pll_wrapper.sv")
I2C_REL = Path("rtl/platform/de1soc/audio_codec_i2c_init.sv")
AUDIO_REL = Path("rtl/platform/de1soc/audio_codec_wrapper.sv")
BOARD_TOP_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
ASYNC_FIFO_REL = Path("rtl/common/async_fifo.sv")
ADAPTER_REL = Path("rtl/sources/trecap_audio_adapter.sv")
PROFILE_REL = Path("config/profiles/de1soc_linein_demo.json")
PINS_REL = Path("constraints/de1soc/pin_assignments.tcl")
FULL_FILELIST_REL = Path("filelists/rtl_de1soc_full.f")
QUARTUS_FILELIST_REL = Path("filelists/quartus_de1soc.qsf.inc")
MODEL_REL = Path("scripts/sim/check_step16_audio_model.py")
CHECKER_REL = Path("scripts/check_de1soc_audio_path.py")

EXPECTED_TOP_LEVEL = {
    "schema": "trecap_phase2_de1soc_audio_linein_v1",
    "file_class": "[1] hand-written Step-16 DE1-SoC LINE-IN audio contract",
    "project": "T_RECAP_Phase2",
    "board": "de1soc",
    "board_revision": "rev_h",
    "contract_stage": "step16_audio_linein_source_implemented",
    "status": (
        "source_implemented_pending_rtl_compile_simulation_quartus_timing_i2c_ack_"
        "clock_measurement_live_audio_and_hardware_evidence"
    ),
}

EXPECTED_OWNERSHIP = {
    "physical_board_top": BOARD_TOP_REL.as_posix(),
    "audio_pll_wrapper": PLL_REL.as_posix(),
    "codec_i2c_initializer": I2C_REL.as_posix(),
    "audio_serial_wrapper": AUDIO_REL.as_posix(),
    "async_fifo_primitive": ASYNC_FIFO_REL.as_posix(),
    "audio_source_adapter": ADAPTER_REL.as_posix(),
    "linein_profile": PROFILE_REL.as_posix(),
    "pin_assignments": PINS_REL.as_posix(),
    "full_board_filelist": FULL_FILELIST_REL.as_posix(),
    "quartus_filelist": QUARTUS_FILELIST_REL.as_posix(),
    "schema_file": SCHEMA_REL.as_posix(),
    "source_checker": CHECKER_REL.as_posix(),
    "behavioral_model": MODEL_REL.as_posix(),
}

EXPECTED_REGISTER_SEQUENCE = [
    (15, 0x000),
    (9, 0x000),
    (0, 0x017),
    (1, 0x017),
    (2, 0x079),
    (3, 0x079),
    (4, 0x012),
    (5, 0x000),
    (6, 0x002),
    (7, 0x042),
    (8, 0x000),
    (9, 0x001),
]

EXPECTED_COUNTERS = {
    "audio_rx_overflow_count_o": (
        "completed_enabled_rx_frame_arrives_while_rx_async_fifo_full"
    ),
    "audio_tx_overflow_count_o": (
        "enabled_lineout_sample_arrives_while_tx_async_fifo_full"
    ),
    "audio_tx_underflow_count_o": (
        "enabled_primed_dac_frame_boundary_requires_sample_while_tx_async_fifo_empty"
    ),
}


class CheckFailure(RuntimeError):
    """Raised when a committed Step-16 source contract is inconsistent."""


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


def strip_sv_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\r\n]*", "", text)


def strip_tcl_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CheckFailure(f"{context} differs from the frozen Step-16 value")


def require_regex(text: str, pattern: str, context: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if match is None:
        raise CheckFailure(f"{context}: required source pattern is missing: {pattern}")
    return match


def forbid_regex(text: str, pattern: str, context: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE):
        raise CheckFailure(f"{context}: forbidden source pattern is present: {pattern}")


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


def resolve_local_ref(schema_root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise CheckFailure(f"fallback schema validator cannot resolve external $ref {ref!r}")
    value: Any = schema_root
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise CheckFailure(f"schema contains unresolved local $ref {ref!r}")
        value = value[part]
    if not isinstance(value, dict):
        raise CheckFailure(f"schema $ref {ref!r} does not resolve to an object")
    return value


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
    if isinstance(expected_type, list):
        if not any(matches_json_type(value, str(item)) for item in expected_type):
            raise CheckFailure(f"{location}: value has the wrong JSON type")
    elif expected_type is not None and not matches_json_type(value, str(expected_type)):
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
            if len(canonical) != len(set(canonical)):
                raise CheckFailure(f"{location}: array items are not unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_schema_fallback(
                    item, item_schema, schema_root, f"{location}[{index}]"
                )
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise CheckFailure(f"{location}: string is shorter than minLength")
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            raise CheckFailure(f"{location}: string does not match schema pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise CheckFailure(f"{location}: number is below schema minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise CheckFailure(f"{location}: number is above schema maximum")


def validate_contract_schema(
    contract: Any, schema: Any, force_fallback: bool
) -> str:
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        raise CheckFailure("contract and schema roots must be JSON objects")
    if jsonschema is not None and not force_fallback:
        try:
            jsonschema.Draft202012Validator(schema).validate(contract)
        except Exception as exc:
            raise CheckFailure(f"contract does not validate against schema: {exc}") from exc
        return "jsonschema"
    validate_schema_fallback(contract, schema, schema)
    return "dependency_free_fallback"


def find_matching_paren(text: str, open_index: int) -> int:
    if open_index >= len(text) or text[open_index] != "(":
        raise CheckFailure("internal SystemVerilog parser expected an opening parenthesis")
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    raise CheckFailure("unterminated SystemVerilog parenthesized construct")


def skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def parse_instances(text: str, module_name: str) -> list[tuple[str, str, str]]:
    """Return (instance name, parameter body, port body) for named instances."""
    clean = strip_sv_comments(text)
    instances: list[tuple[str, str, str]] = []
    for match in re.finditer(rf"\b{re.escape(module_name)}\b", clean):
        index = skip_space(clean, match.end())
        parameters = ""
        if index < len(clean) and clean[index] == "#":
            index = skip_space(clean, index + 1)
            if index >= len(clean) or clean[index] != "(":
                continue
            close = find_matching_paren(clean, index)
            parameters = clean[index + 1 : close]
            index = skip_space(clean, close + 1)
        name_match = re.match(r"[A-Za-z_][A-Za-z0-9_$]*", clean[index:])
        if name_match is None:
            continue
        name = name_match.group(0)
        # Reject the module declaration itself.
        if name == module_name or name == "import":
            continue
        index = skip_space(clean, index + len(name))
        if index >= len(clean) or clean[index] != "(":
            continue
        close = find_matching_paren(clean, index)
        instances.append((name, parameters, clean[index + 1 : close]))
    return instances


def parse_named_ports(body: str) -> dict[str, str]:
    ports: dict[str, str] = {}
    index = 0
    while index < len(body):
        dot = body.find(".", index)
        if dot < 0:
            break
        match = re.match(r"\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(", body[dot:])
        if match is None:
            index = dot + 1
            continue
        name = match.group(1)
        open_index = dot + match.end() - 1
        close_index = find_matching_paren(body, open_index)
        ports[name] = compact(body[open_index + 1 : close_index])
        index = close_index + 1
    return ports


def parse_continuous_assignments(text: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for match in re.finditer(
        r"\bassign\s+([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*([^;]+);",
        strip_sv_comments(text),
        flags=re.MULTILINE | re.DOTALL,
    ):
        assignments[match.group(1)] = compact(match.group(2))
    return assignments


def signal_depends_on(
    assignments: dict[str, str], target: str, source: str, visited: set[str] | None = None
) -> bool:
    if not target or not source:
        return False
    if source in target:
        return True
    visited = set() if visited is None else visited
    if target in visited:
        return False
    visited.add(target)
    expression = assignments.get(target, "")
    if source in expression:
        return True
    identifiers = re.findall(r"\b[A-Za-z_][A-Za-z0-9_$]*\b", expression)
    return any(
        signal_depends_on(assignments, identifier, source, visited)
        for identifier in identifiers
        if identifier in assignments
    )


def validate_contract_values(contract: dict[str, Any]) -> None:
    for key, expected in EXPECTED_TOP_LEVEL.items():
        require_equal(contract.get(key), expected, f"contract.{key}")
    require_equal(contract.get("ownership"), EXPECTED_OWNERSHIP, "contract.ownership")

    board = contract.get("board_codec_contract")
    require(isinstance(board, dict), "contract.board_codec_contract must be an object")
    require_equal(board.get("codec_model"), "WM8731", "codec model")
    require_equal(board.get("codec_control_address_7bit"), "0x1a", "codec address")
    require_equal(board.get("codec_control_bus_hz"), 100_000, "I2C bus rate")
    require_equal(
        board.get("codec_control_mux_select_owner"),
        "HPS_GPIO48_HPS_I2C_CONTROL",
        "codec-control mux owner",
    )
    require_equal(
        board.get("fabric_may_drive_codec_control_mux_select"),
        False,
        "codec-control mux ownership",
    )
    require_equal(
        board.get("fpga_i2c_sclk", {}).get("package_pin"),
        "PIN_J12",
        "FPGA_I2C_SCLK pin",
    )
    require_equal(
        board.get("fpga_i2c_sdat", {}).get("package_pin"),
        "PIN_K12",
        "FPGA_I2C_SDAT pin",
    )

    pll = contract.get("audio_pll_contract")
    require(isinstance(pll, dict), "contract.audio_pll_contract must be an object")
    require_equal(pll.get("reference_clock_hz"), 50_000_000, "PLL reference rate")
    require_equal(pll.get("master_clock_hz"), 12_288_000, "audio MCLK rate")
    require_equal(pll.get("master_clock_multiple_of_sample_rate"), 256, "MCLK/Fs")
    require_equal(pll.get("integer_or_counter_divider_permitted"), False, "PLL policy")

    codec = contract.get("codec_configuration_contract")
    require(isinstance(codec, dict), "codec_configuration_contract must be an object")
    require_equal(codec.get("sample_rate_hz"), 48_000, "codec sample rate")
    require_equal(codec.get("word_width_bits"), 16, "codec word width")
    require_equal(codec.get("serial_format"), "i2s", "codec serial format")
    require_equal(codec.get("clock_role"), "codec_master", "codec clock role")
    sequence = codec.get("register_sequence")
    require(isinstance(sequence, list), "codec register_sequence must be an array")
    actual_sequence = []
    for item in sequence:
        require(isinstance(item, dict), "codec register_sequence entries must be objects")
        actual_sequence.append((item.get("register"), int(str(item.get("value")), 0)))
    require_equal(actual_sequence, EXPECTED_REGISTER_SEQUENCE, "codec register sequence")

    cdc = contract.get("cdc_and_counter_contract")
    require(isinstance(cdc, dict), "cdc_and_counter_contract must be an object")
    require_equal(cdc.get("cdc_primitive"), "trecap_async_fifo", "audio CDC primitive")
    require_equal(cdc.get("minimum_audio_async_fifo_instances"), 2, "audio FIFO count")
    require_equal(cdc.get("counter_width_bits"), 64, "audio counter width")
    require_equal(cdc.get("counter_arithmetic"), "saturating_unsigned", "counter arithmetic")
    counter_entries = cdc.get("counter_outputs")
    require(isinstance(counter_entries, list), "counter_outputs must be an array")
    actual_counters = {
        str(item.get("name")): str(item.get("event"))
        for item in counter_entries
        if isinstance(item, dict)
    }
    require_equal(actual_counters, EXPECTED_COUNTERS, "audio counter semantics")

    evidence = contract.get("evidence_policy")
    require(isinstance(evidence, dict), "contract.evidence_policy must be an object")
    for key, value in evidence.items():
        if key.startswith("source_check_is_"):
            require_equal(value, False, f"evidence_policy.{key}")


def validate_pll(text: str) -> None:
    clean = strip_sv_comments(text)
    compact_text = compact(clean)
    require_regex(clean, r"\bmodule\s+audio_pll_wrapper\b", "audio PLL wrapper")
    for token in (
        "REF_CLK_HZ=50_000_000",
        "AUDIO_MCLK_HZ=12_288_000",
        "(REF_CLK_HZ==50_000_000)&&(AUDIO_MCLK_HZ==12_288_000)",
        "fractional_vco_multiplier(\"true\")",
        "reference_clock_frequency(\"50.0MHz\")",
        "altera_pll#(",
        ")u_audio_altera_pll(",
        "assignaudio_mclk_o=pll_mclk_w;",
        "assignconfig_supported_o=CONFIG_SUPPORTED;",
    ):
        if token not in compact_text:
            raise CheckFailure(f"audio PLL wrapper: required source token is missing: {token}")
    require_regex(clean, r"`ifdef\s+SYNTHESIS", "audio PLL synthesis ownership")
    require_regex(
        clean,
        r"output_clock_frequency0\s*\(\s*\"12\.2880*\s*MHz\"\s*\)",
        "audio PLL generated output frequency",
    )
    require_regex(clean, r"\blocked_o\b", "audio PLL qualified lock output")
    require_regex(clean, r"LOCK_STABLE", "audio PLL stable-lock qualifier")
    require_regex(
        clean,
        r"async_reg\s*=\s*\"true\".*preserve\s*=\s*\"true\".*"
        r"logic\s*\[\s*1\s*:\s*0\s*\]\s*pll_locked_sync_q",
        "audio PLL raw-lock synchronizer attributes",
    )
    require_regex(
        clean,
        r"pll_locked_sync_q\s*<=\s*\{\s*pll_locked_sync_q\s*\[\s*0\s*\]\s*,\s*"
        r"pll_locked_raw_w\s*\}",
        "audio PLL raw-lock two-flop synchronization",
    )
    require_regex(
        clean,
        r"else\s+if\s*\(\s*!pll_locked_sync_q\s*\[\s*1\s*\]\s*\|\|\s*"
        r"!CONFIG_SUPPORTED\s*\)",
        "audio PLL stable-lock qualification uses synchronized lock",
    )
    require_regex(
        clean,
        r"g_unsupported_clock_profile.*pll_mclk_w\s*=\s*1'b0.*pll_locked_raw_w\s*=\s*1'b0",
        "audio PLL unsupported-profile fail-closed behavior",
    )
    forbid_regex(
        clean,
        r"assign\s+(?:audio_mclk_o|pll_mclk_w)\s*=\s*ref_clk_i\s*;",
        "audio PLL pass-through",
    )


def validate_i2c(text: str) -> None:
    clean = strip_sv_comments(text)
    compact_text = compact(clean)
    require_regex(clean, r"\bmodule\s+audio_codec_i2c_init\b", "codec I2C initializer")
    for token in (
        "CLK_HZ=50_000_000",
        "I2C_BUS_HZ=100_000",
        "AUDIO_MCLK_HZ=12_288_000",
        "AUDIO_SAMPLE_RATE_HZ=48_000",
        "AUDIO_WORD_W=16",
        "CODEC_I2C_ADDRESS=7'h1a",
        "MAX_RETRIES=3",
        "CONFIG_WRITE_COUNT=12",
        "transaction_byte={CODEC_I2C_ADDRESS,1'b0};",
        "sda_sync_q<=2'b11;",
        "sda_sync_q<={sda_sync_q[0],FPGA_I2C_SDAT};",
        "assignsampled_ack=(sda_sync_q[1]===1'b0);",
        "ack_error_count_o<=saturating_increment(ack_error_count_o);",
        "retry_count_o<=saturating_increment(retry_count_o);",
        "config_error_sticky_o<=1'b1;",
        "config_done_o<=1'b1;",
    ):
        if token not in compact_text:
            raise CheckFailure(f"codec I2C initializer: required token is missing: {token}")

    for signal, drive in (
        ("FPGA_I2C_SCLK", "scl_drive_low"),
        ("FPGA_I2C_SDAT", "sda_drive_low"),
    ):
        require_regex(
            clean,
            rf"assign\s+{signal}\s*=\s*{drive}\s*\?\s*1'b0\s*:\s*1'bz\s*;",
            f"{signal} open-drain drive",
        )
        for line in clean.splitlines():
            if re.search(rf"assign\s+{signal}\b", line) and "1'b1" in line:
                raise CheckFailure(f"codec I2C initializer: {signal} actively drives logic high")

    for index, (register, value) in enumerate(EXPECTED_REGISTER_SEQUENCE):
        literal = f"{index}:codec_register_word={{7'd{register},9'h{value:03x}}};"
        if literal not in compact_text.lower():
            raise CheckFailure(
                "codec I2C initializer: register sequence entry is missing or reordered: "
                f"index={index} register={register} value=0x{value:03x}"
            )

    for state in (
        "I2C_IDLE",
        "I2C_START_HOLD",
        "I2C_START_LOW",
        "I2C_BIT_LOW",
        "I2C_BIT_HIGH",
        "I2C_ACK_LOW",
        "I2C_ACK_HIGH",
        "I2C_STOP_LOW",
        "I2C_STOP_HIGH",
        "I2C_STOP_RELEASE",
    ):
        require_regex(clean, rf"\b{state}\b", "codec I2C protocol state")
    require_regex(
        clean,
        r"if\s*\(\s*!sampled_ack\s*\).*stop_due_to_nack_q\s*<=\s*1'b1",
        "codec I2C ACK failure path",
    )
    require_regex(
        clean,
        r"if\s*\(\s*config_index_q\s*==\s*CONFIG_INDEX_LAST\s*\).*config_done_o\s*<=\s*1'b1",
        "codec activation completion gate",
    )
    require_regex(
        clean,
        r"busy_o\s*&&\s*\(\s*!enable_i\s*\|\|\s*!bus_grant_i",
        "codec I2C lock/grant abort",
    )
    require_regex(
        clean,
        r"if\s*\(\s*!enable_i\s*\|\|\s*!bus_grant_i\s*\|\|\s*!CONFIG_SUPPORTED\s*\)\s*"
        r"begin\s*config_done_o\s*<=\s*1'b0",
        "codec I2C idle ownership-loss config-done invalidation",
    )
    require_regex(
        clean,
        r"if\s*\(\s*clear_sticky_i\s*\)\s*begin\s*config_done_o\s*<=\s*1'b0\s*;\s*"
        r"config_error_sticky_o\s*<=\s*1'b0",
        "codec I2C explicit clear invalidates config-done and clears sticky error",
    )
    require_equal(
        compact_text.count("config_error_sticky_o<=1'b0;"),
        2,
        "codec I2C sticky-error reset/clear-only ownership",
    )


def _port_is_64_bit_output(clean: str, names: Sequence[str]) -> bool:
    alternatives = "|".join(re.escape(name) for name in names)
    return bool(
        re.search(
            rf"output\s+(?:logic|wire)?\s*\[\s*63\s*:\s*0\s*\]\s*(?:{alternatives})\b",
            clean,
            flags=re.IGNORECASE,
        )
    )


def validate_audio_wrapper(text: str) -> None:
    clean = strip_sv_comments(text)
    require_regex(clean, r"\bmodule\s+audio_codec_wrapper\b", "audio serial wrapper")
    fifo_instances = parse_instances(clean, "trecap_async_fifo")
    require(
        len(fifo_instances) >= 2,
        f"audio serial wrapper: expected at least two trecap_async_fifo instances, found {len(fifo_instances)}",
    )
    rx_instances = [item for item in fifo_instances if "rx" in item[0].lower()]
    tx_instances = [item for item in fifo_instances if "tx" in item[0].lower()]
    require(rx_instances, "audio serial wrapper: RX async-FIFO instance name is missing")
    require(tx_instances, "audio serial wrapper: TX async-FIFO instance name is missing")

    rx_ports = parse_named_ports(rx_instances[0][2])
    tx_ports = parse_named_ports(tx_instances[0][2])
    require("aud_bclk" in rx_ports.get("wr_clk", "").lower(), "RX FIFO write clock must be AUD_BCLK")
    require("clk" in rx_ports.get("rd_clk", "").lower(), "RX FIFO read clock must be fabric clk")
    require("clk" in tx_ports.get("wr_clk", "").lower(), "TX FIFO write clock must be fabric clk")
    require("aud_bclk" in tx_ports.get("rd_clk", "").lower(), "TX FIFO read clock must be AUD_BCLK")
    require(
        bool(rx_ports.get("wr_overflow_pulse_o")),
        "RX FIFO overflow pulse must be connected",
    )
    require(
        bool(tx_ports.get("wr_overflow_pulse_o")),
        "TX FIFO overflow pulse must be connected",
    )
    # A raw FIFO read-underflow pulse is acceptable, but the preferred implementation requests
    # reads only when valid and counts a semantic underflow at an enabled DAC frame boundary.
    # That avoids counting BCLK cycles or disabled/muted intervals as missing audio frames.
    if not tx_ports.get("rd_underflow_pulse_o"):
        require_regex(
            clean,
            r"tx_frame_start_left.*tx_fifo_(?:out_valid|entry_current).*"
            r"bclk_tx_underflow_pulse_q\s*<=\s*1'b1",
            "TX semantic frame-boundary underflow",
        )
        require_regex(
            clean,
            r"u_tx_underflow_event_cdc.*src_pulse_i\s*\(\s*bclk_tx_underflow_pulse_q\s*\)",
            "TX underflow event CDC",
        )

    require_regex(
        clean,
        r"always_ff\s*@\s*\(\s*posedge\s+aud_bclk",
        "I2S receive edge",
    )
    require_regex(
        clean,
        r"always_ff\s*@\s*\(\s*negedge\s+aud_bclk",
        "I2S transmit edge",
    )
    require_regex(clean, r"I2S_DELAY_BITS\s*=\s*1", "I2S one-bit delay")
    require_regex(clean, r"\blogic\s+bclk_rx_armed_q\s*;", "I2S RX boundary arm state")
    require(
        len(re.findall(r"bclk_rx_armed_q\s*<=\s*1'b0", clean)) >= 2,
        "audio serial wrapper: RX arm must clear on reset and disabled capture",
    )
    require_regex(
        clean,
        r"else\s+if\s*\(\s*!bclk_rx_armed_q\s*\).*"
        r"if\s*\(\s*aud_adclrck\s*!=\s*bclk_lrck_q\s*\).*"
        r"bclk_rx_armed_q\s*<=\s*1'b1.*bclk_left_seen_q\s*<=\s*1'b0",
        "I2S RX fresh-LRCK alignment before first stereo frame",
    )
    require_regex(
        clean,
        r"else\s+if\s*\(\s*bclk_tx_control_lrck_q\s*!=\s*bclk_tx_lrck_q\s*\).*"
        r"bclk_dacdat_q\s*<=\s*bclk_lineout_left_q\s*\[\s*AUDIO_SAMPLE_W\s*-\s*1\s*\].*"
        r"bclk_dacdat_q\s*<=\s*bclk_lineout_right_q\s*\[\s*AUDIO_SAMPLE_W\s*-\s*1\s*\]",
        "I2S TX post-prefetch atomic stereo launch",
    )
    forbid_regex(
        clean,
        r"else\s+if\s*\(\s*aud_daclrck\s*!=\s*bclk_tx_lrck_q\s*\)",
        "I2S TX raw-LRCK sampling on its falling-edge launch boundary",
    )

    counter_aliases = {
        "audio_rx_overflow_count_o": (
            "audio_rx_overflow_count_o",
            "rx_overflow_count_o",
        ),
        "audio_tx_overflow_count_o": (
            "audio_tx_overflow_count_o",
            "tx_overflow_count_o",
        ),
        "audio_tx_underflow_count_o": (
            "audio_tx_underflow_count_o",
            "tx_underflow_count_o",
        ),
    }
    for contract_name, aliases in counter_aliases.items():
        require(
            _port_is_64_bit_output(clean, aliases),
            f"audio serial wrapper: {contract_name} must be a 64-bit output",
        )
        require(
            any(clean.count(alias) >= 2 for alias in aliases),
            f"audio serial wrapper: {contract_name} lacks update/use logic",
        )
    require_regex(
        clean,
        r"function\s+automatic\s+logic\s*\[\s*63\s*:\s*0\s*\]\s+[A-Za-z0-9_]*(?:sat|increment)[A-Za-z0-9_]*",
        "audio counter saturating increment",
    )
    require_regex(clean, r"\bclear_sticky_i\b", "audio counter clear owner")

    # Disabling capture must not leave a pre-disable FIFO payload to become the first sample of a
    # later source epoch.  Accept either continuous drain/discard or an explicit FIFO flush/reset.
    stale_frame_policy = bool(
        re.search(
            r"(?:rx_[A-Za-z0-9_]*(?:discard|drain|flush)|"
            r"(?:out_ready_i|rx_fifo_[A-Za-z0-9_]*ready)[^;]*(?:1'b1|!enable_i)|"
            r"assign\s+rx_fifo_out_ready\s*=\s*rx_fifo_out_valid|"
            r"rx_[A-Za-z0-9_]*rst[^;]*enable_i)",
            clean,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    require(stale_frame_policy, "audio serial wrapper: stale RX epoch prevention is not visible")


def validate_board_top(text: str) -> None:
    clean = strip_sv_comments(text)
    assignments = parse_continuous_assignments(clean)
    require_regex(clean, r"\bmodule\s+de1_soc_trecap_top\b", "physical board top")
    require_regex(
        clean,
        r"\boutput\s+wire\s+FPGA_I2C_SCLK\b",
        "board top FPGA_I2C_SCLK port",
    )
    require_regex(
        clean,
        r"\binout\s+wire\s+FPGA_I2C_SDAT\b",
        "board top FPGA_I2C_SDAT port",
    )

    expected_instances = {
        "audio_pll_wrapper": "u_audio_pll_wrapper",
        "audio_codec_i2c_init": "u_audio_codec_i2c_init",
        "audio_codec_wrapper": "u_audio_codec_wrapper",
    }
    parsed: dict[str, tuple[str, str, str]] = {}
    for module_name, expected_name in expected_instances.items():
        instances = parse_instances(clean, module_name)
        require(
            len(instances) == 1,
            f"board top: expected one {module_name} instance, found {len(instances)}",
        )
        require_equal(instances[0][0], expected_name, f"board top {module_name} instance")
        parsed[module_name] = instances[0]

    pll_ports = parse_named_ports(parsed["audio_pll_wrapper"][2])
    i2c_ports = parse_named_ports(parsed["audio_codec_i2c_init"][2])
    audio_ports = parse_named_ports(parsed["audio_codec_wrapper"][2])
    require("clock_50" in pll_ports.get("ref_clk_i", "").lower() or "clk_fabric" in pll_ports.get("ref_clk_i", "").lower(), "board top: PLL reference is not CLOCK_50/fabric alias")
    require(bool(pll_ports.get("audio_mclk_o")), "board top: PLL MCLK output is unbound")
    require(bool(pll_ports.get("locked_o")), "board top: PLL lock output is unbound")
    for port in ("FPGA_I2C_SCLK", "FPGA_I2C_SDAT"):
        require_equal(i2c_ports.get(port), port, f"board top I2C binding {port}")
    require(bool(i2c_ports.get("enable_i")), "board top: codec initializer enable is unbound")
    require(bool(i2c_ports.get("config_done_o")), "board top: codec config-done is unbound")

    compact_text = compact(clean)
    require_regex(
        clean,
        r"async_reg\s*=\s*\"true\".*preserve\s*=\s*\"true\".*"
        r"logic\s*\[\s*1\s*:\s*0\s*\]\s*audio_i2c_bus_grant_sync_q",
        "board top HPS codec-bus grant synchronizer attributes",
    )
    forbid_regex(clean, r"assign\s+AUD_XCK\s*=\s*1'b0\s*;", "board top AUD_XCK")
    forbid_regex(clean, r"assign\s+HPS_I2C_CONTROL\s*=", "HPS-owned codec-bus mux select")
    pll_body = compact(parsed["audio_pll_wrapper"][2])
    require(
        "AUD_XCK" in pll_body or "AUD_XCK" in compact_text,
        "board top: AUD_XCK is not connected to the audio PLL path",
    )

    pll_lock_net = pll_ports.get("locked_o", "")
    i2c_enable = i2c_ports.get("enable_i", "")
    require(
        pll_lock_net == i2c_enable
        or pll_lock_net in i2c_enable
        or bool(re.search(rf"{re.escape(i2c_enable)}[^;]*{re.escape(pll_lock_net)}", compact_text))
        or bool(re.search(rf"{re.escape(pll_lock_net)}[^;]*{re.escape(i2c_enable)}", compact_text)),
        "board top: codec initialization is not visibly qualified by PLL lock",
    )

    config_done_net = i2c_ports.get("config_done_o", "")
    capture_enable = audio_ports.get("enable_i", "")
    require(
        config_done_net in capture_enable
        or signal_depends_on(assignments, capture_enable, config_done_net),
        "board top: audio capture enable is not visibly qualified by codec config-done",
    )
    for readiness_gate in ("!audio_i2c_start", "!audio_i2c_busy"):
        require(
            readiness_gate in assignments.get("audio_codec_ready", ""),
            f"board top: audio_codec_ready lacks re-initialization gate {readiness_gate}",
        )

    counter_aliases = {
        "audio_rx_overflow_count_o": ("audio_rx_overflow_count_o", "rx_overflow_count_o"),
        "audio_tx_overflow_count_o": ("audio_tx_overflow_count_o", "tx_overflow_count_o"),
        "audio_tx_underflow_count_o": ("audio_tx_underflow_count_o", "tx_underflow_count_o"),
    }
    for contract_name, aliases in counter_aliases.items():
        binding = next((audio_ports.get(alias) for alias in aliases if alias in audio_ports), None)
        require(bool(binding), f"board top: {contract_name} output is not bound")


def validate_profile(profile: Any) -> None:
    require(isinstance(profile, dict), "LINE-IN profile root must be an object")
    require_equal(profile.get("profile_name"), "de1soc_linein_demo", "LINE-IN profile name")
    require_equal(profile.get("sample_rate_hz"), 48_000, "LINE-IN profile sample rate")
    input_cfg = profile.get("input")
    require(isinstance(input_cfg, dict), "LINE-IN profile input must be an object")
    require_equal(input_cfg.get("kind"), "audio_wrapper", "LINE-IN input kind")
    require_equal(input_cfg.get("source_mode"), "audio_wrapper", "LINE-IN source mode")
    audio = input_cfg.get("audio")
    require(isinstance(audio, dict), "LINE-IN profile input.audio must be an object")
    expected_scalars = {
        "codec_sample_width": 16,
        "channel_select": "left",
        "input_scale_rule": "signed_rnd_shr_Baudio_minus_N",
        "master_clock_hz": 12_288_000,
    }
    for key, expected in expected_scalars.items():
        require_equal(audio.get(key), expected, f"LINE-IN profile audio.{key}")
    require_equal(
        audio.get("codec_control"),
        {
            "enable": True,
            "codec_model": "wm8731",
            "i2c_bus": "fpga_i2c",
            "i2c_address_7bit": "0x1a",
            "serial_format": "i2s",
            "sample_rate_hz": 48_000,
            "word_width_bits": 16,
            "clock_role": "codec_master",
        },
        "LINE-IN profile audio.codec_control",
    )
    require_equal(
        audio.get("audio_pll"),
        {
            "enable": True,
            "reference_clock": "CLOCK_50",
            "reference_clock_hz": 50_000_000,
            "output_clock": "AUD_XCK",
            "output_clock_hz": 12_288_000,
        },
        "LINE-IN profile audio.audio_pll",
    )
    require_equal(
        audio.get("hardware_gate"),
        {
            "codec_init_requires_pll_locked": True,
            "audio_capture_requires_config_done": True,
        },
        "LINE-IN profile audio.hardware_gate",
    )


def validate_pins(text: str) -> None:
    clean = strip_tcl_comments(text)
    for pin, signal in (("PIN_J12", "FPGA_I2C_SCLK"), ("PIN_K12", "FPGA_I2C_SDAT")):
        matches = re.findall(
            rf"^\s*trecap_pin\s+{pin}\s+(?:\{{)?{signal}(?:\}})?(?:\s|$)",
            clean,
            flags=re.MULTILINE,
        )
        require(len(matches) == 1, f"pin assignments: expected one {signal} -> {pin} binding")
    forbid_regex(
        clean,
        r"trecap_pullup\s+(?:\{)?FPGA_I2C_(?:SCLK|SDAT)(?:\})?",
        "FPGA I2C external-pullup policy",
    )


def active_filelist_entries(text: str, quartus: bool) -> list[str]:
    entries: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "+")):
            continue
        if quartus:
            match = re.fullmatch(
                r"set_global_assignment\s+-name\s+SYSTEMVERILOG_FILE\s+(.+)", stripped
            )
            if match:
                entries.append(match.group(1).strip().strip('"'))
        else:
            entries.append(stripped)
    return entries


def validate_filelist(text: str, context: str, quartus: bool) -> None:
    entries = active_filelist_entries(text, quartus)
    required = [
        PLL_REL.as_posix(),
        I2C_REL.as_posix(),
        AUDIO_REL.as_posix(),
        BOARD_TOP_REL.as_posix(),
    ]
    for item in required:
        require(entries.count(item) == 1, f"{context}: must list {item} exactly once")
    require(
        entries.index(PLL_REL.as_posix()) < entries.index(AUDIO_REL.as_posix()),
        f"{context}: audio PLL wrapper must precede audio serial wrapper",
    )
    require(
        entries.index(I2C_REL.as_posix()) < entries.index(AUDIO_REL.as_posix()),
        f"{context}: codec I2C initializer must precede audio serial wrapper",
    )
    require(
        entries.index(AUDIO_REL.as_posix()) < entries.index(BOARD_TOP_REL.as_posix()),
        f"{context}: audio wrappers must precede physical board top",
    )


def check_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise CheckFailure(f"cannot stat checker/model {path}: {exc}") from exc
    require(bool(mode & stat.S_IXUSR), f"checker/model is not executable: {path}")


def run_checks(repo_root: Path, force_fallback: bool) -> tuple[str, int]:
    required_paths = (
        CONTRACT_REL,
        SCHEMA_REL,
        PLL_REL,
        I2C_REL,
        AUDIO_REL,
        BOARD_TOP_REL,
        ASYNC_FIFO_REL,
        ADAPTER_REL,
        PROFILE_REL,
        PINS_REL,
        FULL_FILELIST_REL,
        QUARTUS_FILELIST_REL,
        MODEL_REL,
        CHECKER_REL,
    )
    missing = [rel.as_posix() for rel in required_paths if not (repo_root / rel).is_file()]
    if missing:
        raise CheckFailure(f"required Step-16 source files are missing: {missing}")

    contract = load_json(repo_root / CONTRACT_REL)
    schema = load_json(repo_root / SCHEMA_REL)
    engine = validate_contract_schema(contract, schema, force_fallback)
    validate_contract_values(contract)
    validate_pll(read_text(repo_root / PLL_REL))
    validate_i2c(read_text(repo_root / I2C_REL))
    validate_audio_wrapper(read_text(repo_root / AUDIO_REL))
    validate_board_top(read_text(repo_root / BOARD_TOP_REL))
    validate_profile(load_json(repo_root / PROFILE_REL))
    validate_pins(read_text(repo_root / PINS_REL))
    validate_filelist(
        read_text(repo_root / FULL_FILELIST_REL), FULL_FILELIST_REL.as_posix(), False
    )
    validate_filelist(
        read_text(repo_root / QUARTUS_FILELIST_REL), QUARTUS_FILELIST_REL.as_posix(), True
    )
    check_executable(repo_root / CHECKER_REL)
    check_executable(repo_root / MODEL_REL)
    return engine, len(required_paths)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
        print(f"check_de1soc_audio_path: ERROR: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(
            "check_de1soc_audio_path: PASS "
            f"({checked_count} committed source/contract files; schema={engine}; source-only)"
        )
        print(
            "check_de1soc_audio_path: no RTL compile/native simulation, Quartus/TimeQuest, "
            "PLL measurement, I2C ACK, live-audio, or hardware evidence was produced"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
