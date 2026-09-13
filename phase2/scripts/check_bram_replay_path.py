#!/usr/bin/env python3
"""Check the source-only Step-11 DE1-SoC BRAM replay path contract.

The gate is dependency-free when ``jsonschema`` is unavailable.  It validates
committed contracts, artifacts, SystemVerilog hierarchy/bindings, the board
profile, and the declared RTL regression.  It does not compile or simulate RTL,
generate Platform Designer HDL, invoke Quartus/TimeQuest, or touch hardware.
"""

from __future__ import annotations

import argparse
import hashlib
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


CONTRACT_REL = Path("config/boards/de1soc_bram_replay_path.json")
SCHEMA_REL = Path("spec/schemas/de1soc_bram_replay_path.schema.json")
DOC_REL = Path("docs/architecture/de1soc_bram_replay_path.md")
SYSTEM_TOP_REL = Path("rtl/top/trecap_bram_replay_system_top.sv")
E2E_SUPERVISOR_REL = Path("rtl/top/trecap_bram_replay_e2e_supervisor.sv")
SOURCE_CORE_REL = Path("rtl/top/trecap_source_core_integration.sv")
REPLAY_SOURCE_REL = Path("rtl/sources/trecap_bram_replay_source.sv")
CORE_REL = Path("rtl/core/trecap_core_top.sv")
FULL_TOP_REL = Path("rtl/top/trecap_de1soc_full_top.sv")
TELEMETRY_REL = Path("rtl/telemetry/trecap_telemetry_top.sv")
PACKET_FIFO_REL = Path("rtl/telemetry/trecap_packet_fifo.sv")
HPS_BRIDGE_REL = Path("rtl/hps_bridge/trecap_hps_bridge_top.sv")
DDR_WRITER_REL = Path("rtl/hps_bridge/trecap_ddr_ring_writer.sv")
AVMM_MASTER_REL = Path("rtl/hps_bridge/trecap_avmm_write_master.sv")
PD_WRAPPER_REL = Path("rtl/platform/de1soc/platform_designer_wrapper.sv")
BOARD_TOP_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
PROFILE_REL = Path("config/profiles/de1soc_bram_replay.json")
TELEMETRY_PROFILE_REL = Path("config/profiles/telemetry_status_only.json")
TESTBENCH_REL = Path("sim/tb/tb_trecap_step11_bram_e2e.sv")
TEST_FILELIST_REL = Path("sim/filelists/step11_bram_e2e.f")
IMPORT_MANIFEST_REL = Path("artifacts/manifests/reference_import_manifest.json")
ZERO_CONFIG_REL = Path("artifacts/test_vectors/zero_Ns4096_thr0/config.json")
ZERO_INPUT_REL = Path("artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh")
IMPULSE_CONFIG_REL = Path("artifacts/test_vectors/impulse_Ns1024_thr0/config.json")
IMPULSE_INPUT_REL = Path("artifacts/test_vectors/impulse_Ns1024_thr0/x_in.memh")
IMPULSE_Y_REL = Path("artifacts/reference_outputs/impulse_Ns1024_thr0/y_out.memh")

UPLOADED_ARCHIVE_SHA256 = "caf0aa0997a9ad9e8b4382eb2a9a1245ee927b161ce030cd8c83fab6ac80363b"
ZERO_INPUT_SHA256 = "9024e2856ad4ac8e8f91940331cd492ee792e5d72a380e779b67562ab1227a26"
IMPULSE_INPUT_SHA256 = "ba664127051e78535aa77e70d3747e1cfdbb658e3479de6b23740bf09d65b0b1"
IMPULSE_Y_SHA256 = "607bbb9f04d53e20d121aa1b35e140c73ed9eb00260ed22cb38981c4c3eef5d3"

EXPECTED_TOP_LEVEL = {
    "schema": "trecap_phase2_de1soc_bram_replay_path_v1",
    "file_class": "[1] hand-written Step-11 BRAM replay path contract",
    "project": "T_RECAP_Phase2",
    "board": "de1soc",
    "contract_stage": "step11_bram_replay_path_source_implemented",
    "status": (
        "source_implemented_pending_rtl_compile_functional_verification_"
        "platform_designer_generation_quartus_timing_and_hardware_evidence"
    ),
}

EXPECTED_OWNERSHIP = {
    "pin_agnostic_system_top": SYSTEM_TOP_REL.as_posix(),
    "e2e_supervisor": E2E_SUPERVISOR_REL.as_posix(),
    "source_core_and_completion_monitor": SOURCE_CORE_REL.as_posix(),
    "bram_replay_source": REPLAY_SOURCE_REL.as_posix(),
    "mathematical_core": CORE_REL.as_posix(),
    "logical_telemetry_hps_top": FULL_TOP_REL.as_posix(),
    "telemetry_top": TELEMETRY_REL.as_posix(),
    "hps_bridge_top": HPS_BRIDGE_REL.as_posix(),
    "ddr_ring_writer": DDR_WRITER_REL.as_posix(),
    "platform_designer_wrapper": PD_WRAPPER_REL.as_posix(),
    "physical_board_top": BOARD_TOP_REL.as_posix(),
    "board_profile": PROFILE_REL.as_posix(),
    "rtl_testbench": TESTBENCH_REL.as_posix(),
    "rtl_test_filelist": TEST_FILELIST_REL.as_posix(),
    "reference_import_manifest": IMPORT_MANIFEST_REL.as_posix(),
    "human_document": DOC_REL.as_posix(),
    "schema_file": SCHEMA_REL.as_posix(),
    "source_checker": "scripts/check_bram_replay_path.py",
}

EXPECTED_EXACT_COUNTS = [
    "replay_core_output_accept_count==Ny",
    "replay_source_output_accept_count==Ny",
    "wola_output_count==Ny",
    "core_sample_count==tau_last",
    "core_frame_count==Nframes",
    "core_error_sample_count==Ny",
    "replay_epoch_metric_commit_count==Ny",
]

EXPECTED_EVIDENCE = {
    "source_checker": "scripts/check_bram_replay_path.py",
    "schema_file": SCHEMA_REL.as_posix(),
    "human_document": DOC_REL.as_posix(),
    "default_checker_scope": "source_only",
    "external_tool_execution_performed_by_checker": False,
    "source_check_is_rtl_compile": False,
    "source_check_is_functional_verification": False,
    "source_check_is_platform_designer_generation": False,
    "source_check_is_quartus_compile": False,
    "source_check_is_timing_closure": False,
    "source_check_is_hardware_evidence": False,
    "source_check_is_hardware_signoff": False,
}

FALSE_EVIDENCE_FIELDS = (
    "rtl_compile",
    "functional_verification",
    "platform_designer_generation",
    "quartus_compile",
    "timing_closure",
    "hardware_bram_replay",
    "hardware_ddr_hps_capture",
    "hardware_signoff",
)


class CheckFailure(RuntimeError):
    """Raised when checked-in Step-11 source violates the frozen contract."""


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CheckFailure(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CheckFailure(f"{context} differs from the frozen Step-11 value")


def require_token(text: str, token: str, context: str) -> None:
    if token not in text:
        raise CheckFailure(f"{context}: required token is missing: {token}")


def require_regex(text: str, pattern: str, context: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if match is None:
        raise CheckFailure(f"{context}: required source pattern is missing: {pattern}")
    return match


def forbid_regex(text: str, pattern: str, context: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL):
        raise CheckFailure(f"{context}: forbidden source pattern is present: {pattern}")


def strip_sv_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\r\n]*", "", text)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


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
    for key in FALSE_EVIDENCE_FIELDS:
        require_equal(implementation.get(key), False, f"contract.implementation_state.{key}")

    replay_path = contract.get("replay_path")
    if not isinstance(replay_path, dict):
        raise CheckFailure("contract.replay_path must be an object")
    for key, expected in {
        "profile_source_mode": "TSRC_BRAM_REPLAY",
        "reset_source_mode": "TSRC_BRAM_REPLAY",
        "runtime_source_mode_owner": "ctrl.source_mode_and_source_mode_apply_pulse",
        "pin_agnostic_source_mode_locked": False,
        "source_mode_commit_permitted_in_pin_agnostic_top": True,
        "replay_start_requires_active_bram_mode": True,
        "raw_replay_start_request_reaches_source_owner": True,
        "replay_start_admission_owner": "composition_status_only_transport_gate",
        "replay_start_admission_requires": [
            "status_only_transport_ready",
            "transport_epoch_idle",
            "no_e2e_epoch_inflight",
        ],
        "transport_epoch_idle_signal": "transport_epoch_idle_o",
        "transport_epoch_idle_semantic": "writer_idle_and_no_fifo_record_valid",
        "denied_explicit_start_emits_reject_evidence": True,
        "telemetry_or_ddr_ready_to_core_permitted": False,
    }.items():
        require_equal(replay_path.get(key), expected, f"contract.replay_path.{key}")

    completion = contract.get("exact_completion_contract")
    if not isinstance(completion, dict):
        raise CheckFailure("contract.exact_completion_contract must be an object")
    require_equal(
        completion.get("exact_count_requirements"),
        EXPECTED_EXACT_COUNTS,
        "contract.exact_completion_contract.exact_count_requirements",
    )
    require_equal(
        completion.get("source_done_is_exact_path_done"),
        False,
        "contract.exact_completion_contract.source_done_is_exact_path_done",
    )
    require_equal(
        completion.get("source_done_may_precede_path_done"),
        True,
        "contract.exact_completion_contract.source_done_may_precede_path_done",
    )

    e2e = contract.get("e2e_completion_contract")
    if not isinstance(e2e, dict):
        raise CheckFailure("contract.e2e_completion_contract must be an object")
    for key, expected in {
        "supervisor_owner": "trecap_bram_replay_e2e_supervisor",
        "supervisor_source": E2E_SUPERVISOR_REL.as_posix(),
        "supervisor_instance": "u_replay_e2e_supervisor",
        "supervisor_block_label": "p_replay_e2e_completion",
        "core_path_done_is_step11_e2e_done": False,
        "accepted_start_flushes_uncommitted_telemetry_state": True,
        "accepted_start_telemetry_flush_scope": "packetizer_and_packet_fifo_only",
        "accepted_start_telemetry_flush_requires_epoch_idle": True,
        "accepted_start_external_transport_clear_permitted": False,
        "accepted_start_preserves_committed_ring_state": True,
        "pin_agnostic_clear_or_disable_clears_transport_epoch": True,
        "hps_telemetry_soft_reset_scope": "transport_only_frozen_control_contract",
        "board_replay_rearm_binding": "key_press_pulse[3]",
        "board_replay_rearm_scope": "source_core_and_e2e_only_preserve_transport_state",
        "board_replay_rearm_telemetry_flush_permitted": False,
        "board_replay_rearm_preserves_transport_state": True,
        "drop_baseline_captured_after_accepted_start_telemetry_flush": True,
        "fault_capture_active_on_accepted_start_edge": True,
        "fault_capture_active_during_baseline_cycle": True,
        "baseline_capture_has_fault_blind_window": False,
        "periodic_status_suppressed_during_replay_epoch": True,
        "post_core_status_request_trigger": "replay_path_done_pulse",
        "transport_observation_must_follow_core_path_done": True,
        "required_transport_packet": "new_STATUS_record_for_completed_replay_epoch",
        "required_commit_kind": "normal_DDR_ring_commit",
        "normal_commit_requires_all_local_avmm_beat_responses_ok": True,
        "pin_agnostic_tb_avmm_response_model": "delayed_OKAY_and_SLVERR_injection",
        "physical_board_local_response_owner": "platform_designer_wrapper",
        "physical_board_okay_semantic": (
            "legal_F2SDRAM_request_accepted_across_waitrequest_boundary"
        ),
        "physical_board_range_reject_response": "SLVERR",
        "physical_board_e2e_proves_physical_dram_durability": False,
        "physical_board_e2e_proves_downstream_error_visibility": False,
        "post_core_transport_baseline_captured_on_path_done": True,
        "normal_commit_must_follow_core_path_done": True,
        "producer_pointer_must_advance_from_post_core_baseline": True,
        "dma_packet_count_must_advance_from_post_core_baseline": True,
        "writer_must_be_idle_at_done": True,
        "e2e_done_semantic": (
            "retained_historical_terminal_evidence_for_correlated_replay_status_epoch"
        ),
        "e2e_done_is_live_global_transport_health": False,
        "terminal_success_requires_no_correlated_avmm_response_outstanding": True,
        "later_unrelated_transport_fault_retroactively_invalidates_epoch": False,
        "later_unrelated_transport_fault_reporting": (
            "normal_transport_fault_and_status_channels"
        ),
        "retained_epoch_result_invalidated_on_new_epoch_or_defined_clear_rearm": True,
    }.items():
        require_equal(e2e.get(key), expected, f"contract.e2e_completion_contract.{key}")

    board_profile = contract.get("board_profile_contract")
    if not isinstance(board_profile, dict):
        raise CheckFailure("contract.board_profile_contract must be an object")
    require_equal(
        {
            key: board_profile.get(key)
            for key in ("vector_name", "Ns", "Ny", "Nframes", "THR2", "artifact_use")
        },
        {
            "vector_name": "zero_Ns4096_thr0",
            "Ns": 4096,
            "Ny": 4608,
            "Nframes": 33,
            "THR2": "0",
            "artifact_use": "development_board_smoke_only",
        },
        "contract.board_profile_contract zero-vector selection",
    )

    regression = contract.get("rtl_regression_contract")
    if not isinstance(regression, dict):
        raise CheckFailure("contract.rtl_regression_contract must be an object")
    require_equal(
        {
            key: regression.get(key)
            for key in (
                "vector_name",
                "Ns",
                "Ny",
                "Nframes",
                "THR2",
                "requires_path_done_auto_status_injection",
                "manual_status_tick_after_path_done_permitted",
                "requires_delayed_avmm_responses",
                "requires_negative_final_slverr_epoch",
                "requires_response_error_blocks_commit_and_e2e",
                "regression_result_recorded",
                "status",
                "artifact_use",
            )
        },
        {
            "vector_name": "impulse_Ns1024_thr0",
            "Ns": 1024,
            "Ny": 1536,
            "Nframes": 9,
            "THR2": "0",
            "requires_path_done_auto_status_injection": True,
            "manual_status_tick_after_path_done_permitted": False,
            "requires_delayed_avmm_responses": True,
            "requires_negative_final_slverr_epoch": True,
            "requires_response_error_blocks_commit_and_e2e": True,
            "regression_result_recorded": False,
            "status": "source_declared_not_run",
            "artifact_use": "development_rtl_smoke_only",
        },
        "contract.rtl_regression_contract impulse selection",
    )

    provenance = contract.get("reference_provenance")
    if not isinstance(provenance, dict):
        raise CheckFailure("contract.reference_provenance must be an object")
    require_equal(
        provenance,
        {
            "uploaded_archive_name": "trecap-golden-new(1).zip",
            "uploaded_archive_sha256": UPLOADED_ARCHIVE_SHA256,
            "uploaded_archive_sha256_observed": True,
            "original_source_provenance_verified": False,
            "checked_in_import_matches_uploaded_archive": False,
            "match_status": (
                "mismatch_between_uploaded_archive_and_checked_in_embedded_proxy_provenance"
            ),
            "checked_in_manifest": IMPORT_MANIFEST_REL.as_posix(),
            "checked_in_manifest_provenance_status": (
                "embedded_proxy_unverified_source_archive"
            ),
            "checked_in_manifest_source_kind": "embedded_proxy",
            "checked_in_manifest_source_verified": False,
            "artifact_trust_class": "development_smoke_only",
            "signoff_authority": False,
        },
        "contract.reference_provenance",
    )


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
    text: str, module_name: str, instance_name: str, context: str
) -> tuple[dict[str, str], dict[str, str]]:
    matches = [item for item in parse_instances(text, module_name) if item[0] == instance_name]
    if len(matches) != 1:
        raise CheckFailure(
            f"{context}: expected exactly one {module_name} {instance_name}, found {len(matches)}"
        )
    return matches[0][1], matches[0][2]


def require_bindings(
    actual: dict[str, str], expected: dict[str, str], context: str
) -> None:
    for name, expression in expected.items():
        if actual.get(name) != compact(expression):
            raise CheckFailure(
                f"{context}: .{name} must bind {compact(expression)}, got {actual.get(name)!r}"
            )


def assignment_expression(text: str, signal: str, context: str) -> str:
    clean = strip_sv_comments(text)
    matches = re.findall(rf"\bassign\s+{re.escape(signal)}\s*=\s*(.*?);", clean, re.DOTALL)
    if len(matches) != 1:
        raise CheckFailure(f"{context}: expected one continuous assignment to {signal}")
    return compact(matches[0])


def validate_system_top(text: str) -> None:
    context = SYSTEM_TOP_REL.as_posix()
    require_regex(text, r"\bmodule\s+trecap_bram_replay_system_top\b", context)
    source_params, source_ports = one_instance(
        text, "trecap_source_core_integration", "u_source_core_integration", context
    )
    full_params, full_ports = one_instance(
        text, "trecap_de1soc_full_top", "u_full_top", context
    )
    _, e2e_ports = one_instance(
        text,
        "trecap_bram_replay_e2e_supervisor",
        "u_replay_e2e_supervisor",
        context,
    )
    require_bindings(
        source_params,
        {
            "X_MEMH_FILE": "X_MEMH_FILE",
            "REPLAY_MEM_DEPTH": "REPLAY_MEM_DEPTH",
            "REPLAY_INPUT_SAMPLES": "REPLAY_INPUT_SAMPLES",
            "RESET_SOURCE_MODE": "TSRC_BRAM_REPLAY",
        },
        f"{context} source/core parameters",
    )
    require_bindings(
        source_ports,
        {
            "clear_i": "replay_epoch_clear_w",
            "requested_source_mode_i": "ctrl_w.source_mode",
            "source_mode_apply_pulse_i": "source_mode_apply_pulse_w",
            "audio_sample_valid_i": "1'b0",
            "adc_sample_valid_i": "1'b0",
            "replay_start_i": "replay_owner_start_w",
            "replay_start_admit_i": "replay_start_admit_w",
            "y_ready_i": "y_ready_i",
            "replay_done_o": "replay_source_done_o",
            "replay_path_busy_o": "replay_path_busy_o",
            "replay_path_done_o": "replay_path_done_o",
            "replay_path_done_pulse_o": "replay_path_done_pulse_o",
            "replay_start_accept_pulse_o": "replay_start_accept_w",
            "replay_start_reject_pulse_o": "replay_start_reject_w",
            "replay_completion_error_sticky_o": "replay_completion_error_sticky_o",
            "tap_sample_o": "tap_sample_w",
            "tap_frame_o": "tap_frame_w",
            "tap_bin_valid_o": "tap_bin_valid_w",
            "core_sample_count_o": "core_sample_count_o",
            "core_frame_count_o": "core_frame_count_o",
        },
        f"{context} source/core ports",
    )
    require_bindings(
        full_params,
        {"SYNC_TOP_RESET_DEASSERTION": "1'b0"},
        f"{context} logical full-top parameters",
    )
    require_bindings(
        full_ports,
        {
            "external_transport_clear_i": "clear_i||!enable_i",
            "external_telemetry_flush_i": "replay_start_accept_w",
            "tap_sample_i": "tap_sample_w",
            "tap_frame_i": "tap_frame_w",
            "tap_bin_valid_i": "tap_bin_valid_w",
            "core_frame_count_i": "core_frame_count_o",
            "core_sample_count_i": "core_sample_count_o",
            "status_tick_i": "status_tick_to_transport_w",
            "transport_epoch_idle_o": "transport_epoch_idle_w",
            "transport_epoch_idle_stable_o": "transport_epoch_idle_stable_w",
            "replay_start_accept_pulse_i": "csr_replay_accept_feedback_w",
            "replay_start_reject_pulse_i": "csr_replay_reject_feedback_w",
            "replay_rearm_required_i": "replay_rearm_required_w",
            "replay_start_pulse_o": "csr_replay_start_w",
            "replay_rearm_pulse_o": "csr_replay_rearm_w",
            "avm_address_o": "avm_address_o",
            "avm_write_o": "avm_write_o",
            "avm_writedata_o": "avm_writedata_o",
            "avm_byteenable_o": "avm_byteenable_o",
            "avm_burstcount_o": "avm_burstcount_o",
            "avm_waitrequest_i": "avm_waitrequest_i",
            "avm_writeresponsevalid_i": "avm_writeresponsevalid_i",
            "avm_response_i": "avm_response_i",
        },
        f"{context} logical full-top ports",
    )
    require_bindings(
        e2e_ports,
        {
            "clear_i": "replay_epoch_clear_w",
            "replay_start_accept_pulse_i": "replay_start_accept_w",
            "replay_path_busy_i": "replay_path_busy_o",
            "replay_path_done_i": "replay_path_done_o",
            "replay_path_done_pulse_i": "replay_path_done_pulse_o",
            "replay_completion_error_sticky_i": "replay_completion_error_sticky_o",
            "completion_fault_i": "replay_e2e_completion_fault_w",
            "transport_ready_i": "replay_e2e_transport_ready_w",
            "transport_clear_pulse_i": "telemetry_soft_reset_pulse_w",
            "transport_fault_i": "replay_e2e_transport_fault_w",
            "writer_idle_i": "writer_idle_w",
            "writer_busy_i": "writer_busy_o",
            "normal_commit_pulse_i": "normal_commit_pulse_o",
            "producer_ptr_i": "producer_ptr_o",
            "dma_packet_count_i": "dma_packet_count_o",
            "dma_drop_count_i": "dma_drop_count_o",
            "packet_fifo_drop_count_i": "packet_fifo_drop_count_o",
            "replay_e2e_busy_o": "replay_e2e_busy_o",
            "replay_e2e_done_o": "replay_e2e_done_o",
            "replay_e2e_done_pulse_o": "replay_e2e_done_pulse_o",
            "replay_e2e_error_sticky_o": "replay_e2e_error_sticky_o",
        },
        f"{context} E2E supervisor ports",
    )
    require_equal(
        assignment_expression(text, "replay_start_admit_w", context),
        "replay_e2e_transport_ready_w&&transport_epoch_idle_w&&transport_epoch_idle_stable_w&&!replay_e2e_busy_o&&!replay_rearm_required_w",
        f"{context} replay admission",
    )
    require_equal(
        assignment_expression(text, "replay_epoch_clear_w", context),
        "clear_i||!enable_i||csr_replay_rearm_w",
        f"{context} replay/E2E abort and rearm",
    )
    for signal, expected in (
        (
            "csr_replay_forward_w",
            "!replay_epoch_clear_w&&(replay_request_origin_q==REPLAY_ORIGIN_NONE)&&(csr_replay_queued_q||csr_replay_start_w)",
        ),
        (
            "key_replay_forward_w",
            "!replay_epoch_clear_w&&(replay_request_origin_q==REPLAY_ORIGIN_NONE)&&!csr_replay_forward_w&&replay_start_i",
        ),
        (
            "replay_owner_start_w",
            "csr_replay_forward_w||key_replay_forward_w",
        ),
        (
            "replay_request_busy_w",
            "(replay_request_origin_q!=REPLAY_ORIGIN_NONE)||csr_replay_queued_q||csr_replay_start_w||replay_start_i",
        ),
        (
            "csr_replay_feedback_enable_w",
            "(replay_request_origin_q==REPLAY_ORIGIN_CSR)||((replay_request_origin_q==REPLAY_ORIGIN_NONE)&&csr_replay_forward_w)",
        ),
        (
            "csr_replay_accept_feedback_w",
            "!replay_epoch_clear_w&&replay_start_accept_w&&csr_replay_feedback_enable_w",
        ),
        (
            "csr_replay_reject_feedback_w",
            "(!replay_epoch_clear_w&&replay_start_reject_w&&csr_replay_feedback_enable_w)||csr_replay_abort_reject_q",
        ),
    ):
        require_equal(
            assignment_expression(text, signal, context),
            expected,
            f"{context} KEY/CSR replay arbitration {signal}",
        )
    system_compact = compact(strip_sv_comments(text))
    for token in (
        "if(replay_epoch_clear_w)begin",
        "csr_replay_abort_reject_q<=(replay_request_origin_q==REPLAY_ORIGIN_CSR)||csr_replay_queued_q||csr_replay_start_w;",
        "replay_request_origin_q<=REPLAY_ORIGIN_NONE;",
        "csr_replay_queued_q<=1'b0;",
    ):
        require_token(token=token, text=system_compact, context=f"{context} replay abort isolation")
    transport_ready = assignment_expression(text, "replay_e2e_transport_ready_w", context)
    for token in (
        "ring_configured_o",
        "ctrl_w.telemetry_enable",
        "ctrl_w.ring_writer_enable",
        "ctrl_w.packet_enable==TCSR_PACKET_ENABLE_STATUS_EN_MASK",
        "!telemetry_config_illegal_w",
    ):
        require_token(transport_ready, token, f"{context} STATUS-only transport readiness")
    status_request = assignment_expression(text, "status_tick_to_transport_w", context)
    for token in (
        "replay_path_done_pulse_o",
        "status_tick_i",
        "!replay_e2e_busy_o",
        "!replay_path_busy_o",
        "!replay_start_accept_w",
    ):
        require_token(status_request, token, f"{context} replay-correlated STATUS request")
    if parse_instances(text, "trecap_core_top"):
        raise CheckFailure(f"{context}: direct second mathematical core is forbidden")
    if parse_instances(text, "trecap_core_telemetry_top"):
        raise CheckFailure(f"{context}: standalone second-core composition is forbidden")
    forbid_regex(
        compact(strip_sv_comments(text)),
        r"requested_source_mode_i\(TSRC_BRAM_REPLAY\)",
        f"{context} runtime CSR source-mode path",
    )


def validate_e2e_supervisor(text: str) -> None:
    context = E2E_SUPERVISOR_REL.as_posix()
    require_regex(text, r"\bmodule\s+trecap_bram_replay_e2e_supervisor\b", context)
    for signal in (
        "replay_start_accept_pulse_i",
        "replay_path_busy_i",
        "replay_path_done_i",
        "replay_path_done_pulse_i",
        "replay_completion_error_sticky_i",
        "transport_ready_i",
        "transport_fault_i",
        "writer_idle_i",
        "writer_busy_i",
        "normal_commit_pulse_i",
        "producer_ptr_i",
        "dma_packet_count_i",
        "dma_drop_count_i",
        "packet_fifo_drop_count_i",
        "replay_e2e_busy_o",
        "replay_e2e_done_o",
        "replay_e2e_done_pulse_o",
        "replay_e2e_error_sticky_o",
    ):
        require_regex(text, rf"\b{re.escape(signal)}\b", f"{context} interface")

    counter_fault = assignment_expression(text, "transport_counter_fault_w", context)
    for token in (
        "dma_drop_count_i!=start_dma_drop_count_q",
        "packet_fifo_drop_count_i!=start_packet_fifo_drop_count_q",
    ):
        require_token(counter_fault, token, f"{context} drop-count fault")
    epoch_fault = assignment_expression(text, "epoch_fault_w", context)
    for token in (
        "replay_completion_error_sticky_i",
        "completion_fault_i",
        "transport_fault_i",
        "transport_counter_fault_w",
        "transport_clear_pulse_i",
    ):
        require_token(epoch_fault, token, f"{context} epoch fault")
    progress = assignment_expression(text, "post_core_progress_w", context)
    for token in (
        "producer_ptr_i!=post_core_producer_ptr_q",
        "dma_packet_count_i!=post_core_dma_packet_count_q",
    ):
        require_token(progress, token, f"{context} post-core transport progress")
    busy = assignment_expression(text, "replay_e2e_busy_o", context)
    for token in ("replay_e2e_inflight_q", "replay_path_busy_i"):
        require_token(busy, token, f"{context} E2E busy")
    done = assignment_expression(text, "replay_e2e_done_o", context)
    for token in (
        "replay_e2e_done_q",
        "replay_path_done_i",
        "!replay_e2e_busy_o",
        "!replay_e2e_error_sticky_q",
    ):
        require_token(done, token, f"{context} E2E done")

    clean = strip_sv_comments(text)
    label_match = re.search(r"\bbegin\s*:\s*p_replay_e2e_completion\b", clean)
    if label_match is None:
        raise CheckFailure(f"{context}: p_replay_e2e_completion block is missing")
    monitor_end = clean.find("`ifndef", label_match.end())
    if monitor_end < 0:
        raise CheckFailure(f"{context}: cannot delimit p_replay_e2e_completion block")
    monitor = compact(clean[label_match.start() : monitor_end])
    for token in (
        "replay_start_accept_pulse_i",
        "replay_e2e_inflight_q<=1'b1",
        "replay_e2e_error_sticky_q<=!transport_ready_i||transport_clear_pulse_i||",
        "transport_fault_i||replay_completion_error_sticky_i||completion_fault_i",
        "start_dma_drop_count_q<=dma_drop_count_i",
        "start_packet_fifo_drop_count_q<=packet_fifo_drop_count_i",
        "if(!baseline_valid_q)begin",
        "if(!transport_ready_i||epoch_fault_w)beginreplay_e2e_error_sticky_q<=1'b1",
        "replay_path_done_pulse_i",
        "core_done_seen_q<=1'b1",
        "post_core_producer_ptr_q<=producer_ptr_i",
        "post_core_dma_packet_count_q<=dma_packet_count_i",
        "normal_commit_pulse_i&&baseline_valid_q&&",
        "core_done_seen_q||replay_path_done_pulse_i",
        "post_core_commit_seen_q<=1'b1",
        "baseline_valid_q&&core_done_seen_q&&replay_path_done_i",
        "post_core_commit_seen_q",
        "post_core_progress_w&&writer_idle_i&&!writer_busy_i",
        "transport_ready_i&&!epoch_fault_w",
        "!replay_e2e_error_sticky_q",
        "replay_e2e_done_q<=1'b1",
        "replay_e2e_done_pulse_q<=1'b1",
        "if(clear_i)beginreplay_e2e_inflight_q<=1'b0;replay_e2e_done_q<=1'b0",
        "elseif(replay_start_accept_pulse_i)beginreplay_e2e_inflight_q<=1'b1;replay_e2e_done_q<=1'b0",
        "elseif(replay_e2e_inflight_q)begin",
        "if(replay_e2e_error_sticky_q&&!replay_path_busy_i&&writer_idle_i&&!writer_busy_i)begin"
        "replay_e2e_inflight_q<=1'b0;end",
    ):
        require_token(monitor, token, f"{context} E2E completion supervisor")
    if len(re.findall(r"replay_e2e_done_q<=", monitor)) != 4:
        raise CheckFailure(
            f"{context}: retained E2E result may change only on reset, clear, new epoch, or success"
        )
    forbid_regex(
        monitor,
        r"if\(replay_path_done(?:_pulse)?_i\)beginreplay_e2e_done_q<=1'b1",
        f"{context} core-path done cannot directly assert E2E done",
    )


def validate_completion_monitor(text: str) -> None:
    context = SOURCE_CORE_REL.as_posix()
    replay_params, replay_ports = one_instance(
        text, "trecap_bram_replay_source", "u_bram_replay_source", context
    )
    _, core_ports = one_instance(text, "trecap_core_top", "u_core", context)
    require_bindings(
        replay_params,
        {
            "INPUT_SAMPLES": "REPLAY_INPUT_SAMPLES",
            "FLUSH_SAMPLES": "REPLAY_FLUSH_SAMPLES",
        },
        f"{context} BRAM source parameters",
    )
    require_bindings(
        replay_ports,
        {
            "done_o": "replay_done_o",
            "output_accept_count_o": "replay_output_accept_count_o",
        },
        f"{context} BRAM source status",
    )
    require_bindings(
        core_ports,
        {
            "y_valid_o": "y_valid_o",
            "y_ready_i": "y_ready_i",
            "y_sample_idx_o": "y_sample_idx_o",
            "core_sample_count_o": "core_sample_count_o",
            "core_frame_count_o": "core_frame_count_o",
            "core_error_sample_count_o": "core_error_sample_count_o",
            "wola_output_count_o": "wola_output_count_w",
        },
        f"{context} core completion observations",
    )

    require_equal(
        assignment_expression(text, "replay_y_accept_w", context),
        "y_valid_o&&y_ready_i",
        f"{context} accepted-y event",
    )
    require_regex(
        text,
        r"\binput\s+logic\s+replay_start_admit_i\b",
        f"{context} admission interface",
    )
    require_equal(
        assignment_expression(text, "replay_start_request_w", context),
        "replay_start_i||replay_auto_start_pending_q",
        f"{context} raw replay request preservation",
    )
    replay_qualified = assignment_expression(text, "replay_start_qualified_w", context)
    for token in (
        "replay_start_request_w",
        "replay_start_admit_i",
        "mode_is_bram_w",
        "!replay_path_inflight_q",
        "LOCAL_BUILD_CONTRACT_OK",
    ):
        require_token(replay_qualified, token, f"{context} accepted-start qualification")
    require_equal(
        assignment_expression(text, "replay_start_local_reject_w", context),
        "replay_start_i&&!replay_start_qualified_w",
        f"{context} denied-start evidence",
    )
    replay_reject = assignment_expression(text, "replay_start_reject_pulse_o", context)
    for token in ("replay_start_reject_w", "replay_start_local_reject_w"):
        require_token(replay_reject, token, f"{context} replay reject output")
    structural_busy = assignment_expression(text, "replay_path_structural_busy_w", context)
    for token in (
        "replay_active_o",
        "mux_sample_valid_w",
        "core_busy_o",
        "y_valid_o",
    ):
        require_token(structural_busy, token, f"{context} structural-busy expression")
    quiescent = assignment_expression(text, "replay_path_quiescent_w", context)
    for token in ("replay_done_o", "!replay_path_structural_busy_w"):
        require_token(quiescent, token, f"{context} quiescence expression")

    exact_counts = assignment_expression(text, "replay_path_exact_counts_w", context)
    for token in (
        "replay_core_output_accept_count_q==REPLAY_OUTPUT_SAMPLES",
        "replay_output_accept_count_o==REPLAY_OUTPUT_SAMPLES",
        "wola_output_count_w==REPLAY_OUTPUT_SAMPLES",
        "core_sample_count_o==REPLAY_TAU_LAST",
        "core_frame_count_o==REPLAY_NFRAMES",
        "core_error_sample_count_o==REPLAY_OUTPUT_SAMPLES",
        "replay_metric_commit_count_q==REPLAY_OUTPUT_SAMPLES",
    ):
        require_token(exact_counts, token, f"{context} exact-count expression")

    path_done = assignment_expression(text, "replay_path_done_o", context)
    for token in ("replay_path_done_q", "!replay_path_structural_busy_w"):
        require_token(path_done, token, f"{context} exact path-done expression")
    if path_done == "replay_done_o" or "replay_done_o" in path_done:
        raise CheckFailure(f"{context}: path-done must be retained exact state, not source-done")

    clean = strip_sv_comments(text)
    label_match = re.search(r"\bbegin\s*:\s*p_replay_exact_completion\b", clean)
    if label_match is None:
        raise CheckFailure(f"{context}: p_replay_exact_completion block is missing")
    monitor_end = clean.find("always_comb", label_match.end())
    if monitor_end < 0:
        raise CheckFailure(f"{context}: cannot delimit p_replay_exact_completion block")
    monitor = compact(clean[label_match.start() : monitor_end])
    for token in (
        "replay_start_accept_w",
        "replay_path_inflight_q<=1'b1",
        "replay_y_accept_w",
        "y_sample_idx_o!=replay_core_output_accept_count_q",
        "replay_core_output_accept_count_q+64'd1",
        "tap_sample_o.valid&&replay_path_inflight_q",
        "replay_metric_commit_count_q+64'd1",
        "replay_path_inflight_q&&replay_path_quiescent_w",
        "replay_path_exact_counts_w&&!replay_path_fault_w",
        "!replay_completion_error_sticky_q",
        "replay_path_done_q<=1'b1",
        "replay_path_done_pulse_q<=1'b1",
        "replay_completion_error_sticky_q<=1'b1",
        "elsebeginreplay_path_inflight_q<=1'b0;replay_path_done_q<=1'b0;"
        "replay_completion_error_sticky_q<=1'b1;end",
    ):
        require_token(monitor, token, f"{context} exact-completion monitor")
    forbid_regex(
        monitor,
        r"if\(replay_done_o\)beginreplay_path_done_q<=1'b1",
        f"{context} source-done alias",
    )


def validate_board_top(text: str) -> None:
    context = BOARD_TOP_REL.as_posix()
    source_params, source_ports = one_instance(
        text, "trecap_source_core_integration", "u_source_core_integration", context
    )
    _, full_ports = one_instance(text, "trecap_de1soc_full_top", "u_full_top", context)
    _, pd_ports = one_instance(text, "platform_designer_wrapper", "u_platform_designer_wrapper", context)
    _, e2e_ports = one_instance(
        text,
        "trecap_bram_replay_e2e_supervisor",
        "u_replay_e2e_supervisor",
        context,
    )
    for abort_signal in ("key_press_pulse[3]", "csr_replay_rearm"):
        if abort_signal in full_ports.get("external_telemetry_flush_i", ""):
            raise CheckFailure(
                f"{context}: {abort_signal} must not flush telemetry/FIFO while writer state is retained"
            )
    require_bindings(
        source_params,
        {
            "X_MEMH_FILE": "REPLAY_X_MEMH_FILE",
            "REPLAY_INPUT_SAMPLES": "REPLAY_INPUT_SAMPLES",
            "RESET_SOURCE_MODE": "TSRC_BRAM_REPLAY",
        },
        f"{context} source/core parameters",
    )
    require_bindings(
        source_ports,
        {
            "clear_i": "key_press_pulse[3]||csr_replay_rearm",
            "requested_source_mode_i": "ctrl.source_mode",
            "source_mode_apply_pulse_i": "source_mode_apply_pulse",
            "replay_start_i": "replay_owner_start",
            "replay_start_admit_i": "replay_start_admit",
            "y_ready_i": "1'b1",
            "replay_done_o": "replay_done",
            "replay_path_busy_o": "replay_path_busy",
            "replay_path_done_o": "replay_path_done",
            "replay_path_done_pulse_o": "replay_path_done_pulse",
            "replay_start_accept_pulse_o": "replay_start_accept",
            "replay_start_reject_pulse_o": "replay_start_reject",
            "replay_completion_error_sticky_o": "replay_completion_error_sticky",
            "tap_sample_o": "tap_sample",
            "tap_frame_o": "tap_frame",
            "tap_bin_valid_o": "tap_bin_valid",
        },
        f"{context} source/core ports",
    )
    require_bindings(
        full_ports,
        {
            "external_transport_clear_i": "1'b0",
            "external_telemetry_flush_i": "replay_start_accept",
            "tap_sample_i": "tap_sample",
            "tap_frame_i": "tap_frame",
            "tap_bin_valid_i": "tap_bin_valid",
            "core_frame_count_i": "core_frame_count",
            "core_sample_count_i": "core_sample_count",
            "status_tick_i": "status_tick_to_transport",
            "transport_epoch_idle_o": "transport_epoch_idle",
            "transport_epoch_idle_stable_o": "transport_epoch_idle_stable",
            "replay_start_accept_pulse_i": "csr_replay_accept_feedback",
            "replay_start_reject_pulse_i": "csr_replay_reject_feedback",
            "replay_rearm_required_i": "replay_rearm_required",
            "replay_start_pulse_o": "csr_replay_start",
            "replay_rearm_pulse_o": "csr_replay_rearm",
            "avm_address_o": "avm_address",
            "avm_write_o": "avm_write",
            "avm_writedata_o": "avm_writedata",
            "avm_byteenable_o": "avm_byteenable",
            "avm_burstcount_o": "avm_burstcount",
            "avm_waitrequest_i": "avm_waitrequest",
            "avm_writeresponsevalid_i": "avm_writeresponsevalid",
            "avm_response_i": "avm_response",
        },
        f"{context} logical telemetry/HPS ports",
    )
    require_bindings(
        pd_ports,
        {
            "avm_address_i": "avm_address",
            "avm_write_i": "avm_write",
            "avm_writedata_i": "avm_writedata",
            "avm_byteenable_i": "avm_byteenable",
            "avm_burstcount_i": "avm_burstcount",
            "avm_waitrequest_o": "avm_waitrequest",
            "avm_writeresponsevalid_o": "avm_writeresponsevalid",
            "avm_response_o": "avm_response",
            "HPS_DDR3_ADDR": "HPS_DDR3_ADDR",
            "HPS_DDR3_DQ": "HPS_DDR3_DQ",
            "HPS_DDR3_RZQ": "HPS_DDR3_RZQ",
        },
        f"{context} Platform Designer/DDR ports",
    )
    require_bindings(
        e2e_ports,
        {
            "clear_i": "key_press_pulse[3]||csr_replay_rearm",
            "replay_start_accept_pulse_i": "replay_start_accept",
            "replay_path_busy_i": "replay_path_busy",
            "replay_path_done_i": "replay_path_done",
            "replay_path_done_pulse_i": "replay_path_done_pulse",
            "replay_completion_error_sticky_i": "replay_completion_error_sticky",
            "completion_fault_i": "replay_e2e_completion_fault",
            "transport_ready_i": "replay_e2e_transport_ready",
            "transport_clear_pulse_i": "telemetry_soft_reset_pulse",
            "transport_fault_i": "replay_e2e_transport_fault",
            "writer_idle_i": "writer_idle",
            "writer_busy_i": "writer_busy",
            "normal_commit_pulse_i": "normal_commit_pulse",
            "producer_ptr_i": "producer_ptr",
            "dma_packet_count_i": "dma_packet_count",
            "dma_drop_count_i": "dma_drop_count",
            "packet_fifo_drop_count_i": "packet_fifo_drop_count",
            "replay_e2e_busy_o": "replay_e2e_busy",
            "replay_e2e_done_o": "replay_e2e_done",
            "replay_e2e_done_pulse_o": "replay_e2e_done_pulse",
            "replay_e2e_error_sticky_o": "replay_e2e_error_sticky",
        },
        f"{context} E2E supervisor ports",
    )
    require_equal(
        assignment_expression(text, "replay_start_admit", context),
        "replay_e2e_transport_ready&&transport_epoch_idle&&transport_epoch_idle_stable&&!replay_e2e_busy&&!replay_rearm_required",
        f"{context} replay admission",
    )
    require_equal(
        assignment_expression(text, "replay_epoch_clear", context),
        "key_press_pulse[3]||csr_replay_rearm",
        f"{context} KEY/CSR replay abort and rearm",
    )
    for signal, expected in (
        (
            "csr_replay_forward",
            "!replay_epoch_clear&&(replay_request_origin_q==REPLAY_ORIGIN_NONE)&&(csr_replay_queued_q||csr_replay_start)",
        ),
        (
            "key_replay_forward",
            "!replay_epoch_clear&&(replay_request_origin_q==REPLAY_ORIGIN_NONE)&&!csr_replay_forward&&key_press_pulse[1]",
        ),
        ("replay_owner_start", "csr_replay_forward||key_replay_forward"),
        (
            "replay_request_busy",
            "(replay_request_origin_q!=REPLAY_ORIGIN_NONE)||csr_replay_queued_q||csr_replay_start||key_press_pulse[1]",
        ),
        (
            "csr_replay_feedback_enable",
            "(replay_request_origin_q==REPLAY_ORIGIN_CSR)||((replay_request_origin_q==REPLAY_ORIGIN_NONE)&&csr_replay_forward)",
        ),
        (
            "csr_replay_accept_feedback",
            "!replay_epoch_clear&&replay_start_accept&&csr_replay_feedback_enable",
        ),
        (
            "csr_replay_reject_feedback",
            "(!replay_epoch_clear&&replay_start_reject&&csr_replay_feedback_enable)||csr_replay_abort_reject_q",
        ),
    ):
        require_equal(
            assignment_expression(text, signal, context),
            expected,
            f"{context} KEY/CSR replay arbitration {signal}",
        )
    board_compact = compact(strip_sv_comments(text))
    for token in (
        "if(replay_epoch_clear)begin",
        "csr_replay_abort_reject_q<=(replay_request_origin_q==REPLAY_ORIGIN_CSR)||csr_replay_queued_q||csr_replay_start;",
        "replay_request_origin_q<=REPLAY_ORIGIN_NONE;",
        "csr_replay_queued_q<=1'b0;",
    ):
        require_token(token=token, text=board_compact, context=f"{context} replay abort isolation")
    board_transport_ready = assignment_expression(text, "replay_e2e_transport_ready", context)
    for token in (
        "ring_configured",
        "ctrl.telemetry_enable",
        "ctrl.ring_writer_enable",
        "ctrl.packet_enable==TCSR_PACKET_ENABLE_STATUS_EN_MASK",
        "!telemetry_config_illegal",
    ):
        require_token(board_transport_ready, token, f"{context} STATUS-only transport readiness")
    board_status_request = assignment_expression(text, "status_tick_to_transport", context)
    for token in (
        "replay_path_done_pulse",
        "status_tick",
        "!replay_e2e_busy",
        "!replay_path_busy",
        "!replay_start_accept",
    ):
        require_token(board_status_request, token, f"{context} replay-correlated STATUS request")
    adc_manual_request = assignment_expression(text, "adc_manual_request", context)
    require_token(
        adc_manual_request,
        "key_press_pulse[2]",
        f"{context} frozen ADC manual-request binding",
    )
    require_equal(
        assignment_expression(text, "LEDR[8]", context),
        "replay_e2e_busy",
        f"{context} busy LED",
    )
    require_equal(
        assignment_expression(text, "LEDR[9]", context),
        "replay_e2e_done",
        f"{context} E2E-done LED",
    )
    led7 = assignment_expression(text, "LEDR[7]", context)
    require_token(led7, "replay_completion_error_sticky", f"{context} fault LED")
    require_token(led7, "replay_e2e_error_sticky", f"{context} E2E fault LED")
    if parse_instances(text, "trecap_core_top") or parse_instances(text, "trecap_core_telemetry_top"):
        raise CheckFailure(f"{context}: direct or duplicate mathematical core is forbidden")


def validate_transport_hierarchy(
    full_top: str,
    telemetry: str,
    hps_bridge: str,
    ddr_writer: str,
    pd_wrapper: str,
) -> None:
    _, telemetry_ports = one_instance(
        full_top, "trecap_telemetry_top", "u_telemetry_top", FULL_TOP_REL.as_posix()
    )
    _, hps_ports = one_instance(
        full_top, "trecap_hps_bridge_top", "u_hps_bridge_top", FULL_TOP_REL.as_posix()
    )
    require_bindings(
        telemetry_ports,
        {
            "telemetry_soft_reset_i": "telemetry_soft_clear_w",
            "formatter_flush_i": "formatter_flush_w",
            "counter_clear_i": "counter_clear_pulse_w",
            "tap_sample_i": "tap_sample_i",
            "tap_frame_i": "tap_frame_i",
            "tap_bin_valid_i": "tap_bin_valid_i",
            "record_valid_o": "record_valid_w",
            "record_ready_i": "record_ready_w",
            "record_meta_o": "record_meta_w",
            "record_payload_data_o": "record_payload_data_w",
            "record_payload_keep_o": "record_payload_keep_w",
            "record_payload_last_o": "record_payload_last_w",
        },
        f"{FULL_TOP_REL.as_posix()} telemetry bindings",
    )
    require_bindings(
        hps_ports,
        {
            "external_transport_clear_i": "external_transport_clear_i",
            "record_valid_i": "record_valid_w",
            "record_ready_o": "record_ready_w",
            "record_meta_i": "record_meta_w",
            "record_payload_data_i": "record_payload_data_w",
            "record_payload_keep_i": "record_payload_keep_w",
            "record_payload_last_i": "record_payload_last_w",
            "avm_address_o": "avm_address_o",
            "avm_write_o": "avm_write_o",
            "avm_writedata_o": "avm_writedata_o",
            "avm_byteenable_o": "avm_byteenable_o",
            "avm_burstcount_o": "avm_burstcount_o",
            "avm_waitrequest_i": "avm_waitrequest_i",
            "avm_writeresponsevalid_i": "avm_writeresponsevalid_i",
            "avm_response_i": "avm_response_i",
        },
        f"{FULL_TOP_REL.as_posix()} HPS bridge bindings",
    )
    full_context = FULL_TOP_REL.as_posix()
    require_equal(
        assignment_expression(full_top, "telemetry_soft_clear_w", full_context),
        "telemetry_soft_reset_pulse_w|external_transport_clear_i",
        f"{full_context} telemetry soft reset",
    )
    require_equal(
        assignment_expression(full_top, "formatter_flush_w", full_context),
        "transport_epoch_idle_q&&(external_telemetry_flush_i||(source_discontinuity_i&&source_mode_apply_pulse_w))",
        f"{full_context} quiescent telemetry-only formatter/FIFO flush",
    )
    require_equal(
        assignment_expression(full_top, "telemetry_clear_w", full_context),
        "telemetry_soft_clear_w|formatter_flush_w",
        f"{full_context} combined telemetry status clear",
    )
    require_equal(
        assignment_expression(full_top, "transport_epoch_idle_o", full_context),
        "writer_idle_o&&!record_valid_w",
        f"{full_context} transport epoch idle",
    )
    full_clean = strip_sv_comments(full_top)
    if len(re.findall(r"\bexternal_telemetry_flush_i\b", full_clean)) != 2:
        raise CheckFailure(
            f"{full_context}: external telemetry flush must be confined to the formatter/FIFO clear"
        )
    if re.search(r"\by_ready", strip_sv_comments(full_top)):
        raise CheckFailure(f"{FULL_TOP_REL}: telemetry/HPS hierarchy must not own core y_ready")

    _, wave_ports = one_instance(
        telemetry, "trecap_wave_packetizer", "u_wave_packetizer", TELEMETRY_REL.as_posix()
    )
    _, fifo_ports = one_instance(
        telemetry, "trecap_packet_fifo", "u_packet_fifo", TELEMETRY_REL.as_posix()
    )
    require_bindings(
        wave_ports,
        {"tap_sample_i": "tap_sample_i"},
        f"{TELEMETRY_REL.as_posix()} real sample tap",
    )
    require_bindings(
        fifo_ports,
        {
            "out_payload_data_o": "record_payload_data_o",
            "out_payload_keep_o": "record_payload_keep_o",
            "out_payload_last_o": "record_payload_last_o",
        },
        f"{TELEMETRY_REL.as_posix()} packet FIFO output",
    )

    _, writer_ports = one_instance(
        hps_bridge, "trecap_ddr_ring_writer", "u_ddr_ring_writer", HPS_BRIDGE_REL.as_posix()
    )
    require_bindings(
        writer_ports,
        {
            "record_payload_data_i": "record_payload_data_i",
            "record_payload_keep_i": "record_payload_keep_i",
            "record_payload_last_i": "record_payload_last_i",
            "avm_address_o": "avm_address_o",
            "avm_write_o": "avm_write_o",
            "avm_writedata_o": "avm_writedata_o",
            "avm_byteenable_o": "avm_byteenable_o",
            "avm_burstcount_o": "avm_burstcount_o",
            "avm_waitrequest_i": "avm_waitrequest_i",
            "avm_writeresponsevalid_i": "avm_writeresponsevalid_i",
            "avm_response_i": "avm_response_i",
        },
        f"{HPS_BRIDGE_REL.as_posix()} DDR writer bindings",
    )

    avmm_params, avmm_ports = one_instance(
        ddr_writer, "trecap_avmm_write_master", "u_avmm_write_master", DDR_WRITER_REL.as_posix()
    )
    require_bindings(
        avmm_params,
        {"CHECK_RESPONSES": "1'b1"},
        f"{DDR_WRITER_REL.as_posix()} response-checked Avalon-MM master",
    )
    require_bindings(
        avmm_ports,
        {
            "avm_address_o": "avm_address_o",
            "avm_write_o": "avm_write_o",
            "avm_writedata_o": "avm_writedata_o",
            "avm_byteenable_o": "avm_byteenable_o",
            "avm_burstcount_o": "avm_burstcount_o",
            "avm_waitrequest_i": "avm_waitrequest_i",
            "avm_writeresponsevalid_i": "avm_writeresponsevalid_i",
            "avm_response_i": "avm_response_i",
        },
        f"{DDR_WRITER_REL.as_posix()} Avalon-MM master bindings",
    )
    writer_context = DDR_WRITER_REL.as_posix()
    producer_advance = assignment_expression(
        ddr_writer, "producer_advance_valid", writer_context
    )
    for token in ("!avmm_response_error_now", "!avmm_response_error_sticky"):
        require_token(producer_advance, token, f"{writer_context} response-qualified commit")

    _, pd_ports = one_instance(pd_wrapper, "system", "u_platform_designer_system", PD_WRAPPER_REL.as_posix())
    require_bindings(
        pd_ports,
        {
            "memory_mem_a": "HPS_DDR3_ADDR",
            "memory_mem_dq": "HPS_DDR3_DQ",
            "memory_oct_rzqin": "HPS_DDR3_RZQ",
            "trecap_f2h_sdram0_address": "pd_ddr_address",
            "trecap_f2h_sdram0_write": "pd_ddr_write",
            "trecap_f2h_sdram0_writedata": "avm_writedata_i",
            "trecap_f2h_sdram0_byteenable": "avm_byteenable_i",
            "trecap_f2h_sdram0_waitrequest": "pd_ddr_waitrequest",
        },
        f"{PD_WRAPPER_REL.as_posix()} generated F2SDRAM/HPS DDR bindings",
    )
    for signal in ("pd_ddr_address", "pd_ddr_write", "avm_waitrequest_o"):
        assignment_expression(pd_wrapper, signal, PD_WRAPPER_REL.as_posix())
    pd_context = PD_WRAPPER_REL.as_posix()
    require_equal(
        assignment_expression(pd_wrapper, "ddr_address_in_range", pd_context),
        "(avm_address_i<HPS_DDR_END_EXCLUSIVE)",
        f"{pd_context} local DDR range guard",
    )
    require_equal(
        assignment_expression(pd_wrapper, "ddr_address_reject", pd_context),
        "avm_write_i&&!ddr_address_in_range",
        f"{pd_context} local DDR range reject",
    )
    require_equal(
        assignment_expression(pd_wrapper, "pd_ddr_write", pd_context),
        "avm_write_i&&ddr_address_in_range",
        f"{pd_context} legal F2SDRAM request",
    )
    require_equal(
        assignment_expression(pd_wrapper, "ddr_write_accept", pd_context),
        "avm_write_i&&!avm_waitrequest_o",
        f"{pd_context} local bridge acceptance",
    )
    wrapper_clean = compact(strip_sv_comments(pd_wrapper))
    for token in (
        "AVMM_RESPONSE_OKAY=2'b00",
        "AVMM_RESPONSE_SLVERR=2'b10",
        "avm_waitrequest_o=ddr_address_reject?1'b0:pd_ddr_waitrequest",
        "avm_response_o=ddr_response_error_q?AVMM_RESPONSE_SLVERR:AVMM_RESPONSE_OKAY",
        "ddr_response_valid_q<=ddr_write_accept",
        "ddr_response_error_q<=ddr_write_accept&&ddr_address_reject",
    ):
        require_token(wrapper_clean, token, f"{pd_context} wrapper-local response authority")


def validate_avmm_response_closure(master: str, writer: str, wrapper: str) -> None:
    master_context = AVMM_MASTER_REL.as_posix()
    master_compact = compact(strip_sv_comments(master))
    for token in (
        "MSTATE_WAIT_RESPONSE=2'd2",
        "assignavm_write_o=enable_i&&(state_q==MSTATE_WRITE)&&hold_valid_q",
        "assignstream_ready_o=enable_i&&(state_q==MSTATE_WRITE)&&!hold_valid_q",
        "state_q==MSTATE_WAIT_RESPONSE",
        "avm_writeresponsevalid_i&&(avm_response_i==2'b00)",
        "state_q!=MSTATE_WAIT_RESPONSE",
        "response_completes_record_q<=write_done_ok",
        "state_q<=MSTATE_WAIT_RESPONSE",
        "if(response_success)begin",
        "if(response_completes_record_q)beginwrite_done_pulse_o<=1'b1",
        "write_done_pulse_o<=1'b1;state_q<=MSTATE_IDLE",
    ):
        require_token(master_compact, token, f"{master_context} response-serialized completion")

    writer_context = DDR_WRITER_REL.as_posix()
    writer_params, _ = one_instance(
        writer, "trecap_avmm_write_master", "u_avmm_write_master", writer_context
    )
    require_equal(
        writer_params.get("CHECK_RESPONSES"),
        "1'b1",
        f"{writer_context} response checking",
    )

    wrapper_context = PD_WRAPPER_REL.as_posix()
    wrapper_compact = compact(strip_sv_comments(wrapper))
    for token in (
        "assignddr_write_accept=avm_write_i&&!avm_waitrequest_o",
        "assignavm_writeresponsevalid_o=ddr_response_valid_q",
        "assignavm_response_o=ddr_response_error_q?AVMM_RESPONSE_SLVERR:AVMM_RESPONSE_OKAY",
        "ddr_response_valid_q<=ddr_write_accept",
        "ddr_response_error_q<=ddr_write_accept&&ddr_address_reject",
    ):
        require_token(wrapper_compact, token, f"{wrapper_context} one-response-per-accept")
    forbid_regex(
        wrapper_compact,
        r"ddr_reject_response_q",
        f"{wrapper_context} obsolete reject-only response",
    )


def validate_memh(path: Path, expected_rows: int, expected_sha256: str, context: str) -> None:
    actual_hash = sha256_file(path)
    if actual_hash != expected_sha256:
        raise CheckFailure(f"{context}: SHA-256 mismatch {actual_hash} != {expected_sha256}")
    rows = read_text(path).splitlines()
    if len(rows) != expected_rows:
        raise CheckFailure(f"{context}: expected {expected_rows} rows, found {len(rows)}")
    for index, row in enumerate(rows):
        if re.fullmatch(r"[0-9a-f]+", row) is None:
            raise CheckFailure(f"{context}: row {index} is not canonical lowercase hexadecimal")


def validate_vector_config(
    config: dict[str, Any],
    vector_name: str,
    ns: int,
    ny: int,
    frames: int,
    input_sha256: str,
    output_sha256: str,
    context: str,
) -> None:
    require_equal(config.get("schema"), "trecap_phase2_vector_config_v1", f"{context}.schema")
    require_equal(config.get("vector_name"), vector_name, f"{context}.vector_name")
    geometry = config.get("configuration")
    if not isinstance(geometry, dict):
        raise CheckFailure(f"{context}.configuration must be an object")
    require_equal(
        {key: geometry.get(key) for key in ("L", "H", "G", "D", "Ns", "Ny", "frames", "THR2")},
        {"L": 256, "H": 128, "G": 128, "D": 384, "Ns": ns, "Ny": ny, "frames": frames, "THR2": "0"},
        f"{context}.configuration",
    )
    expected_frames = (ns + 256 - 2) // 128
    expected_ny = expected_frames * 128 + 128 + 256
    if (expected_frames, expected_ny) != (frames, ny):
        raise CheckFailure(f"{context}: frozen full-tail geometry is internally inconsistent")
    stream_hashes = config.get("stream_hashes")
    if not isinstance(stream_hashes, dict):
        raise CheckFailure(f"{context}.stream_hashes must be an object")
    require_equal(stream_hashes.get("x_in_sha256"), input_sha256, f"{context} input hash")
    require_equal(stream_hashes.get("y_out_sha256"), output_sha256, f"{context} output hash")


def validate_profile(profile: dict[str, Any]) -> None:
    context = PROFILE_REL.as_posix()
    require_equal(profile.get("schema"), "trecap_phase2_runtime_profile_v1", f"{context}.schema")
    require_equal(profile.get("profile_kind"), "build", f"{context}.profile_kind")
    require_equal(profile.get("profile_name"), "de1soc_bram_replay", f"{context}.profile_name")
    build = profile.get("build")
    source = profile.get("input")
    transport = profile.get("transport")
    if not isinstance(build, dict) or not isinstance(source, dict) or not isinstance(transport, dict):
        raise CheckFailure(f"{context}: build, input, and transport must be objects")
    require_equal(
        {key: build.get(key) for key in ("target", "top_module", "platform", "board")},
        {
            "target": "de1soc_full",
            "top_module": "de1_soc_trecap_top",
            "platform": "de1soc",
            "board": "de1soc",
        },
        f"{context}.build",
    )
    require_equal(
        {key: source.get(key) for key in ("kind", "source_mode", "vector_config", "input_memh", "replay_start_policy")},
        {
            "kind": "bram_replay",
            "source_mode": "bram_replay",
            "vector_config": ZERO_CONFIG_REL.as_posix(),
            "input_memh": ZERO_INPUT_REL.as_posix(),
            "replay_start_policy": "board_key",
        },
        f"{context}.input",
    )
    require_equal(profile.get("telemetry_profile"), TELEMETRY_PROFILE_REL.as_posix(), f"{context}.telemetry_profile")
    require_equal(profile.get("sample_rate_hz"), 48_000, f"{context}.sample_rate_hz")
    require_equal(transport.get("hps_ddr_enable"), True, f"{context}.transport.hps_ddr_enable")
    require_equal(transport.get("hps_udp_enable"), True, f"{context}.transport.hps_udp_enable")


def active_filelist_entries(text: str) -> list[str]:
    entries: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("+incdir+"):
            continue
        entries.append(stripped)
    return entries


def validate_testbench(text: str, filelist: str) -> None:
    context = TESTBENCH_REL.as_posix()
    require_regex(text, r"\bmodule\s+tb_trecap_step11_bram_e2e\b", context)
    params, ports = one_instance(text, "trecap_bram_replay_system_top", "dut", context)
    require_bindings(
        params,
        {
            "X_MEMH_FILE": "X_MEMH_FILE",
            "REPLAY_MEM_DEPTH": "EXPECTED_NS",
            "REPLAY_INPUT_SAMPLES": "EXPECTED_NS",
        },
        f"{context} DUT parameters",
    )
    require_bindings(
        ports,
        {
            "y_valid_o": "y_valid_o",
            "y_ready_i": "y_ready_i",
            "y_data_o": "y_data_o",
            "y_sample_idx_o": "y_sample_idx_o",
            "replay_source_done_o": "replay_source_done_o",
            "replay_path_done_o": "replay_path_done_o",
            "replay_path_done_pulse_o": "replay_path_done_pulse_o",
            "replay_e2e_busy_o": "replay_e2e_busy_o",
            "replay_e2e_done_o": "replay_e2e_done_o",
            "replay_e2e_done_pulse_o": "replay_e2e_done_pulse_o",
            "replay_e2e_error_sticky_o": "replay_e2e_error_sticky_o",
            "core_error_sample_count_o": "core_error_sample_count_o",
            "avm_write_o": "avm_write_o",
            "avm_waitrequest_i": "avm_waitrequest_i",
            "normal_commit_pulse_o": "normal_commit_pulse_o",
            "full_path_alive_o": "full_path_alive_o",
        },
        f"{context} DUT ports",
    )
    clean = strip_sv_comments(text)
    compact_clean = compact(clean)
    for token in (
        "EXPECTED_NS=1024",
        "EXPECTED_NY=1536",
        "EXPECTED_TAU_LAST=1152",
        "EXPECTED_FRAMES=9",
        'artifacts/test_vectors/impulse_Ns1024_thr0/x_in.memh',
        'artifacts/reference_outputs/impulse_Ns1024_thr0/y_out.memh',
        "if(y_valid_o&&y_ready_i)",
        "y_sample_idx_o!==y_accept_count_q",
        "y_data_o!==expected_y[y_accept_count_q]",
        "wait(replay_path_done_pulse_o)",
        "check_exact_completion()",
        "core_error_sample_count_o!==64'(EXPECTED_NY)",
        "wait(normal_commit_seen_q)",
        "wait(replay_e2e_done_o)",
        "check_status_record()",
        "full_path_alive_o!==1'b1",
        "replay_e2e_done_o!==1'b1",
        "replay_e2e_busy_o!==1'b0",
        "replay_e2e_error_sticky_o!==1'b0",
        "STEP11_BRAM_E2E_PASS",
    ):
        require_token(compact_clean, compact(token), context)
    forbid_regex(
        compact_clean,
        r"wait\(replay_source_done_o\)",
        f"{context} source-done cannot terminate the test",
    )
    forbid_regex(
        compact_clean,
        r"status_tick_i=1'b1",
        f"{context} replay completion must use path-done STATUS auto-injection",
    )
    for token in (
        "avm_write_o&&!avm_waitrequest_i",
        "avm_write_o&&avm_waitrequest_i",
        "normal_commit_count_q!=32'd1",
        "dma_packet_count_o!=32'd1",
        "TPKT_TYPE_STATUS",
        "TCSR_SOURCE_MODE_BRAM_REPLAY",
        "TCSR_PACKET_ENABLE_STATUS_EN_MASK",
        "AVMM_RESPONSE_OKAY=2'b00",
        "AVMM_RESPONSE_SLVERR=2'b10",
        "ddr_response_pending_q",
        "response_delay_for_beat",
        "inject_final_response_error_q",
        "ddr_response_code_q<=AVMM_RESPONSE_SLVERR",
        "STEP11_BRAM_E2E_NEGATIVE_PASS",
        "negative DDR-error epoch reached commit/E2E done",
    ):
        require_token(compact_clean, compact(token), f"{context} DDR/STATUS regression")

    entries = active_filelist_entries(filelist)
    required = [
        REPLAY_SOURCE_REL.as_posix(),
        CORE_REL.as_posix(),
        E2E_SUPERVISOR_REL.as_posix(),
        TELEMETRY_REL.as_posix(),
        HPS_BRIDGE_REL.as_posix(),
        DDR_WRITER_REL.as_posix(),
        SOURCE_CORE_REL.as_posix(),
        FULL_TOP_REL.as_posix(),
        SYSTEM_TOP_REL.as_posix(),
        TESTBENCH_REL.as_posix(),
    ]
    for entry in required:
        if entries.count(entry) != 1:
            raise CheckFailure(f"{TEST_FILELIST_REL}: must list {entry} exactly once")
    ordered = [
        REPLAY_SOURCE_REL.as_posix(),
        CORE_REL.as_posix(),
        SOURCE_CORE_REL.as_posix(),
        FULL_TOP_REL.as_posix(),
        E2E_SUPERVISOR_REL.as_posix(),
        SYSTEM_TOP_REL.as_posix(),
        TESTBENCH_REL.as_posix(),
    ]
    positions = [entries.index(entry) for entry in ordered]
    if positions != sorted(positions):
        raise CheckFailure(f"{TEST_FILELIST_REL}: Step-11 owners are not in dependency order")
    if BOARD_TOP_REL.as_posix() in entries or "rtl/top/trecap_core_telemetry_top.sv" in entries:
        raise CheckFailure(f"{TEST_FILELIST_REL}: includes a board-only or duplicate-core top")


def validate_import_manifest(manifest: dict[str, Any]) -> None:
    context = IMPORT_MANIFEST_REL.as_posix()
    require_equal(manifest.get("schema"), "trecap_phase2_reference_import_manifest_v3", f"{context}.schema")
    require_equal(
        manifest.get("provenance_status"),
        "embedded_proxy_unverified_source_archive",
        f"{context}.provenance_status",
    )
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise CheckFailure(f"{context}.source must be an object")
    require_equal(source.get("kind"), "embedded_proxy", f"{context}.source.kind")
    require_equal(source.get("verified"), False, f"{context}.source.verified")
    if "archive_sha256" in source:
        raise CheckFailure(
            f"{context}: embedded proxy must not masquerade as the uploaded verified archive"
        )


def validate_document(text: str) -> None:
    normalized = re.sub(r"\s+", " ", text)
    for token in (
        "Step 11 status",
        "source-only",
        "trecap_bram_replay_system_top",
        "replay_start_admit_i",
        "replay_start_reject_pulse_o",
        "transport_epoch_idle_o",
        "external_telemetry_flush_i",
        "external_transport_clear_i",
        "TELEMETRY_SOFT_RESET",
        "KEY[3]",
        "KEY[2]",
        "core_error_sample_count_o",
        "baseline blind window",
        "delayed `OKAY` responses",
        "delayed `SLVERR`",
        "not proof of physical-DRAM completion",
        "replay_path_done_pulse_o` injects the replay-correlated post-core STATUS request",
        "p_replay_exact_completion",
        "Three completion levels",
        "replay_e2e_done_o",
        "zero_Ns4096_thr0",
        "impulse_Ns1024_thr0",
        UPLOADED_ARCHIVE_SHA256,
        "embedded_proxy_unverified_source_archive",
        "development smoke artifacts only",
        "does not invoke a simulator",
        "hardware_signoff",
    ):
        require_token(normalized, token, DOC_REL.as_posix())


def check_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise CheckFailure(f"cannot stat checker {path}: {exc}") from exc
    if not mode & stat.S_IXUSR:
        raise CheckFailure(f"checker is not executable: {path}")


def run_checks(repo_root: Path, force_fallback: bool) -> tuple[str, int]:
    required_paths = (
        CONTRACT_REL,
        SCHEMA_REL,
        DOC_REL,
        SYSTEM_TOP_REL,
        E2E_SUPERVISOR_REL,
        SOURCE_CORE_REL,
        REPLAY_SOURCE_REL,
        CORE_REL,
        FULL_TOP_REL,
        TELEMETRY_REL,
        PACKET_FIFO_REL,
        HPS_BRIDGE_REL,
        DDR_WRITER_REL,
        AVMM_MASTER_REL,
        PD_WRAPPER_REL,
        BOARD_TOP_REL,
        PROFILE_REL,
        TELEMETRY_PROFILE_REL,
        TESTBENCH_REL,
        TEST_FILELIST_REL,
        IMPORT_MANIFEST_REL,
        ZERO_CONFIG_REL,
        ZERO_INPUT_REL,
        IMPULSE_CONFIG_REL,
        IMPULSE_INPUT_REL,
        IMPULSE_Y_REL,
    )
    missing = [rel.as_posix() for rel in required_paths if not (repo_root / rel).is_file()]
    if missing:
        raise CheckFailure(f"required Step-11 source files are missing: {missing}")

    contract = load_json(repo_root / CONTRACT_REL)
    schema = load_json(repo_root / SCHEMA_REL)
    engine = validate_contract_schema(contract, schema, force_fallback)
    validate_contract_values(contract)

    validate_profile(load_json(repo_root / PROFILE_REL))
    zero_config = load_json(repo_root / ZERO_CONFIG_REL)
    impulse_config = load_json(repo_root / IMPULSE_CONFIG_REL)
    if not isinstance(zero_config, dict) or not isinstance(impulse_config, dict):
        raise CheckFailure("Step-11 vector config roots must be objects")
    validate_vector_config(
        zero_config,
        "zero_Ns4096_thr0",
        4096,
        4608,
        33,
        ZERO_INPUT_SHA256,
        "ac450f2a1f94c04e0b50a3641dc7bfffced0f4aa58bed510148e87c11846d7cf",
        ZERO_CONFIG_REL.as_posix(),
    )
    validate_vector_config(
        impulse_config,
        "impulse_Ns1024_thr0",
        1024,
        1536,
        9,
        IMPULSE_INPUT_SHA256,
        IMPULSE_Y_SHA256,
        IMPULSE_CONFIG_REL.as_posix(),
    )
    validate_memh(repo_root / ZERO_INPUT_REL, 4096, ZERO_INPUT_SHA256, ZERO_INPUT_REL.as_posix())
    validate_memh(repo_root / IMPULSE_INPUT_REL, 1024, IMPULSE_INPUT_SHA256, IMPULSE_INPUT_REL.as_posix())
    validate_memh(repo_root / IMPULSE_Y_REL, 1536, IMPULSE_Y_SHA256, IMPULSE_Y_REL.as_posix())
    import_manifest = load_json(repo_root / IMPORT_MANIFEST_REL)
    if not isinstance(import_manifest, dict):
        raise CheckFailure("reference import manifest root must be an object")
    validate_import_manifest(import_manifest)

    system_top = read_text(repo_root / SYSTEM_TOP_REL)
    e2e_supervisor = read_text(repo_root / E2E_SUPERVISOR_REL)
    source_core = read_text(repo_root / SOURCE_CORE_REL)
    full_top = read_text(repo_root / FULL_TOP_REL)
    telemetry = read_text(repo_root / TELEMETRY_REL)
    hps_bridge = read_text(repo_root / HPS_BRIDGE_REL)
    ddr_writer = read_text(repo_root / DDR_WRITER_REL)
    avmm_master = read_text(repo_root / AVMM_MASTER_REL)
    pd_wrapper = read_text(repo_root / PD_WRAPPER_REL)
    validate_system_top(system_top)
    validate_e2e_supervisor(e2e_supervisor)
    validate_completion_monitor(source_core)
    validate_board_top(read_text(repo_root / BOARD_TOP_REL))
    validate_transport_hierarchy(full_top, telemetry, hps_bridge, ddr_writer, pd_wrapper)
    validate_avmm_response_closure(avmm_master, ddr_writer, pd_wrapper)
    validate_testbench(
        read_text(repo_root / TESTBENCH_REL), read_text(repo_root / TEST_FILELIST_REL)
    )
    validate_document(read_text(repo_root / DOC_REL))
    check_executable(Path(__file__).resolve())
    return engine, len(required_paths)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        "--root",
        dest="repo_root",
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
        print(f"check_bram_replay_path: ERROR: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(
            "check_bram_replay_path: PASS "
            f"({checked_count} committed source/contract files; schema={engine}; source-only)"
        )
        print(
            "check_bram_replay_path: no RTL compile/simulation, Platform Designer generation, "
            "Quartus/TimeQuest, timing-closure, DDR/HPS capture, or hardware evidence was produced"
        )
        print(
            "check_bram_replay_path: reference artifacts remain development-smoke-only "
            f"(uploaded SHA-256 {UPLOADED_ARCHIVE_SHA256}; provenance unverified/mismatched)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
