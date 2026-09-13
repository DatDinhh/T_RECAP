#!/usr/bin/env python3
"""Check the source-only Step-17 DE1-SoC LTC2308 live-ADC contract.

This dependency-free gate validates the frozen contract/schema/profile, Rev-H
pin identity, LTC2308 timing and command structure, ADC_DOUT synchronization,
single-domain sample publication, adapter/source-mux integration, telemetry
sample-rate binding, and generated source lists.  It deliberately does not
compile or simulate RTL, invoke Quartus/TimeQuest, measure post-fit I/O timing,
characterize the analog path, observe a live converter, or establish hardware
signoff.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    import jsonschema  # type: ignore[import-not-found]
except ImportError:
    jsonschema = None  # type: ignore[assignment]


CONTRACT_REL = Path("config/boards/de1soc_adc_live.json")
SCHEMA_REL = Path("spec/schemas/de1soc_adc_live.schema.json")
PROFILE_REL = Path("config/profiles/de1soc_adc_demo.json")
RUNTIME_SCHEMA_REL = Path("spec/schemas/runtime_profile.schema.json")
ADC_REL = Path("rtl/platform/de1soc/adc_wrapper.sv")
BOARD_TOP_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
ADAPTER_REL = Path("rtl/sources/trecap_adc_adapter.sv")
MUX_REL = Path("rtl/sources/trecap_source_mux.sv")
SOURCE_CORE_REL = Path("rtl/top/trecap_source_core_integration.sv")
PINS_REL = Path("constraints/de1soc/pin_assignments.tcl")
CLOCKS_REL = Path("constraints/de1soc/clocks.sdc")
FULL_FILELIST_REL = Path("filelists/rtl_de1soc_full.f")
QUARTUS_FILELIST_REL = Path("filelists/quartus_de1soc.qsf.inc")
MODEL_REL = Path("scripts/sim/check_step17_adc_model.py")
CHECKER_REL = Path("scripts/check_de1soc_adc_path.py")

EXPECTED_TOP_LEVEL = {
    "schema": "trecap_phase2_de1soc_adc_live_v1",
    "file_class": "[1] hand-written Step-17 DE1-SoC live-ADC contract",
    "project": "T_RECAP_Phase2",
    "board": "de1soc",
    "board_revision": "rev_h",
    "contract_stage": "step17_adc_live_source_implemented",
    "status": (
        "source_implemented_pending_native_rtl_simulation_quartus_timing_post_fit_"
        "io_measurement_analog_characterization_and_hardware_evidence"
    ),
}

EXPECTED_OWNERSHIP = {
    "physical_board_top": BOARD_TOP_REL.as_posix(),
    "adc_protocol_wrapper": ADC_REL.as_posix(),
    "adc_source_adapter": ADAPTER_REL.as_posix(),
    "source_mux": MUX_REL.as_posix(),
    "source_core_owner": SOURCE_CORE_REL.as_posix(),
    "adc_profile": PROFILE_REL.as_posix(),
    "runtime_profile_schema": RUNTIME_SCHEMA_REL.as_posix(),
    "pin_assignments": PINS_REL.as_posix(),
    "clock_constraints": CLOCKS_REL.as_posix(),
    "full_board_filelist": FULL_FILELIST_REL.as_posix(),
    "quartus_filelist": QUARTUS_FILELIST_REL.as_posix(),
    "schema_file": SCHEMA_REL.as_posix(),
    "source_checker": CHECKER_REL.as_posix(),
    "behavioral_model": MODEL_REL.as_posix(),
}

EXPECTED_PINS = [
    {
        "top_port": "ADC_CS_N",
        "package_pin": "PIN_AJ4",
        "device_signal": "CONVST",
        "direction": "fpga_output",
    },
    {
        "top_port": "ADC_DIN",
        "package_pin": "PIN_AK4",
        "device_signal": "SDI",
        "direction": "fpga_output",
    },
    {
        "top_port": "ADC_DOUT",
        "package_pin": "PIN_AK3",
        "device_signal": "SDO",
        "direction": "fpga_input",
    },
    {
        "top_port": "ADC_SCLK",
        "package_pin": "PIN_AK2",
        "device_signal": "SCK",
        "direction": "fpga_output",
    },
]

CHANNEL_COMMANDS = (0x22, 0x32, 0x26, 0x36, 0x2A, 0x3A, 0x2E, 0x3E)

EXPECTED_PROFILE_ADC = {
    "device_model": "ltc2308",
    "sample_width_bits": 12,
    "sample_format": "unsigned_straight_binary",
    "input_mode": "single_ended",
    "polarity": "unipolar",
    "power_mode": "awake",
    "input_range_volts": "0_to_4.096",
    "zero_code": 2048,
    "input_scale_rule": "unsigned_midscale_subtract_then_signed_rnd_shr_Badc_minus_N",
    "channel_select": "sw6_4_latched_on_source_entry",
    "default_channel": 0,
    "channel_change_policy": "leave_and_reenter_adc_source",
    "first_result_policy": "prime_and_discard_previous_configuration",
    "sampling_mode_select": "sw7_low_continuous_high_key2_manual",
    "continuous_sample_rate_hz": 100_000,
    "serial_clock_hz": 2_500_000,
    "dc_block_enable": False,
}

FALSE_EVIDENCE_KEYS = (
    "source_check_is_native_rtl_compile",
    "source_check_is_native_rtl_simulation",
    "source_check_is_quartus_compile",
    "source_check_is_timing_closure",
    "source_check_is_post_fit_io_timing_measurement",
    "source_check_is_analog_accuracy_or_noise_measurement",
    "source_check_is_live_adc_evidence",
    "source_check_is_hardware_signoff",
)


class CheckFailure(RuntimeError):
    """Raised when committed Step-17 source violates the frozen contract."""


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckFailure(f"cannot read {path}: {exc}") from exc


def _reject_duplicates(path: Path):
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CheckFailure(f"duplicate JSON key in {path}: {key!r}")
            result[key] = value
        return result

    return hook


def load_json(path: Path) -> Any:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CheckFailure(f"UTF-8 BOM is forbidden: {path}")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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
        raise CheckFailure(f"{context} differs from the frozen Step-17 value")


def require_token(text: str, token: str, context: str) -> None:
    if token not in text:
        raise CheckFailure(f"{context}: required source token is missing: {token}")


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
    raise CheckFailure(f"unsupported fallback JSON type {type_name!r}")


def validate_schema_fallback(value: Any, schema: dict[str, Any], location: str = "$") -> None:
    if "const" in schema and value != schema["const"]:
        raise CheckFailure(f"{location}: value does not match schema const")
    expected_type = schema.get("type")
    if expected_type is not None and not matches_json_type(value, str(expected_type)):
        raise CheckFailure(f"{location}: wrong JSON type")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise CheckFailure(f"{location}: missing required property {key}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise CheckFailure(f"{location}: unexpected properties: {extra}")
        for key, child in properties.items():
            if key in value and isinstance(child, dict):
                validate_schema_fallback(value[key], child, f"{location}.{key}")


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
    validate_schema_fallback(contract, schema)
    return "dependency_free_fallback"


def validate_contract(contract: dict[str, Any]) -> None:
    for key, expected in EXPECTED_TOP_LEVEL.items():
        require_equal(contract.get(key), expected, f"contract.{key}")
    require_equal(contract.get("ownership"), EXPECTED_OWNERSHIP, "contract.ownership")

    authority = contract.get("protocol_authority", {})
    require_equal(
        authority.get("device_datasheet"),
        "https://www.analog.com/media/en/technical-documentation/data-sheets/2308fc.pdf",
        "contract.protocol_authority.device_datasheet",
    )
    require_equal(
        authority.get("cross_revision_ad7928_or_other_adc_compatibility_claimed"),
        False,
        "contract cross-revision policy",
    )

    board = contract.get("board_adc_contract", {})
    for key, expected in {
        "device_model": "LTC2308",
        "channel_count": 8,
        "resolution_bits": 12,
        "maximum_device_sample_rate_hz": 500_000,
        "board_input_range_volts": "0_to_4.096",
        "io_standard": "3.3-V LVTTL",
        "adc_cs_n_name_is_active_low_chip_select": False,
        "adc_cs_n_electrical_role": "active_high_CONVST_idle_low",
    }.items():
        require_equal(board.get(key), expected, f"contract.board_adc_contract.{key}")
    require_equal(board.get("pins"), EXPECTED_PINS, "contract.board_adc_contract.pins")

    timing = contract.get("serial_timing_contract", {})
    expected_timing = {
        "fabric_clock_hz": 50_000_000,
        "fabric_clock_period_ns": 20,
        "adc_sclk_half_div": 10,
        "adc_sclk_hz": 2_500_000,
        "adc_sclk_idle_level": 0,
        "adc_sclk_high_time_ns": 200,
        "adc_sclk_low_time_ns": 200,
        "device_sclk_max_hz": 40_000_000,
        "convst_pulse_cycles": 2,
        "convst_high_time_ns": 40,
        "device_convst_high_min_ns": 20,
        "best_performance_convst_high_max_ns": 40,
        "conversion_wait_cycles": 80,
        "conversion_to_first_sclk_rise_cycles": 92,
        "conversion_to_first_sclk_rise_ns": 1840,
        "device_conversion_time_max_ns": 1600,
        "serial_result_bits": 12,
        "serial_command_bits": 6,
        "acquisition_guard_cycles": 12,
        "seventh_sclk_rise_to_next_convst_min_cycles": 122,
        "seventh_sclk_rise_to_next_convst_min_ns": 2440,
        "device_acquisition_time_min_ns": 240,
        "transaction_cycles": 334,
        "transaction_time_ns": 6680,
        "reentry_recovery_cycles_after_enable_or_abort": 92,
        "reentry_recovery_time_ns": 1840,
    }
    for key, expected in expected_timing.items():
        require_equal(timing.get(key), expected, f"contract.serial_timing_contract.{key}")
    require_equal(
        timing.get("unsupported_well_formed_parameter_configuration_behavior"),
        "fail_closed_idle_pins_no_requests_no_samples",
        "contract fail-closed timing behavior",
    )
    require_equal(
        timing.get("degenerate_zero_width_parameter_overrides_are_outside_module_abi"),
        True,
        "contract degenerate-width ABI boundary",
    )
    require_equal(
        timing.get("sdo_transition_edge"),
        "B11_valid_after_conversion_then_B10_to_B0_change_after_falling_ADC_SCLK",
        "contract SDO edge wording",
    )

    channel = contract.get("channel_command_contract", {})
    require_equal(
        channel.get("command_formula"),
        "{1,channel[0],channel[2],channel[1],1,0}",
        "contract channel command formula",
    )
    commands = channel.get("channel_commands")
    require(isinstance(commands, list) and len(commands) == 8, "channel command table must have 8 rows")
    for index, expected in enumerate(CHANNEL_COMMANDS):
        row = commands[index]
        require_equal(row.get("channel"), index, f"channel table row {index}")
        require_equal(int(row.get("command_hex"), 16), expected, f"channel {index} command")
        require_equal(int(row.get("command_binary"), 2), expected, f"channel {index} bits")
    require_equal(channel.get("sleep_bit_always_zero"), True, "contract SLP policy")
    require_equal(channel.get("sleep_wakeup_delay_applicable"), False, "contract wake policy")
    require_equal(
        channel.get("unsupported_input_mode_polarity_or_sleep_command"),
        "reject_set_protocol_error_no_transaction",
        "contract unsupported-command policy",
    )
    require_equal(
        channel.get("first_result_after_reset_enable_abort_or_command_change"),
        "discard",
        "contract priming policy",
    )

    sample = contract.get("sample_format_contract", {})
    for key, expected in {
        "device_output_format": "unsigned_straight_binary",
        "raw_code_min": 0,
        "raw_code_max": 4095,
        "default_zero_code": 2048,
        "centered_min": -2048,
        "centered_max": 2047,
        "core_sample_width_bits": 12,
        "raw_sample_counter_width_bits": 64,
        "raw_sample_counter_arithmetic": "saturating_unsigned",
        "raw_sample_counter_clear": "hard_reset_only",
    }.items():
        require_equal(sample.get(key), expected, f"contract.sample_format_contract.{key}")

    sampling = contract.get("sampling_contract", {})
    require_equal(sampling.get("continuous_sample_rate_hz"), 100_000, "ADC sample rate")
    require_equal(sampling.get("scheduler_fabric_cycles_per_request"), 500, "ADC cadence")
    require_equal(sampling.get("transaction_must_finish_before_next_request"), True, "ADC fit")

    cdc = contract.get("cdc_contract", {})
    for key, expected in {
        "controller_clock_domain": "clk_fabric_50mhz",
        "adc_sclk_is_internal_rtl_clock": False,
        "asynchronous_input": "ADC_DOUT",
        "dout_synchronizer_stages": 2,
        "raw_adc_dout_direct_payload_capture_permitted": False,
        "sample_data_and_valid_registered_together_in_fabric_domain": True,
        "post_wrapper_multibit_cdc_required": False,
        "independent_multibit_payload_synchronizers_permitted": False,
        "separate_adc_clock_domain_if_introduced_requires_async_fifo": True,
    }.items():
        require_equal(cdc.get(key), expected, f"contract.cdc_contract.{key}")

    integration = contract.get("source_integration_contract", {})
    for key, expected in {
        "wrapper_instance": "u_adc_wrapper",
        "adapter_instance": "u_adc_adapter",
        "source_mux_instance": "u_source_mux",
        "source_mode": "TSRC_ADC_LIVE",
        "board_channel_latch_guard_cycles_before_request_input": 1,
        "wrapper_reentry_recovery_cycles_before_request_acceptance": 92,
        "requests_during_reentry_recovery": "reject_set_request_overrun_sticky",
        "telemetry_sample_rate_binding": "TSRC_ADC_LIVE_100000_otherwise_48000",
        "telemetry_adc_sample_rate_hz": 100_000,
        "telemetry_non_adc_sample_rate_hz": 48_000,
        "adc_may_block_bram_replay_or_audio_milestones": False,
        "bram_replay_remains_correctness_authority": True,
    }.items():
        require_equal(integration.get(key), expected, f"contract.source_integration_contract.{key}")

    fault = contract.get("fault_contract", {})
    require_equal(
        fault.get("request_overrun_sticky_event"),
        "scheduler_or_manual_request_attempt_occurs_during_reentry_recovery_or_while_protocol_state_not_idle",
        "contract request-overrun event",
    )
    require_equal(
        fault.get("protocol_error_sticky_event"),
        "illegal_state_or_unsupported_protocol_configuration_or_unsupported_runtime_command",
        "contract protocol-error event",
    )
    require_equal(
        fault.get("clear_sticky_does_not_clear_lifetime_sample_count"),
        True,
        "contract counter clear policy",
    )

    profile = contract.get("profile_contract", {})
    for key, expected in {
        "profile_name": "de1soc_adc_demo",
        "input_kind": "adc_live",
        "source_mode": "adc_live",
        "sample_rate_hz": 100_000,
        "serial_clock_hz": 2_500_000,
        "default_channel": 0,
        "profile_is_build_and_bringup_selection_not_runtime_hardware_evidence": True,
    }.items():
        require_equal(profile.get(key), expected, f"contract.profile_contract.{key}")

    evidence = contract.get("evidence_policy", {})
    require_equal(evidence.get("source_checker"), CHECKER_REL.as_posix(), "evidence checker")
    require_equal(evidence.get("behavioral_model"), MODEL_REL.as_posix(), "evidence model")
    for key in FALSE_EVIDENCE_KEYS:
        require_equal(evidence.get(key), False, f"contract.evidence_policy.{key}")

    invariants = contract.get("invariants")
    require(isinstance(invariants, list) and len(invariants) >= 8, "contract invariants are incomplete")


def validate_profile(profile: dict[str, Any]) -> None:
    require_equal(
        set(profile),
        {
            "schema",
            "profile_kind",
            "profile_name",
            "description",
            "build",
            "contract_refs",
            "input",
            "sample_rate_hz",
            "telemetry_profile",
            "transport",
            "transport_version_major",
            "transport_version_minor",
        },
        "ADC profile top-level keys",
    )
    for key, expected in {
        "schema": "trecap_phase2_runtime_profile_v1",
        "profile_kind": "build",
        "profile_name": "de1soc_adc_demo",
        "sample_rate_hz": 100_000,
        "telemetry_profile": "config/profiles/telemetry_full_demo.json",
        "transport_version_major": 1,
        "transport_version_minor": 8,
    }.items():
        require_equal(profile.get(key), expected, f"profile.{key}")
    require_equal(
        profile.get("build"),
        {
            "target": "de1soc_full",
            "top_module": "de1_soc_trecap_top",
            "platform": "de1soc",
            "board": "de1soc",
            "quartus_project": "platform/de1soc/quartus/trecap_de1soc",
        },
        "ADC profile build selection",
    )
    input_cfg = profile.get("input", {})
    require_equal(
        input_cfg,
        {
            "kind": "adc_live",
            "source_mode": "adc_live",
            "adc": EXPECTED_PROFILE_ADC,
        },
        "profile ADC input contract",
    )
    require_equal(
        profile.get("contract_refs"),
        {
            "core_config": "spec/generated/core_config.json",
            "csr_map": "spec/generated/csr_map.json",
            "packet_layouts": "spec/generated/packet_layouts.json",
        },
        "ADC profile generated-contract references",
    )
    require_equal(
        profile.get("transport"),
        {
            "hps_ddr_enable": True,
            "hps_udp_enable": True,
            "command_server_enable": True,
            "ring_enable_policy": "after_config_and_rd_commit",
            "address_map": "platform/de1soc/address_map/hps_bridge_regions.json",
            "hps_runtime_config": "sw/hps/config/trecap_hps_config.json",
            "dashboard_config": "sw/pc_dashboard/configs/dashboard_direct_link.json",
        },
        "ADC profile transport selection",
    )


def validate_adc_wrapper(text: str) -> None:
    clean = strip_sv_comments(text)
    dense = compact(clean)
    require_token(clean, "module adc_wrapper", "ADC wrapper")
    for token in (
        "parameterintunsignedCLK_HZ=50_000_000,",
        "parameterintunsignedSAMPLE_RATE_HZ=100_000,",
        "parameterintunsignedSCLK_HALF_DIV=10,",
        "parameterintunsignedFRAME_BITS=12,",
        "parameterintunsignedCOMMAND_BITS=6,",
        "parameterintunsignedADC_BITS=12,",
        "parameterintunsignedDOUT_SYNC_STAGES=2,",
        "parameterintunsignedCONVST_PULSE_CYCLES=2,",
        "parameterintunsignedCONVERSION_WAIT_CYCLES=80,",
        "parameterintunsignedACQUISITION_GUARD_CYCLES=12,",
        "parameterlogic[COMMAND_BITS-1:0]DEFAULT_COMMAND=6'b100010",
        "ADC_IDLE,ADC_CONVST,ADC_CONVERT,ADC_SHIFT,ADC_ACQUIRE",
        "localparambitPROTOCOL_CONFIG_SUPPORTED=",
        "((DEFAULT_COMMAND&6'b100011)==6'b100010)&&",
        "(DOUT_SYNC_STAGES>=2)&&",
        "(SCLK_HALF_DIV>=(DOUT_SYNC_STAGES+1))&&",
        "localparamintunsignedREENTRY_RECOVERY_CYCLES=CONVST_PULSE_CYCLES+CONVERSION_WAIT_CYCLES+SCLK_HALF_DIV;",
        "case(requested_command&6'b100011)",
        "6'b100010:requested_command_supported=1'b1;",
        "default:requested_command_supported=1'b0;",
        "case(state_q)ADC_IDLE,ADC_CONVST,ADC_CONVERT,ADC_SHIFT,ADC_ACQUIRE:state_q_legal=1'b1;default:state_q_legal=1'b0;endcase",
        "assignrequest_attempt=enable_i&&PROTOCOL_CONFIG_SUPPORTED&&",
        "assignrequest_now=request_attempt&&reentry_recovery_ready_q;",
        "assignbusy_o=PROTOCOL_CONFIG_SUPPORTED&&enable_i&&(!reentry_recovery_ready_q||(state_q!=ADC_IDLE));",
        "adc_dout_sync_q<={adc_dout_sync_q[DOUT_SYNC_SAFE-2:0],ADC_DOUT};",
        "if(!rst_n)beginreentry_recovery_cnt_q<='0;reentry_recovery_ready_q<=1'b0;endelseif(!PROTOCOL_CONFIG_SUPPORTED||!enable_i||!state_q_legal)beginreentry_recovery_cnt_q<='0;reentry_recovery_ready_q<=1'b0;",
        "if(reentry_recovery_cnt_q==REENTRY_RECOVERY_LAST)beginreentry_recovery_ready_q<=1'b1;end",
        "reentry_recovery_cnt_q<=reentry_recovery_cnt_q+{{(REENTRY_RECOVERY_CNT_W-1){1'b0}},1'b1};",
        "if(request_attempt&&(!reentry_recovery_ready_q||(state_q!=ADC_IDLE)))beginrequest_overrun_sticky_o<=1'b1;end",
        "if(request_attempt&&!requested_command_supported)beginprotocol_error_sticky_o<=1'b1;end",
        "rx_shift_q<={rx_shift_q[FRAME_BITS-2:0],adc_dout_sync_q[DOUT_SYNC_SAFE-1]};",
        "if(!requested_command_supported)beginprotocol_error_sticky_o<=1'b1;end",
        "ADC_DIN<=requested_command[COMMAND_BITS-1];",
        "ADC_DIN<=tx_command_q[COMMAND_BITS-1];",
        "tx_command_q<={tx_command_q[COMMAND_BITS-2:0],1'b0};",
        "ADC_DIN<=tx_command_q[COMMAND_BITS-2];",
        "result_eligible_q<=configured_valid_q&&(configured_command_q==requested_command);",
        "configured_command_q<=transaction_command_q;",
        "configured_valid_q<=1'b1;",
        "if(result_eligible_q)begin",
        "sample_valid_o<=1'b1;",
        "sample_count_o<=sat_inc64(sample_count_o);",
        "if(!PROTOCOL_CONFIG_SUPPORTED)begin",
        "if(enable_i)beginprotocol_error_sticky_o<=1'b1;end",
        "ADC_CS_N<=1'b0;",
        "ADC_DIN<=1'b0;",
        "ADC_SCLK<=1'b0;",
        "if(DOUT_SYNC_STAGES<2)",
        "if(SCLK_HALF_DIV<(DOUT_SYNC_STAGES+1))",
        "if((DEFAULT_COMMAND&6'b100011)!=6'b100010)",
        "if(TRANSACTION_CYCLES_U64>=SAMPLE_INTERVAL_MIN_CYCLES_U64)",
    ):
        require_token(dense, token, "ADC wrapper protocol/CDC/fail-closed contract")

    for attribute in (
        'async_reg = "true"',
        'preserve = "true"',
        'SYNCHRONIZER_IDENTIFICATION FORCED',
    ):
        require_token(clean, attribute, "ADC_DOUT synchronizer attributes")

    forbid_regex(
        dense,
        r"assignrequested_command_supported=",
        "two-state runtime command comparator that can admit X/Z controls",
    )

    forbid_regex(
        dense,
        r"rx_shift_q<=[^;]*(?<![A-Za-z0-9_])ADC_DOUT(?![A-Za-z0-9_])",
        "direct raw ADC_DOUT payload capture",
    )
    forbid_regex(clean, r"@\s*\([^)]*\bADC_SCLK\b", "ADC_SCLK used as RTL event clock")
    forbid_regex(clean, r"\.\s*(?:clk|clock)\s*\(\s*ADC_SCLK\s*\)", "ADC_SCLK clock port")
    forbid_regex(clean, r"\btrecap_async_fifo\b", "artificial ADC async FIFO")

    for timing_token in (
        "CONVST_HIGH_TIME_SCALED>=",
        "CONVST_HIGH_TIME_SCALED<=",
        "CONVERSION_TO_FIRST_SCLK_TIME_SCALED>=",
        "ACQUISITION_FROM_SEVENTH_RISE_TIME_SCALED>=",
        "TRANSACTION_CYCLES_U64<SAMPLE_INTERVAL_MIN_CYCLES_U64",
    ):
        require_token(dense, timing_token, "ADC wrapper wide timing guard")


def validate_board_top(text: str) -> None:
    dense = compact(strip_sv_comments(text))
    for token in (
        "parameterintunsignedADC_BITS=12,",
        "parameterintunsignedADC_SAMPLE_RATE_HZ=100_000,",
        "parameterintunsignedADC_SCLK_HALF_DIV=10,",
        "parameterintunsignedADC_CONVST_PULSE_CYCLES=2,",
        "parameterintunsignedADC_CONVERSION_WAIT_CYCLES=80,",
        "parameterintunsignedADC_ACQUISITION_GUARD_CYCLES=12,",
        "{1'b1,channel[0],channel[2],channel[1],1'b1,1'b0}",
        "assignadc_source_enable=(active_source_mode==TSRC_ADC_LIVE);",
        "assignadc_epoch_ready=adc_source_enable&&adc_source_enable_d_q;",
        "assignadc_continuous_enable=adc_epoch_ready&&!sw_sync[7];",
        "assignadc_manual_request=adc_epoch_ready&&sw_sync[7]&&key_press_pulse[2];",
        "assignadc_command=ltc2308_single_ended_command(adc_channel_active_q);",
        "if(adc_source_enable&&!adc_source_enable_d_q)beginadc_channel_active_q<=sw_sync[6:4];end",
        "assigntelemetry_sample_rate_hz=adc_source_enable?ADC_SAMPLE_RATE_HZ_U32:SAMPLE_RATE_HZ_U32;",
        ".SAMPLE_RATE_HZ(ADC_SAMPLE_RATE_HZ)",
        ".SCLK_HALF_DIV(ADC_SCLK_HALF_DIV)",
        ".FRAME_BITS(12)",
        ".COMMAND_BITS(6)",
        ".ADC_BITS(ADC_BITS)",
        ".DEFAULT_COMMAND(ADC_DEFAULT_COMMAND)",
        ")u_adc_wrapper(",
        ".enable_i(adc_source_enable)",
        ".command_i(adc_command)",
        ".command_valid_i(1'b1)",
        ".ADC_CS_N(ADC_CS_N)",
        ".ADC_DIN(ADC_DIN)",
        ".ADC_DOUT(ADC_DOUT)",
        ".ADC_SCLK(ADC_SCLK)",
        ".adc_zero_code_valid_i(1'b0)",
        ".adc_zero_code_i('0)",
        ".adc_dc_block_enable_i(1'b0)",
        ".sample_rate_hz_i(telemetry_sample_rate_hz)",
        "if((ADC_SAMPLE_RATE_HZ!=100_000)||(ADC_SCLK_HALF_DIV!=10))",
    ):
        require_token(dense, token, "physical-top ADC integration")
    require_equal(dense.count(")u_adc_wrapper("), 1, "physical-top ADC wrapper count")
    require_equal(dense.count("adc_channel_active_q<="), 2, "ADC epoch channel updates")
    forbid_regex(
        dense,
        r"assignADC_(?:CS_N|DIN|SCLK)=(?:1'b[01]|'0|'1);",
        "constant ADC physical output tie-off",
    )


def validate_adapter(text: str) -> None:
    dense = compact(strip_sv_comments(text))
    for token in (
        "moduletrecap_adc_adapter",
        "assigncapture_input=enable_i&&ADC_CONFIG_OK&&adc_sample_valid_i&&can_capture_input;",
        "assigndrop_input=adc_sample_valid_i&&(!enable_i||!ADC_CONFIG_OK||!can_capture_input);",
        "result[ADC_BITS-1]=1'b1;",
        "centered_raw=unsigned_adc_to_wide(adc_sample_raw_i)-zero_wide;",
        "scaled_value=trecap_rnd_shr(centered_value,shift_abs);",
        "dropped_sample_count_q<=inc_drop_count(dropped_sample_count_q);",
        "if(&value)begininc_drop_count=value;endelsebegininc_drop_count=value+{{(DROP_COUNT_SAFE_W-1){1'b0}},1'b1};end",
        "overflow_sticky_o<=1'b1;",
    ):
        require_token(dense, token, "ADC source adapter")


def validate_source_core(text: str) -> None:
    dense = compact(strip_sv_comments(text))
    for token in (
        ")u_adc_adapter(",
        ".enable_i(enable_i&&mode_is_adc_w&&!transition_guard_w)",
        ".adc_sample_valid_i(adc_sample_valid_i&&mode_is_adc_w&&!transition_guard_w)",
        ".adc_sample_raw_i(adc_sample_raw_i)",
        ".adc_sample_count_i(adc_sample_count_i)",
        ".zero_code_valid_i(adc_zero_code_valid_i)",
        ".zero_code_i(adc_zero_code_i)",
        ".dc_block_enable_i(adc_dc_block_enable_i)",
        ")u_source_mux(",
        ".adc_sample_i(adc_sample_w)",
        ".adc_sample_valid_i(adc_sample_valid_w)",
        ".adc_sample_ready_o(adc_sample_ready_w)",
    ):
        require_token(dense, token, "ADC adapter/source-mux binding")
    require_equal(dense.count(")u_adc_adapter("), 1, "ADC adapter instance count")
    require_equal(dense.count(")u_source_mux("), 1, "source mux instance count")


def validate_mux(text: str) -> None:
    dense = compact(strip_sv_comments(text))
    for token in (
        "TSRC_ADC_LIVE:begin",
        "selected_sample=normalized_sample(adc_sample_i,adc_sample_valid_i);",
        "adc_sample_ready_o=sample_ready_i;",
    ):
        require_token(dense, token, "ADC source-mux selection")


def validate_pins(text: str) -> None:
    clean = strip_tcl_comments(text)
    expected = {
        "ADC_CS_N": "PIN_AJ4",
        "ADC_DIN": "PIN_AK4",
        "ADC_DOUT": "PIN_AK3",
        "ADC_SCLK": "PIN_AK2",
    }
    for port, pin in expected.items():
        require(
            re.search(rf"^\s*trecap_pin\s+{re.escape(pin)}\s+{re.escape(port)}\s*$", clean, re.MULTILINE)
            is not None,
            f"pin assignment for {port} is missing or wrong",
        )
        require_equal(len(re.findall(rf"\b{re.escape(port)}\b", clean)), 1, f"{port} pin count")
    forbid_regex(clean, r"\btrecap_pullup\s+(?:ADC_CS_N|ADC_DIN|ADC_DOUT|ADC_SCLK)\b", "ADC weak pull-up")


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


def validate_filelists(full_text: str, quartus_text: str) -> None:
    for text, quartus, context in (
        (full_text, False, "full RTL filelist"),
        (quartus_text, True, "Quartus RTL include"),
    ):
        entries = active_filelist_entries(text, quartus)
        require_equal(entries.count(ADC_REL.as_posix()), 1, f"{context} ADC wrapper count")
        require_equal(entries.count(ADAPTER_REL.as_posix()), 1, f"{context} ADC adapter count")
        require_equal(entries.count(MUX_REL.as_posix()), 1, f"{context} source mux count")
        require_equal(entries.count(BOARD_TOP_REL.as_posix()), 1, f"{context} board-top count")
        require(entries.index(ADC_REL.as_posix()) < entries.index(BOARD_TOP_REL.as_posix()), f"{context}: ADC wrapper must precede board top")


def validate_clock_constraints(text: str) -> None:
    clean = strip_tcl_comments(text)
    forbid_regex(clean, r"\bcreate_(?:generated_)?clock\b[^\n]*\bADC_SCLK\b", "invented ADC internal/generated clock")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repo_root_from_script())
    parser.add_argument("--force-fallback-schema", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="suppress PASS output")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    try:
        contract = load_json(root / CONTRACT_REL)
        schema = load_json(root / SCHEMA_REL)
        profile = load_json(root / PROFILE_REL)
        require(isinstance(contract, dict), "ADC contract root must be an object")
        require(isinstance(profile, dict), "ADC profile root must be an object")
        schema_engine = validate_contract_schema(contract, schema, args.force_fallback_schema)
        validate_contract(contract)
        validate_profile(profile)
        validate_adc_wrapper(read_text(root / ADC_REL))
        validate_board_top(read_text(root / BOARD_TOP_REL))
        validate_adapter(read_text(root / ADAPTER_REL))
        validate_source_core(read_text(root / SOURCE_CORE_REL))
        validate_mux(read_text(root / MUX_REL))
        validate_pins(read_text(root / PINS_REL))
        validate_filelists(
            read_text(root / FULL_FILELIST_REL), read_text(root / QUARTUS_FILELIST_REL)
        )
        validate_clock_constraints(read_text(root / CLOCKS_REL))
    except (CheckFailure, OSError, ValueError, TypeError) as exc:
        print(f"check_de1soc_adc_path: FAIL: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            "check_de1soc_adc_path: PASS "
            f"schema={schema_engine} rate=100000Sps sclk=2500000Hz channels=8 "
            "scope=source_contract_only"
        )
        print(
            "check_de1soc_adc_path: no native RTL simulation, Quartus/TimeQuest, post-fit I/O "
            "measurement, analog characterization, live ADC, or hardware evidence was produced"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
