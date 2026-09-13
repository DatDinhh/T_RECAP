#!/usr/bin/env python3
"""Check the Step-7 DE1-SoC source-to-core integration source contract.

This is a dependency-free source/structure gate. It is not an RTL compiler,
simulation, synthesis, timing, live-source, or hardware-signoff result.
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
except ImportError:  # The checked-in gate has a dependency-free fallback.
    jsonschema = None  # type: ignore[assignment]


CONTRACT_REL = Path("config/boards/de1soc_source_core_integration.json")
SCHEMA_REL = Path("spec/schemas/source_core_integration.schema.json")
DOC_REL = Path("docs/architecture/source_core_integration.md")
INTEGRATION_REL = Path("rtl/top/trecap_source_core_integration.sv")
BOARD_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
FULL_TOP_REL = Path("rtl/top/trecap_de1soc_full_top.sv")
FILELIST_GENERATOR_REL = Path("scripts/gen_filelists.py")
FULL_FILELIST_REL = Path("filelists/rtl_de1soc_full.f")
QUARTUS_FILELIST_REL = Path("filelists/quartus_de1soc.qsf.inc")

EXPECTED_TOP_LEVEL = {
    "schema": "trecap_phase2_de1soc_source_core_integration_v1",
    "file_class": "[1] hand-written Step-7 integration contract",
    "project": "T_RECAP_Phase2",
    "board": "de1soc",
    "contract_stage": "step7_source_to_core_integration_source_implemented",
    "status": (
        "source_implemented_pending_rtl_compile_functional_verification_"
        "quartus_and_hardware_evidence"
    ),
}

EXPECTED_IMPLEMENTATION_STATE = {
    "integration_rtl_implemented": True,
    "all_four_normalized_sources_present": True,
    "board_audio_and_adc_wrappers_source_connected": True,
    "synthetic_board_taps_removed": True,
    "real_core_taps_connected_to_transport": True,
    "rtl_compile": False,
    "functional_verification": False,
    "quartus_compile": False,
    "live_audio_hardware_ready": False,
    "live_adc_hardware_ready": False,
    "hardware_signoff": False,
}

EXPECTED_OWNERSHIP = {
    "integration_rtl": INTEGRATION_REL.as_posix(),
    "board_top_rtl": BOARD_REL.as_posix(),
    "logical_transport_top_rtl": FULL_TOP_REL.as_posix(),
    "core_rtl": "rtl/core/trecap_core_top.sv",
    "source_mux_rtl": "rtl/sources/trecap_source_mux.sv",
    "bram_source_rtl": "rtl/sources/trecap_bram_replay_source.sv",
    "diagnostic_source_rtl": "rtl/sources/trecap_diagnostic_source.sv",
    "audio_adapter_rtl": "rtl/sources/trecap_audio_adapter.sv",
    "adc_adapter_rtl": "rtl/sources/trecap_adc_adapter.sv",
    "audio_board_wrapper_rtl": "rtl/platform/de1soc/audio_codec_wrapper.sv",
    "adc_board_wrapper_rtl": "rtl/platform/de1soc/adc_wrapper.sv",
}

EXPECTED_CLOCK_RESET = {
    "clock": "clk_fabric",
    "reset": "rst_n_platform",
    "single_clock_source_core_transport_domain": True,
    "platform_reset_already_synchronized": True,
    "logical_top_second_reset_synchronizer_enabled": False,
    "logical_top_parameter_binding": "SYNC_TOP_RESET_DEASSERTION=0",
}

EXPECTED_EVIDENCE = {
    "source_checker": "scripts/check_source_core_integration.py",
    "human_document": DOC_REL.as_posix(),
    "schema_file": SCHEMA_REL.as_posix(),
    "default_checker_scope": "source_only",
    "source_check_is_rtl_compile": False,
    "source_check_is_functional_verification": False,
    "source_check_is_quartus_compile": False,
    "source_check_is_live_source_hardware_evidence": False,
    "source_check_is_hardware_signoff": False,
}

EXPECTED_INSTANCES = {
    "u_bram_replay_source": "trecap_bram_replay_source",
    "u_audio_adapter": "trecap_audio_adapter",
    "u_adc_adapter": "trecap_adc_adapter",
    "u_diagnostic_source": "trecap_diagnostic_source",
    "u_source_mux": "trecap_source_mux",
    "u_core": "trecap_core_top",
}


class CheckFailure(RuntimeError):
    """Raised when the checked-in Step-7 source contract is inconsistent."""


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


def require_token(text: str, token: str, context: str) -> None:
    if token not in text:
        raise CheckFailure(f"{context}: required source token is missing: {token}")


def forbid_token(text: str, token: str, context: str) -> None:
    if token in text:
        raise CheckFailure(f"{context}: forbidden source token is present: {token}")


def require_exact_count(text: str, token: str, count: int, context: str) -> None:
    actual = text.count(token)
    if actual != count:
        raise CheckFailure(
            f"{context}: token {token!r} occurs {actual} times; expected {count}"
        )


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CheckFailure(f"{context} differs from the frozen Step-7 value")


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
        if minimum is not None and len(value) < int(minimum):
            raise CheckFailure(f"{location}: list has fewer than {minimum} items")
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


def validate_contract_schema(contract: Any, schema: Any) -> str:
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        raise CheckFailure("contract and schema roots must both be JSON objects")
    if jsonschema is not None:
        try:
            jsonschema.Draft202012Validator(schema).validate(contract)
        except Exception as exc:  # jsonschema exposes several validation exception types.
            raise CheckFailure(f"contract does not validate against schema: {exc}") from exc
        return "jsonschema"
    validate_schema_fallback(contract, schema, schema)
    return "dependency_free_fallback"


def validate_contract_values(contract: dict[str, Any]) -> None:
    for name, expected in EXPECTED_TOP_LEVEL.items():
        require_equal(contract.get(name), expected, f"contract.{name}")
    require_equal(
        contract.get("implementation_state"),
        EXPECTED_IMPLEMENTATION_STATE,
        "contract.implementation_state",
    )
    require_equal(contract.get("source_ownership"), EXPECTED_OWNERSHIP, "contract.source_ownership")
    require_equal(
        contract.get("clock_reset_contract"),
        EXPECTED_CLOCK_RESET,
        "contract.clock_reset_contract",
    )
    require_equal(contract.get("evidence_policy"), EXPECTED_EVIDENCE, "contract.evidence_policy")

    inventory = contract.get("source_inventory")
    if not isinstance(inventory, dict) or set(inventory) != {
        "bram_replay",
        "adc_live",
        "audio_wrapper",
        "diagnostic",
    }:
        raise CheckFailure("contract.source_inventory must describe exactly four source modes")

    stream = contract.get("stream_contract")
    if not isinstance(stream, dict):
        raise CheckFailure("contract.stream_contract must be an object")
    for false_key in (
        "telemetry_ready_path_to_core_permitted",
        "transport_ready_path_to_core_permitted",
    ):
        require_equal(stream.get(false_key), False, f"contract.stream_contract.{false_key}")

    source_switch = contract.get("source_switch_contract")
    if not isinstance(source_switch, dict):
        raise CheckFailure("contract.source_switch_contract must be an object")
    require_equal(
        source_switch.get("idempotent_commit_causes_discontinuity"),
        False,
        "contract.source_switch_contract.idempotent_commit_causes_discontinuity",
    )

    core_config = contract.get("core_config_contract")
    if not isinstance(core_config, dict):
        raise CheckFailure("contract.core_config_contract must be an object")
    require_equal(
        core_config.get("late_tap_frame_valid_is_commit_boundary"),
        False,
        "contract.core_config_contract.late_tap_frame_valid_is_commit_boundary",
    )

    fault = contract.get("fault_projection_contract")
    if not isinstance(fault, dict):
        raise CheckFailure("contract.fault_projection_contract must be an object")
    require_equal(
        fault.get("sticky_level_directly_drives_set_interface"),
        False,
        "contract.fault_projection_contract.sticky_level_directly_drives_set_interface",
    )


def validate_source_files(root: Path, contract: dict[str, Any]) -> None:
    required_paths = {
        CONTRACT_REL,
        SCHEMA_REL,
        DOC_REL,
        INTEGRATION_REL,
        BOARD_REL,
        FULL_TOP_REL,
        FILELIST_GENERATOR_REL,
        FULL_FILELIST_REL,
        QUARTUS_FILELIST_REL,
    }
    ownership = contract["source_ownership"]
    required_paths.update(Path(value) for value in ownership.values())
    missing = sorted(path.as_posix() for path in required_paths if not (root / path).is_file())
    if missing:
        raise CheckFailure(f"required Step-7 source files are missing: {missing}")

    checker_mode = (root / EXPECTED_EVIDENCE["source_checker"]).stat().st_mode
    if not checker_mode & stat.S_IXUSR:
        raise CheckFailure("scripts/check_source_core_integration.py must be executable")


def validate_integration_rtl(text: str) -> None:
    clean = strip_sv_comments(text)
    compact = compact_sv(text)
    context = INTEGRATION_REL.as_posix()

    require_token(compact, "moduletrecap_source_core_integration", context)
    require_token(compact, "endmodule:trecap_source_core_integration", context)

    for instance_name, module_name in EXPECTED_INSTANCES.items():
        require_exact_count(compact, f"{instance_name}(", 1, context)
        require_token(compact, module_name, context)

    for token in (
        ".bram_sample_i(bram_sample_w)",
        ".adc_sample_i(adc_sample_w)",
        ".audio_sample_i(audio_sample_w)",
        ".diagnostic_sample_i(diagnostic_sample_w)",
        ".sample_o(mux_sample_w)",
        ".sample_i(core_sample_w)",
        ".sample_ready_o(core_sample_ready_w)",
        ".source_mode_commit_i(source_mode_apply_pulse_i)",
        ".safe_to_switch_i(1'b1)",
        ".clear_i(1'b0)",
        ".source_discontinuity_i(source_discontinuity_pulse_o)",
        ".finite_stream_i(mode_is_bram_w)",
        ".tail_tick_valid_i(tail_tick_valid_w)",
        ".tail_tick_sample_idx_i(mux_sample_w.sample_idx)",
        ".thr2_i(thr2_i)",
        ".clear_metrics_i(core_clear_metrics_w)",
        ".tap_sample_o(tap_sample_o)",
        ".tap_frame_o(tap_frame_o)",
        ".tap_bin_valid_o(tap_bin_valid_o)",
    ):
        require_token(compact, token, context)

    for token in (
        "assignselected_source_pace_w=(mode_is_bram_w||mode_is_diagnostic_w)?source_tick_i:1'b1;",
        "assignselected_bram_tail_w=mode_is_bram_w&&mux_sample_valid_w&&(mux_sample_w.sample_idx>=REPLAY_TAU_LAST_U64);",
        "assigncore_sample_valid_w=!transition_guard_w&&selected_source_pace_w&&mux_sample_valid_w&&!selected_bram_tail_w;",
        "assigntail_tick_valid_w=!transition_guard_w&&selected_source_pace_w&&mux_sample_valid_w&&selected_bram_tail_w;",
        "assignmode_change_request_w=source_mode_apply_pulse_i&&(requested_source_mode_i!=active_source_mode_o);",
        "assignsource_discontinuity_pulse_o=mode_change_request_w||replay_start_accept_w||(datapath_epoch_clear_level_w&&!datapath_epoch_clear_prior_q);",
        "assignreplay_tail_drain_phase_o=selected_bram_tail_w;",
        "assignsource_safe_boundary_o=rst_n&&!clear_i&&!transition_guard_w&&!source_switch_pending_o&&(!mux_sample_valid_w||source_handshake_w);",
        "assigncore_clear_metrics_w=(metrics_clear_pending_q||clear_metrics_pulse_i)&&core_config_safe_boundary_o&&!replay_path_inflight_q&&!replay_active_o;",
        "!core_busy_o&&!y_valid_o&&!replay_path_inflight_q",
        "replay_start_request_w&&replay_start_admit_i&&mode_is_bram_w",
        "(REPLAY_RESTART_ALLOWED&&replay_path_done_q)",
        "assignreplay_path_done_o=LOCAL_BUILD_CONTRACT_OK&&replay_path_done_q&&",
        "replay_metric_commit_count_q==REPLAY_OUTPUT_SAMPLES",
        "externally_mapped_fault_levels_w&~clear_sticky_flags_w1c_i;",
        "assignexternal_overflow_flags_set_o=externally_mapped_fault_levels_w&~prior_mapped_fault_levels_q;",
        "assignexternal_csr_reject_pulse_o=mux_switch_reject_w;",
    ):
        require_token(compact, token, context)

    for mask in (
        "TCSR_OVERFLOW_FLAGS_ARITHMETIC_OVERFLOW_MASK",
        "TCSR_OVERFLOW_FLAGS_OLA_OVERFLOW_MASK",
        "TCSR_OVERFLOW_FLAGS_RING_OVERFLOW_MASK",
        "TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_MASK",
    ):
        require_token(compact, mask, context)

    for forbidden in (
        "trecap_telemetry_top",
        "trecap_hps_bridge_top",
        "trecap_ddr_ring_writer",
        "platform_designer_wrapper",
        "tap_sample_ready",
        "tap_frame_ready",
        "tap_bin_ready",
    ):
        forbid_token(clean, forbidden, context)
    forbid_token(
        compact,
        "source_discontinuity_pulse_o=mode_change_request_w||mux_discontinuity_w",
        context,
    )


def validate_board_rtl(text: str) -> None:
    compact = compact_sv(text)
    context = BOARD_REL.as_posix()

    for token in (
        "trecap_source_core_integration#(",
        ")u_source_core_integration(",
        ".clk(clk_fabric)",
        ".rst_n(rst_n_platform)",
        ".thr2_i(ctrl.thr2_active)",
        ".requested_source_mode_i(ctrl.source_mode)",
        ".source_mode_apply_pulse_i(source_mode_apply_pulse)",
        ".clear_metrics_pulse_i(clear_metrics_pulse)",
        ".clear_sticky_flags_w1c_i(clear_sticky_flags_w1c)",
        ".source_tick_i(sample_tick)",
        ".replay_start_i(replay_owner_start)",
        ".replay_start_admit_i(replay_start_admit)",
        "assignreplay_epoch_clear=key_press_pulse[3]||csr_replay_rearm;",
        "assigncsr_replay_forward=!replay_epoch_clear&&(replay_request_origin_q==REPLAY_ORIGIN_NONE)&&(csr_replay_queued_q||csr_replay_start);",
        "assignkey_replay_forward=!replay_epoch_clear&&(replay_request_origin_q==REPLAY_ORIGIN_NONE)&&!csr_replay_forward&&key_press_pulse[1];",
        "assignreplay_owner_start=csr_replay_forward||key_replay_forward;",
        "assignreplay_request_busy=(replay_request_origin_q!=REPLAY_ORIGIN_NONE)||csr_replay_queued_q||csr_replay_start||key_press_pulse[1];",
        "assigncsr_replay_feedback_enable=(replay_request_origin_q==REPLAY_ORIGIN_CSR)||((replay_request_origin_q==REPLAY_ORIGIN_NONE)&&csr_replay_forward);",
        "assigncsr_replay_accept_feedback=!replay_epoch_clear&&replay_start_accept&&csr_replay_feedback_enable;",
        "assigncsr_replay_reject_feedback=(!replay_epoch_clear&&replay_start_reject&&csr_replay_feedback_enable)||csr_replay_abort_reject_q;",
        "assigncsr_command_reject_event=source_core_csr_reject_pulse||csr_replay_reject_feedback;",
        "if(replay_epoch_clear)begin",
        "csr_replay_abort_reject_q<=(replay_request_origin_q==REPLAY_ORIGIN_CSR)||csr_replay_queued_q||csr_replay_start;",
        "assignreplay_error=replay_completion_error_sticky||replay_e2e_error_sticky;",
        "assignreplay_rearm_required=replay_error;",
        "assignreplay_start_admit=replay_e2e_transport_ready&&transport_epoch_idle&&transport_epoch_idle_stable&&!replay_e2e_busy&&!replay_rearm_required;",
        ".y_ready_i(1'b1)",
        ".tap_sample_o(tap_sample)",
        ".tap_frame_o(tap_frame)",
        ".core_config_safe_boundary_o(core_config_safe_boundary)",
        ".source_safe_boundary_o(source_core_safe_boundary)",
        ".external_overflow_flags_set_o(source_core_overflow_flags_set)",
        ".external_csr_reject_pulse_o(source_core_csr_reject_pulse)",
        "audio_codec_wrapper#(",
        ")u_audio_codec_wrapper(",
        "adc_wrapper#(",
        ")u_adc_wrapper(",
        ".SYNC_TOP_RESET_DEASSERTION(1'b0)",
        ".frame_boundary_i(core_config_safe_boundary)",
        ".source_safe_boundary_i(source_core_safe_boundary)",
        ".core_alive_i(core_alive)",
        ".core_frame_count_i(core_frame_count)",
        ".core_sample_count_i(core_sample_count)",
        ".external_overflow_flags_set_i(source_core_overflow_flags_set)",
        ".external_csr_reject_pulse_i(csr_command_reject_event)",
        ".external_telemetry_flush_i(replay_start_accept)",
        ".replay_rearm_required_i(replay_rearm_required)",
        ".replay_request_busy_i(replay_request_busy)",
        ".counter_clear_pulse_o(csr_counter_clear)",
        ".replay_start_pulse_o(csr_replay_start)",
        ".replay_rearm_pulse_o(csr_replay_rearm)",
    ):
        require_token(compact, token, context)

    require_exact_count(compact, ")u_source_core_integration(", 1, context)
    require_exact_count(compact, ")u_audio_codec_wrapper(", 1, context)
    require_exact_count(compact, ")u_adc_wrapper(", 1, context)
    require_exact_count(
        compact,
        ".clear_i(key_press_pulse[3]||csr_replay_rearm)",
        2,
        context,
    )

    for forbidden in (
        "diag_sample_q",
        "diag_frame_stats",
        "diag_mag2_for_bin",
        "bin_active_q",
        "bin_frame_idx_q",
        ".source_safe_boundary_i(source_safe_boundary)",
        "assignAUD_XCK=1'b0",
        "assignADC_CS_N=1'b1",
    ):
        forbid_token(compact, forbidden, context)


def validate_logical_top(text: str) -> None:
    compact = compact_sv(text)
    context = FULL_TOP_REL.as_posix()
    require_token(compact, "assignframe_boundary_w=frame_boundary_i;", context)
    forbid_token(compact, "frame_boundary_i|tap_frame_i.valid", context)
    forbid_token(compact, "tap_frame_i.valid|frame_boundary_i", context)


def validate_filelists(root: Path) -> None:
    integration_path = INTEGRATION_REL.as_posix()
    generator = read_text(root / FILELIST_GENERATOR_REL)
    require_exact_count(generator, f'"{integration_path}"', 1, FILELIST_GENERATOR_REL.as_posix())

    full = read_text(root / FULL_FILELIST_REL)
    require_exact_count(full, integration_path, 1, FULL_FILELIST_REL.as_posix())
    board_path = BOARD_REL.as_posix()
    if full.index(integration_path) > full.index(board_path):
        raise CheckFailure(
            f"{FULL_FILELIST_REL}: integration RTL must be listed before the board top"
        )

    quartus = read_text(root / QUARTUS_FILELIST_REL)
    require_exact_count(quartus, integration_path, 1, QUARTUS_FILELIST_REL.as_posix())
    if quartus.index(integration_path) > quartus.index(board_path):
        raise CheckFailure(
            f"{QUARTUS_FILELIST_REL}: integration RTL must be listed before the board top"
        )


def validate_document(text: str) -> None:
    context = DOC_REL.as_posix()
    for token in (
        "Step 7",
        "source_implemented_pending_rtl_compile_functional_verification_quartus_and_hardware_evidence",
        CONTRACT_REL.as_posix(),
        INTEGRATION_REL.as_posix(),
        "tau_last",
        "source_safe_boundary",
        "core_config_safe_boundary",
        "new-fault",
        "valid-only",
        "functional verification",
        "hardware signoff",
    ):
        require_token(text, token, context)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        "--repo-root",
        dest="repo_root",
        type=Path,
        default=repo_root_from_script(),
        help="Repository root. Default: parent of this script directory.",
    )
    parser.add_argument("--quiet", action="store_true", help="Print only errors.")
    args = parser.parse_args(argv)

    root = args.repo_root.resolve()
    if not (root / "Makefile").is_file():
        print(f"ERROR: not a T-RECAP repository root: {root}", file=sys.stderr)
        return 2

    try:
        contract = load_json(root / CONTRACT_REL)
        schema = load_json(root / SCHEMA_REL)
        schema_mode = validate_contract_schema(contract, schema)
        validate_contract_values(contract)
        validate_source_files(root, contract)
        validate_integration_rtl(read_text(root / INTEGRATION_REL))
        validate_board_rtl(read_text(root / BOARD_REL))
        validate_logical_top(read_text(root / FULL_TOP_REL))
        validate_filelists(root)
        validate_document(read_text(root / DOC_REL))
    except (CheckFailure, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: source-to-core integration check failed: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            "check_source_core_integration: OK "
            f"scope=source_only schema_validator={schema_mode} "
            "rtl_compile=false functional_verification=false quartus_compile=false "
            "hardware_signoff=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
