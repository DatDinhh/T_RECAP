#!/usr/bin/env python3
"""Validate the checked-in Step-14 PC-to-FPGA command-path source contract.

This is a source-only gate. It does not open a UDP socket, mmap HPS/FPGA
resources, run RTL simulation, invoke Platform Designer/Quartus, or claim live
PC, Linux, FPGA, board, or hardware evidence.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from check_ddr_ring_ownership import CheckFailure, validate_contract_schema


CONTRACT_REL = Path("config/boards/de1soc_command_path.json")
SCHEMA_REL = Path("spec/schemas/de1soc_command_path.schema.json")
PACKET_REL = Path("spec/generated/packet_layouts.json")
CSR_REL = Path("spec/generated/csr_map.json")
DOC_REL = Path("docs/architecture/de1soc_command_path.md")
COMMAND_CONTRACT_CANONICAL_SHA256 = (
    "fde3216fed4ebd29ed42b193f213881facd634db476e404ab2bed710e1d3872a"
)

V1_COMMANDS = {
    "SET_THR2": 0x0001,
    "CLEAR_METRICS": 0x0002,
    "SET_SOURCE_MODE": 0x0003,
    "SET_PACKET_ENABLE": 0x0004,
    "SET_WAVE_DECIM": 0x0005,
    "SET_SPEC_SHIFT": 0x0006,
    "PING": 0x0007,
}
V2_EXTENSION_COMMANDS = {
    "SET_SPEC_MODE": 0x0008,
    "SET_TELEMETRY_ENABLE": 0x0009,
    "CONFIGURE_DDR_RING": 0x000A,
    "RESET_TRANSPORT": 0x000B,
    "CLEAR_COUNTERS": 0x000C,
    "START_BRAM_REPLAY": 0x000D,
    "READ_STATUS_VERSION": 0x000E,
}
REQUEST_FIELDS = {
    "magic": 0,
    "version": 4,
    "cmd_type": 6,
    "seq": 8,
    "arg0": 12,
    "arg1": 16,
    "arg2": 20,
    "crc32": 24,
}
V1_ARGS = {
    "SET_THR2": {"arg0": "THR2[31:0]", "arg1": "THR2[55:32] in low 24 bits; upper bits zero", "arg2": "0"},
    "CLEAR_METRICS": {"arg0": "0", "arg1": "0", "arg2": "0"},
    "SET_SOURCE_MODE": {"arg0": "0..3", "arg1": "0", "arg2": "0"},
    "SET_PACKET_ENABLE": {"arg0": "PACKET_ENABLE bit mask with reserved and reserved-disabled bits zero", "arg1": "0", "arg2": "0"},
    "SET_WAVE_DECIM": {"arg0": "1..65535", "arg1": "0", "arg2": "0"},
    "SET_SPEC_SHIFT": {"arg0": "0..55", "arg1": "0", "arg2": "0"},
    "PING": {"arg0": "ignored", "arg1": "ignored", "arg2": "ignored"},
}
V2_CONTRACT_ARGS = {
    "SET_SPEC_MODE": {"arg0": "0..2", "arg1": "0", "arg2": "0"},
    "SET_TELEMETRY_ENABLE": {"arg0": "0_or_1", "arg1": "0", "arg2": "0"},
    "CONFIGURE_DDR_RING": {"arg0": "0", "arg1": "0", "arg2": "0"},
    "RESET_TRANSPORT": {"arg0": "0", "arg1": "0", "arg2": "0"},
    "CLEAR_COUNTERS": {"arg0": "0", "arg1": "0", "arg2": "0"},
    "START_BRAM_REPLAY": {"arg0": "0", "arg1": "0", "arg2": "0"},
    "READ_STATUS_VERSION": {"arg0": "0", "arg1": "0", "arg2": "0"},
}
V2_GENERATED_ARGS = {
    **V2_CONTRACT_ARGS,
    "SET_TELEMETRY_ENABLE": {"arg0": "0 or 1", "arg1": "0", "arg2": "0"},
}
RESULT_FIELDS = {
    "magic": 0,
    "version": 4,
    "cmd_type": 6,
    "seq": 8,
    "disposition": 12,
    "reject_reason": 16,
    "fpga_status": 20,
    "csr_version": 24,
    "crc32": 28,
}
DISPOSITIONS = {"APPLIED": 0, "NOOP": 1, "REJECTED": 2, "FAILED": 3}
REJECT_REASONS = {
    "NONE": 0,
    "BAD_SOURCE": 1,
    "BAD_LENGTH": 2,
    "BAD_MAGIC": 3,
    "BAD_VERSION": 4,
    "BAD_CRC": 5,
    "UNSUPPORTED_TYPE": 6,
    "RANGE": 7,
    "RESERVED_ARGUMENT": 8,
    "CSR": 9,
    "IO": 10,
    "UNSAFE_STATE": 11,
    "SEQUENCE_STALE": 12,
    "SEQUENCE_CONFLICT": 13,
    "TIMEOUT": 14,
    "RESET_REQUIRED": 15,
    "VERSION_MISMATCH": 16,
}
CSR_REGISTERS = {
    "COUNTER_CLEAR": (0x08C, "W1P"),
    "REPLAY_CONTROL": (0x090, "W1P"),
    "REPLAY_STATUS": (0x094, "R"),
}
CSR_REGISTER_FIELDS = {
    "COUNTER_CLEAR": {"transport_counters": (0, 0)},
    "REPLAY_CONTROL": {"start": (0, 0), "rearm": (1, 1)},
    "REPLAY_STATUS": {
        "pending": (0, 0),
        "last_accept": (1, 1),
        "last_reject": (2, 2),
        "start_ready": (3, 3),
        "replay_active": (4, 4),
        "replay_path_busy": (5, 5),
        "replay_path_done": (6, 6),
        "e2e_busy": (7, 7),
        "e2e_done": (8, 8),
        "error": (9, 9),
        "rearm_required": (10, 10),
        "result_epoch": (16, 31),
    },
}
PROFILE_RELS = (
    Path("config/profiles/baseline_core.json"),
    Path("config/profiles/sim_core_only.json"),
    Path("config/profiles/de1soc_bram_replay.json"),
    Path("config/profiles/de1soc_linein_demo.json"),
    Path("config/profiles/telemetry_status_only.json"),
    Path("config/profiles/telemetry_full_demo.json"),
)

SOURCE_FILES = (
    Path("sw/hps/include/command_bridge.h"),
    Path("sw/hps/src/command_bridge.c"),
    Path("sw/hps/include/command_server.h"),
    Path("sw/hps/src/command_server.c"),
    Path("sw/hps/include/csr_map.h"),
    Path("sw/hps/src/csr_map.c"),
    Path("sw/hps/src/trecap_udp_streamer.c"),
    Path("sw/hps/tests/test_step14_command_path.c"),
    Path("sw/pc_dashboard/trecap_dashboard/command_client.py"),
    Path("sw/pc_dashboard/scripts/run_dashboard.py"),
    Path("sw/pc_dashboard/tests/test_step14_command_client.py"),
    Path("rtl/hps_bridge/trecap_csr_bank.sv"),
    Path("rtl/hps_bridge/trecap_hps_bridge_top.sv"),
    Path("sim/check_step14_command_rtl.py"),
    Path("sim/filelists/step14_command_csr.f"),
    Path("sim/tb/tb_trecap_step14_command_csr.sv"),
    Path("Makefile"),
    Path("sw/hps/Makefile"),
)

GENERATED_FILES = (
    Path("rtl/include/generated/trecap_csr_pkg.sv"),
    Path("rtl/include/generated/trecap_packet_pkg.sv"),
    Path("sw/hps/include/generated/trecap_csr.h"),
    Path("sw/hps/include/generated/trecap_packet.h"),
    Path("sw/pc_dashboard/generated/trecap_packet.py"),
)

STEP14_PACKAGE_DIFF_CLOSURE = (
    Path("artifacts/manifests/reference_import_manifest.json"),
    Path("ci/github/check_generated.yml"),
    Path("config/profiles/README.md"),
    Path("docs/architecture/coding_style.md"),
    Path("docs/architecture/repo_architecture.md"),
    Path("platform/de1soc/address_map/address_map.md"),
    Path("platform/de1soc/address_map/hps_bridge_regions.json"),
    Path("platform/de1soc/qsys/hps_config.tcl"),
    Path("platform/de1soc/qsys/system.qsys"),
    Path("scripts/check_bram_replay_path.py"),
    Path("scripts/check_core_telemetry_composition.py"),
    Path("scripts/check_de1soc_clock_reset.py"),
    Path("scripts/check_hps_platform.py"),
    Path("scripts/check_hps_transport.py"),
    Path("scripts/check_source_core_integration.py"),
    Path("spec/schemas/runtime_profile.schema.json"),
    Path("rtl/top/trecap_bram_replay_e2e_supervisor.sv"),
    Path("sw/hps/scripts/run_udp_streamer.sh"),
    Path("sw/reference_model/import_manifest.json"),
    Path("tests/test_command_path_contract_freeze.py"),
    Path("tests/test_gen_headers_csr_freeze.py"),
)


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckFailure(f"cannot read {path}: {exc}") from exc


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CheckFailure(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(read_text(path), object_pairs_hook=reject_duplicate_pairs)
    except CheckFailure as exc:
        raise CheckFailure(f"cannot decode JSON {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CheckFailure(f"cannot decode JSON {path}: {exc}") from exc


def parse_int(value: Any) -> int:
    if isinstance(value, bool):
        raise CheckFailure(f"boolean is not an integer contract value: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value.replace("_", ""), 0)
    raise CheckFailure(f"cannot parse integer contract value {value!r}")


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if type(actual) is not type(expected) or actual != expected:
        raise CheckFailure(f"{context}: expected {expected!r}, got {actual!r}")


def require_token(text: str, token: str, context: str) -> None:
    if token not in text:
        raise CheckFailure(f"{context}: missing required token {token!r}")


def require_tokens(text: str, tokens: Iterable[str], context: str) -> None:
    for token in tokens:
        require_token(text, token, context)


def forbid_token(text: str, token: str, context: str) -> None:
    if token in text:
        raise CheckFailure(f"{context}: forbidden stale token {token!r}")


def walk_dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def named_codes(value: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in walk_dicts(value):
        name = item.get("name")
        code = item.get("code")
        if isinstance(name, str) and code is not None:
            try:
                parsed = parse_int(code)
            except (CheckFailure, ValueError):
                continue
            previous = result.setdefault(name, parsed)
            if previous != parsed:
                raise CheckFailure(
                    f"conflicting generated numeric definitions for {name}: {previous}, {parsed}"
                )
    return result


def require_name_code_set(value: Any, expected: dict[str, int], context: str) -> None:
    found = named_codes(value)
    for name, code in expected.items():
        if found.get(name) != code:
            raise CheckFailure(
                f"{context}.{name}: expected code 0x{code:04x}, got {found.get(name)!r}"
            )


def require_ordered_name_codes(value: Any, expected: dict[str, int], context: str) -> None:
    if not isinstance(value, list):
        raise CheckFailure(f"{context}: expected an array")
    actual = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise CheckFailure(f"{context}: malformed name/code entry {item!r}")
        actual.append((item["name"], parse_int(item.get("code"))))
    require_equal(actual, list(expected.items()), context)


def find_layout(value: Any, fields: dict[str, int], size_bytes: int) -> dict[str, Any]:
    for item in walk_dicts(value):
        if item.get("size_bytes") != size_bytes or not isinstance(item.get("fields"), list):
            continue
        offsets: dict[str, int] = {}
        for field in item["fields"]:
            if isinstance(field, dict) and isinstance(field.get("name"), str):
                try:
                    offsets[field["name"]] = parse_int(field.get("offset"))
                except (CheckFailure, ValueError):
                    pass
        if all(offsets.get(name) == offset for name, offset in fields.items()):
            return item
    raise CheckFailure(f"cannot find exact {size_bytes}-byte generated layout {fields!r}")


def validate_machine_contract(root: Path, force_fallback: bool) -> tuple[dict[str, Any], str]:
    contract = load_json(root / CONTRACT_REL)
    schema = load_json(root / SCHEMA_REL)
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        raise CheckFailure("Step-14 contract and schema roots must be objects")
    canonical_contract = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    require_equal(
        hashlib.sha256(canonical_contract).hexdigest(),
        COMMAND_CONTRACT_CANONICAL_SHA256,
        "contract canonical SHA-256",
    )
    require_equal(schema.get("const"), contract, "schema root const")
    validator = validate_contract_schema(contract, schema, force_fallback)

    expected_top = {
        "schema": "trecap_phase2_de1soc_command_path_v1",
        "project": "T_RECAP_Phase2",
        "board": "de1soc",
        "contract_stage": "architecture_implementation_step_14_source",
        "status": "source_contract_frozen_host_test_sources_required_live_evidence_absent",
    }
    for key, expected in expected_top.items():
        require_equal(contract.get(key), expected, f"contract.{key}")

    authority = contract["authority"]
    require_equal(authority["pdf_v1_policy"], "exact_and_unchanged", "authority.pdf_v1_policy")
    require_equal(authority["csr_version_major"], 1, "authority.csr_version_major")
    require_equal(authority["csr_version_minor"], 8, "authority.csr_version_minor")

    wire = contract["wire_contract"]
    for key, expected in {
        "request_bytes": 28,
        "request_magic": "0x54524343",
        "result_bytes": 32,
        "result_magic": "0x54524352",
        "crc_enabled": False,
    }.items():
        require_equal(wire[key], expected, f"wire_contract.{key}")
    require_ordered_name_codes(
        wire["version_1"]["exact_command_types"],
        V1_COMMANDS,
        "contract.version_1.exact_command_types",
    )
    require_ordered_name_codes(
        wire["version_2"]["extension_command_types"],
        V2_EXTENSION_COMMANDS,
        "contract.version_2.extension_command_types",
    )
    contract_v2_args = {
        item["name"]: item.get("args")
        for item in wire["version_2"]["extension_command_types"]
    }
    require_equal(contract_v2_args, V2_CONTRACT_ARGS, "contract.version_2.arguments")
    find_layout(wire, RESULT_FIELDS, 32)
    require_ordered_name_codes(
        wire["result_layout"]["dispositions"], DISPOSITIONS, "dispositions"
    )
    require_ordered_name_codes(
        wire["result_layout"]["reject_reasons"], REJECT_REASONS, "reject_reasons"
    )
    ping = wire["version_2"]["ping_policy"]
    for key, expected in {
        "arguments": "ignored",
        "response": "fresh_diagnostic_status_only",
        "diagnostic_status_seq": 0,
        "command_result_emitted": False,
        "csr_access": False,
        "mutation_ledger_effect": "none",
    }.items():
        require_equal(ping[key], expected, f"version_2.ping_policy.{key}")

    peer = contract["trusted_peer"]
    for key, expected in {
        "hps_listen_ip_source": "runtime_hps_static_ip",
        "hps_listen_ip": "192.168.10.2",
        "hps_listen_port": 5006,
        "trusted_pc_ip": "192.168.10.1",
        "trusted_pc_source_port": 5007,
    }.items():
        require_equal(peer[key], expected, f"trusted_peer.{key}")
    require_equal(
        peer["match_fields"],
        ["ipv4_address", "udp_source_port"],
        "trusted_peer.match_fields",
    )
    require_equal(
        peer["lab_learning_mode"]["listen_override_ip"],
        "0.0.0.0",
        "trusted_peer.lab_learning_mode.listen_override_ip",
    )

    sequence = contract["sequence_and_replay"]
    require_equal(sequence["comparison"], "RFC1982_serial_number_arithmetic_32_bit", "sequence.comparison")
    require_equal(sequence["ping_exempt"], True, "sequence.ping_exempt")
    require_equal(
        sequence["at_most_once_scope"],
        "all_version_2_non_ping_commands",
        "sequence.at_most_once_scope",
    )

    service = contract["command_service"]
    require_equal(
        service["simple_csr_commands_owner"],
        "command_bridge_for_live_network_path",
        "command_service.simple_csr_commands_owner",
    )
    require_equal(
        service["compatibility_direct_helper_policy"],
        "command_apply_to_csr_not_used_by_live_streamer",
        "command_service.compatibility_direct_helper_policy",
    )
    require_equal(
        service["identity_required_before_noop_or_applied"],
        "every_command_except_PING_and_READ_STATUS_VERSION",
        "command_service.identity_required_before_noop_or_applied",
    )
    require_equal(
        service["read_status_version_identity_exception"],
        "return_raw_STATUS_and_VERSION_as_NOOP_even_when_incompatible; only_read_failure_is_FAILED",
        "command_service.read_status_version_identity_exception",
    )

    lifecycle = contract["lifecycle"]
    require_equal(
        lifecycle["required_order"],
        ["RESET_TRANSPORT", "CONFIGURE_DDR_RING", "SET_TELEMETRY_ENABLE_1"],
        "lifecycle.required_order",
    )
    require_equal(
        lifecycle["network_supplied_ring_address_allowed"],
        False,
        "lifecycle.network_supplied_ring_address_allowed",
    )
    for key, expected in {
        "failure_disable_attempt": "write_CONTROL_zero_then_read_STATUS",
        "verified_fail_closed_condition": "STATUS_telemetry_enable_and_ring_writer_enable_both_zero",
        "hardware_disable_may_be_claimed_without_readback": False,
        "unverified_hardware_disable_policy": "lock_software_RESET_REQUIRED_and_require_operator_or_transport_reset",
        "local_state_commit_policy": "commit_configuration_and_restored_enable_state_only_after_configuration_apply_readback_and_safe_control_restore_readback_both_succeed",
    }.items():
        require_equal(lifecycle[key], expected, f"lifecycle.{key}")
    reset_replay = lifecycle["reset_replay_policy"]
    for key, expected in {
        "placement": "after_ring_reset_before_configuration_reconciliation",
        "reject_if_replay_status_reserved_nonzero": True,
        "reject_if_any_replay_state_set": [
            "pending",
            "replay_active",
            "replay_path_busy",
            "e2e_busy",
        ],
        "required_transport_quiescence": [
            "telemetry_control_off",
            "ring_writer_control_off",
            "writer_busy_clear",
            "thr2_commit_pending_clear",
            "source_commit_pending_clear",
            "source_transition_busy_clear",
            "transport_epoch_idle_set",
        ],
        "healthy_reset_replay_control_write_count": 0,
        "failed_epoch_rearm_condition": "rearm_required_and_replay_and_transport_quiescent",
        "failed_epoch_rearm_pulse_count": 1,
        "rearm_must_preserve_result_epoch": True,
        "rearm_readback_must_clear": [
            "pending",
            "replay_active",
            "replay_path_busy",
            "e2e_busy",
            "last_accept",
            "last_reject",
            "error",
            "rearm_required",
        ],
        "active_replay_is_implicitly_aborted": False,
        "failure_policy": "FAILED_and_software_RESET_REQUIRED_fail_closed",
    }.items():
        require_equal(reset_replay[key], expected, f"lifecycle.reset_replay_policy.{key}")

    mutation = contract["control_mutation_safety"]
    require_equal(
        mutation["applies_to_commands"],
        [
            "SET_SOURCE_MODE",
            "SET_PACKET_ENABLE",
            "SET_WAVE_DECIM",
            "SET_SPEC_MODE",
            "SET_SPEC_SHIFT",
        ],
        "control_mutation_safety.applies_to_commands",
    )
    require_equal(
        mutation["applies_to_version_1_and_version_2"],
        True,
        "control_mutation_safety.applies_to_version_1_and_version_2",
    )
    require_equal(
        mutation["direct_live_csr_writes_allowed"],
        False,
        "control_mutation_safety.direct_live_csr_writes_allowed",
    )
    for required in (
        "telemetry_and_ring_writer_controls_disabled",
        "STATUS.transport_epoch_idle_is_one",
        "no_replay_busy_active_or_pending",
    ):
        if required not in mutation["required_preconditions"]:
            raise CheckFailure(
                f"control_mutation_safety.required_preconditions is missing {required}"
            )

    clear = contract["clear_counters"]
    for required in (
        "OVERFLOW_FLAGS",
        "producer_pointer_W",
        "consumer_pointer_Rd",
        "telemetry_sequence",
        "trusted_peer_binding",
        "mutation_sequence_ledger",
        "result_cache",
    ):
        if required not in clear["preserved"]:
            raise CheckFailure(f"clear_counters.preserved is missing {required}")

    csr = contract["csr_extension"]
    require_equal(csr["version_major"], 1, "csr_extension.version_major")
    require_equal(csr["version_minor"], 8, "csr_extension.version_minor")
    csr_regs = {item["name"]: (parse_int(item["offset"]), item["access"]) for item in csr["registers"]}
    require_equal(csr_regs, CSR_REGISTERS, "csr_extension.registers")
    csr_fields = {
        item["name"]: {
            field["name"]: (field["lsb"], field["msb"])
            for field in item["fields"]
        }
        for item in csr["registers"]
    }
    require_equal(csr_fields, CSR_REGISTER_FIELDS, "csr_extension.register_fields")
    status_fields = {
        item["name"]: (item["lsb"], item["msb"])
        for item in csr["status_extension_fields"]
    }
    require_equal(
        status_fields,
        {
            "actual_source_mode": (10, 11),
            "transport_epoch_idle": (12, 12),
            "source_transition_busy": (13, 13),
        },
        "csr_extension.status_extension_fields",
    )

    evidence = contract["evidence_boundary"]
    for key, value in evidence.items():
        expected = key in {
            "source_implementation_claimed",
            "rtl_structural_checker_source_claimed",
            "rtl_testbench_source_claimed",
            "host_test_source_claimed",
        }
        require_equal(value, expected, f"evidence_boundary.{key}")
    return contract, validator


def validate_generated_contracts(root: Path) -> None:
    packets = load_json(root / PACKET_REL)
    csr = load_json(root / CSR_REL)
    if not isinstance(packets, dict) or not isinstance(csr, dict):
        raise CheckFailure("generated packet/CSR contract roots must be objects")

    command = packets.get("command_packet")
    if not isinstance(command, dict):
        raise CheckFailure("packet_layouts.command_packet must be an object")
    find_layout(packets, REQUEST_FIELDS, 28)
    command_types = command.get("command_types")
    if not isinstance(command_types, list):
        raise CheckFailure("packet_layouts.command_packet.command_types must be an array")
    require_ordered_name_codes(
        command_types,
        {**V1_COMMANDS, **V2_EXTENSION_COMMANDS},
        "packet_layouts.command_types",
    )
    introduced = {item["name"]: item.get("introduced_in_version") for item in command_types}
    require_equal(
        introduced,
        {**{name: 1 for name in V1_COMMANDS}, **{name: 2 for name in V2_EXTENSION_COMMANDS}},
        "packet_layouts.command introduced versions",
    )
    generated_args = {item["name"]: item.get("args") for item in command_types}
    require_equal(
        generated_args,
        {**V1_ARGS, **V2_GENERATED_ARGS},
        "packet_layouts.command arguments",
    )
    find_layout(packets, RESULT_FIELDS, 32)
    result = packets.get("command_result")
    if not isinstance(result, dict):
        raise CheckFailure("packet_layouts.command_result must be an object")
    require_ordered_name_codes(
        result.get("dispositions"), DISPOSITIONS, "packet_layouts.dispositions"
    )
    require_ordered_name_codes(
        result.get("reject_reasons"), REJECT_REASONS, "packet_layouts.reject_reasons"
    )

    transport = packets.get("transport")
    if not isinstance(transport, dict):
        raise CheckFailure("packet_layouts.transport must be an object")
    require_equal(transport.get("command_packet_bytes"), 28, "packet_layouts.command_packet_bytes")
    require_equal(transport.get("command_version"), 2, "packet_layouts.command_version")
    require_equal(
        transport.get("command_versions_supported"),
        [1, 2],
        "packet_layouts.command_versions_supported",
    )
    require_equal(transport.get("transport_version_major"), 1, "packet_layouts.version_major")
    require_equal(transport.get("transport_version_minor"), 8, "packet_layouts.version_minor")
    require_equal(transport.get("telemetry_header_version"), 1, "packet telemetry header version")

    constants = csr.get("constants", {})
    version = constants.get("VERSION", {}) if isinstance(constants, dict) else {}
    require_equal(parse_int(version.get("major")), 1, "csr VERSION.major")
    require_equal(parse_int(version.get("minor")), 8, "csr VERSION.minor")
    require_equal(parse_int(version.get("packed_hex")), 0x00010008, "csr VERSION.packed")
    registers = csr.get("registers")
    if not isinstance(registers, list):
        raise CheckFailure("csr_map.registers must be an array")
    generated_regs = {
        item.get("name"): (parse_int(item.get("offset")), item.get("access"))
        for item in registers
        if isinstance(item, dict) and item.get("name") in CSR_REGISTERS
    }
    require_equal(generated_regs, CSR_REGISTERS, "csr_map Step-14 registers")

    for relative in PROFILE_RELS:
        profile = load_json(root / relative)
        if not isinstance(profile, dict):
            raise CheckFailure(f"{relative}: profile root must be an object")
        require_equal(profile.get("transport_version_major"), 1, f"{relative}.major")
        require_equal(profile.get("transport_version_minor"), 8, f"{relative}.minor")


def validate_generated_language_mirrors(root: Path) -> None:
    missing = [relative for relative in GENERATED_FILES if not (root / relative).is_file()]
    if missing:
        raise CheckFailure(f"missing generated command/CSR mirrors: {[p.as_posix() for p in missing]}")
    packet_texts = {
        relative: read_text(root / relative)
        for relative in GENERATED_FILES
        if "packet" in relative.name
    }
    for relative, text in packet_texts.items():
        result_magic_token = (
            "COMMAND_RESULT_MAGIC" if relative.suffix == ".py" else "54524352"
        )
        require_tokens(
            text,
            (
                "TCMD_VERSION_V1" if relative.suffix != ".py" else "COMMAND_VERSION_V1",
                "TCMD_VERSION_V2" if relative.suffix != ".py" else "COMMAND_VERSION_V2",
                result_magic_token,
                "RESULT",
                "DISPOSITION",
                "SEQUENCE_STALE",
                "SEQUENCE_CONFLICT",
                "RESET_REQUIRED",
                "VERSION_MISMATCH",
            ),
            relative.as_posix(),
        )
        for name in V2_EXTENSION_COMMANDS:
            require_token(text, name, relative.as_posix())

    csr_texts = {
        relative: read_text(root / relative)
        for relative in GENERATED_FILES
        if "csr" in relative.name
    }
    for relative, text in csr_texts.items():
        require_tokens(
            text,
            (
                "00010008",
                "COUNTER_CLEAR",
                "REPLAY_CONTROL",
                "REPLAY_STATUS",
                "ACTUAL_SOURCE_MODE",
                "TRANSPORT_EPOCH_IDLE",
                "SOURCE_TRANSITION_BUSY",
            ),
            relative.as_posix(),
        )


def validate_runtime_configs(root: Path, allow_incomplete: bool) -> list[str]:
    warnings: list[str] = []
    hps_rel = Path("sw/hps/config/trecap_hps_config.json")
    pc_rel = Path("sw/pc_dashboard/configs/dashboard_direct_link.json")
    for relative in (hps_rel, pc_rel):
        if not (root / relative).is_file():
            if allow_incomplete:
                warnings.append(f"source not yet present: {relative}")
                continue
            raise CheckFailure(f"required runtime config missing: {relative}")

    if (root / hps_rel).is_file():
        hps = load_json(root / hps_rel)
        require_equal(hps.get("transport_version_major"), 1, "HPS runtime version major")
        require_equal(hps.get("transport_version_minor"), 8, "HPS runtime version minor")
        require_equal(hps.get("hps_static_ip"), "192.168.10.2", "HPS command bind IP")
        require_equal(hps.get("command_listen_port"), 5006, "HPS command listen port")
        require_equal(hps.get("trusted_command_peer"), "192.168.10.1", "HPS trusted peer IP")
        require_equal(hps.get("trusted_command_peer_port"), 5007, "HPS trusted peer source port")
        require_equal(hps.get("require_trusted_peer"), True, "HPS exact peer required")

    if (root / pc_rel).is_file():
        pc = load_json(root / pc_rel)
        command = pc.get("command")
        if not isinstance(command, dict):
            raise CheckFailure("PC config command section must be an object")
        require_equal(command.get("host"), "192.168.10.2", "PC command destination")
        require_equal(command.get("port"), 5006, "PC command destination port")
        require_equal(command.get("bind_host"), "192.168.10.1", "PC command source IP")
        require_equal(command.get("bind_port"), 5007, "PC command source port")
    return warnings


def validate_source_closure(root: Path, allow_incomplete: bool) -> list[str]:
    warnings: list[str] = []

    def check_or_warn(check: Any) -> None:
        try:
            check()
        except CheckFailure as exc:
            if not allow_incomplete:
                raise
            warnings.append(f"source not yet complete: {exc}")

    missing = [relative for relative in SOURCE_FILES if not (root / relative).is_file()]
    if missing and not allow_incomplete:
        raise CheckFailure(f"Step-14 source closure is missing: {[p.as_posix() for p in missing]}")
    warnings.extend(f"source not yet present: {relative}" for relative in missing)

    available = {relative: read_text(root / relative) for relative in SOURCE_FILES if (root / relative).is_file()}
    combined_hps = "\n".join(
        text for relative, text in available.items() if relative.parts[:2] == ("sw", "hps")
    )
    if combined_hps:
        check_or_warn(
            lambda: require_tokens(
                combined_hps,
                (
                    "TCMD_TYPE_SET_SPEC_MODE",
                    "TCMD_TYPE_SET_TELEMETRY_ENABLE",
                    "TCMD_TYPE_CONFIGURE_DDR_RING",
                    "TCMD_TYPE_RESET_TRANSPORT",
                    "TCMD_TYPE_CLEAR_COUNTERS",
                    "TCMD_TYPE_START_BRAM_REPLAY",
                    "TCMD_TYPE_READ_STATUS_VERSION",
                    "TRECAP_CMD_REJECT_SEQUENCE_STALE",
                    "TRECAP_CMD_REJECT_SEQUENCE_CONFLICT",
                    "TRECAP_CMD_REJECT_RESET_REQUIRED",
                    "TRECAP_CMD_REJECT_VERSION_MISMATCH",
                    "TRECAP_STREAMER_COMMAND_BUDGET_PER_PASS",
                    "trecap_bridge_is_quiesced_config_command",
                    "trecap_bridge_quiesce_config",
                    "trecap_bridge_restore_controls",
                    "trecap_bridge_require_identity",
                    "trecap_bridge_reset_rearm_replay",
                    "REARM is illegal when no failed epoch owns the latch",
                    "A retained CSR request already pending has no free result owner",
                    "REARM clears only a completed failed epoch",
                    "READ_STATUS_VERSION is deliberately an identity-diagnostic exception",
                    "hardware_disable_verified",
                    "hardware_disable_status",
                    "runtime_cfg->hps_static_ip",
                    "trusted_command_peer_port",
                    "trecap_command_bridge_apply_v1",
                    "trecap_command_bridge_handle_v2",
                    "TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK",
                    "TCSR_REPLAY_STATUS_PENDING_MASK",
                ),
                "HPS Step-14 source closure",
            )
        )

    pc_rel = Path("sw/pc_dashboard/trecap_dashboard/command_client.py")
    if pc_rel in available:
        text = available[pc_rel]
        check_or_warn(
            lambda: require_tokens(
                text,
                (
                    "CommandResult",
                    "SET_SPEC_MODE",
                    "SET_TELEMETRY_ENABLE",
                    "CONFIGURE_DDR_RING",
                    "RESET_TRANSPORT",
                    "CLEAR_COUNTERS",
                    "START_BRAM_REPLAY",
                    "READ_STATUS_VERSION",
                ),
                pc_rel.as_posix(),
            )
        )

    csr_bank_rel = Path("rtl/hps_bridge/trecap_csr_bank.sv")
    if csr_bank_rel in available:
        check_or_warn(
            lambda: require_tokens(
                available[csr_bank_rel],
                (
                    "TCSR_COUNTER_CLEAR_OFFSET",
                    "TCSR_REPLAY_CONTROL_OFFSET",
                    "TCSR_REPLAY_STATUS_OFFSET",
                    "result_epoch",
                ),
                csr_bank_rel.as_posix(),
            )
        )

    root_make = available.get(Path("Makefile"), "")
    if root_make:
        check_or_warn(
            lambda: require_tokens(
                root_make,
                ("check-command-path", "hps-step14-test", "dashboard-step14-test", "step14-source"),
                "Makefile",
            )
        )
    hps_make = available.get(Path("sw/hps/Makefile"), "")
    if hps_make:
        check_or_warn(
            lambda: require_tokens(
                hps_make,
                ("command_bridge.c", "test_step14_command_path.c", "test-step14-command-path"),
                "sw/hps/Makefile",
            )
        )
    return warnings


def validate_docs_and_infrastructure(root: Path) -> None:
    doc = read_text(root / DOC_REL)
    require_tokens(
        doc,
        (
            "version-2 extension",
            "0x54524352",
            "RESET_TRANSPORT",
            "CONFIGURE_DDR_RING",
            "SET_TELEMETRY_ENABLE 1",
            "RFC1982",
            "192.168.10.1:5007",
            "COUNTER_CLEAR",
            "REPLAY_CONTROL",
            "REPLAY_STATUS",
            "actual_source_mode",
            "transport_epoch_idle",
            "source_transition_busy",
            "Direct live CSR writes",
            "diagnostic exception",
            "does not claim",
        ),
        DOC_REL.as_posix(),
    )

    package = read_text(root / "scripts/package_architecture_snapshot.py")
    require_tokens(
        package,
        (
            "STEP14_FILES",
            "default=14",
            "contains_step_14_command_v2_source",
            "contains_step_14_host_test_execution_evidence",
            "contains_step_14_pc_hps_udp_runtime_evidence",
            "step_14_scope",
            "step_14_milestone_files",
        ),
        "scripts/package_architecture_snapshot.py",
    )
    try:
        package_tree = ast.parse(package)
    except SyntaxError as exc:
        raise CheckFailure(f"scripts/package_architecture_snapshot.py: invalid Python: {exc}") from exc
    milestone_lists: dict[str, list[str]] = {}
    for node in package_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (
                isinstance(target, ast.Name)
                and target.id.startswith("STEP")
                and target.id.endswith("_FILES")
            ):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError, SyntaxError) as exc:
                raise CheckFailure(
                    f"scripts/package_architecture_snapshot.py: {target.id} must be a literal list"
                ) from exc
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise CheckFailure(
                    f"scripts/package_architecture_snapshot.py: {target.id} must contain only paths"
                )
            duplicates = sorted({item for item in value if value.count(item) > 1})
            if duplicates:
                raise CheckFailure(
                    f"scripts/package_architecture_snapshot.py: {target.id} has duplicate paths {duplicates}"
                )
            milestone_lists[target.id] = value
    step14_files = set(milestone_lists.get("STEP14_FILES", []))
    required_step14 = {
        CONTRACT_REL.as_posix(),
        SCHEMA_REL.as_posix(),
        DOC_REL.as_posix(),
        PACKET_REL.as_posix(),
        CSR_REL.as_posix(),
        *(path.as_posix() for path in PROFILE_RELS),
        *(path.as_posix() for path in SOURCE_FILES),
        *(path.as_posix() for path in GENERATED_FILES),
        *(path.as_posix() for path in STEP14_PACKAGE_DIFF_CLOSURE),
    }
    missing_step14 = sorted(required_step14 - step14_files)
    if missing_step14:
        raise CheckFailure(
            "scripts/package_architecture_snapshot.py: STEP14_FILES misses closure paths "
            f"{missing_step14}"
        )
    lint_layout = read_text(root / "scripts/lint_repo_layout.py")
    require_tokens(
        lint_layout,
        (
            "docs/architecture/de1soc_command_path.md",
            "config/boards/de1soc_command_path.json",
            "spec/schemas/de1soc_command_path.schema.json",
            "scripts/check_command_path.py",
            "sw/hps/tests/test_step14_command_path.c",
            "sw/pc_dashboard/tests/test_step14_command_client.py",
            "sim/check_step14_command_rtl.py",
            "sim/filelists/step14_command_csr.f",
            "sim/tb/tb_trecap_step14_command_csr.sv",
            "tests/test_command_path_contract_freeze.py",
            "tests/test_gen_headers_csr_freeze.py",
        ),
        "scripts/lint_repo_layout.py",
    )
    lint_shell = read_text(root / "scripts/lint.sh")
    require_token(lint_shell, "scripts/check_command_path.py --quiet", "scripts/lint.sh")
    require_token(lint_shell, "python3 sim/check_step14_command_rtl.py", "scripts/lint.sh")

    generated_check = read_text(root / "scripts/check_generated.py")
    require_token(
        generated_check,
        'CSR_FREEZE_NEGATIVE_TEST = "tests/test_gen_headers_csr_freeze.py"',
        "scripts/check_generated.py",
    )
    require_token(
        generated_check,
        'COMMAND_CONTRACT_FREEZE_NEGATIVE_TEST = "tests/test_command_path_contract_freeze.py"',
        "scripts/check_generated.py",
    )
    generated_workflow = read_text(root / "ci/github/check_generated.yml")
    if generated_workflow.count('"tests/test_gen_headers_csr_freeze.py"') != 2:
        raise CheckFailure(
            "ci/github/check_generated.yml: CSR freeze test must trigger both pull_request and push"
        )
    if generated_workflow.count('"tests/test_command_path_contract_freeze.py"') != 2:
        raise CheckFailure(
            "ci/github/check_generated.yml: command-contract freeze test must trigger both pull_request and push"
        )

    for relative in (
        Path("docs/bringup/pc_dashboard_bringup.md"),
        Path("docs/bringup/hps_ethernet_bringup.md"),
    ):
        text = read_text(root / relative)
        forbid_token(text, "--send-ping", relative.as_posix())
    for path in (root / "docs").rglob("*.md"):
        text = read_text(path)
        if any(
            re.search(pattern, text, flags=re.IGNORECASE)
            for pattern in (
                r"0x00010007",
                r"transport_version_minor[\"']?\s*[:=]\s*7\b",
                r"VERSION\s+minor\s*=\s*7\b",
                r"CSR\s+VERSION\s+1\.7\b",
                r"minor\s+(?:version\s+)?1\.7\b",
                r"major\s+1\s*,\s*minor\s+7\b",
            )
        ):
            raise CheckFailure(f"{path.relative_to(root)}: stale active CSR VERSION 1.7 claim")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--force-fallback-schema", action="store_true")
    parser.add_argument(
        "--allow-incomplete-source",
        action="store_true",
        help="Temporarily warn instead of failing for source files being authored in parallel",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve() if args.root else repo_root_from_script()
    if not (root / "Makefile").is_file():
        print(f"ERROR: not a T-RECAP repository: {root}", file=sys.stderr)
        return 2
    try:
        _, validator = validate_machine_contract(root, args.force_fallback_schema)
        validate_generated_contracts(root)
        validate_generated_language_mirrors(root)
        warnings = validate_runtime_configs(root, args.allow_incomplete_source)
        warnings.extend(validate_source_closure(root, args.allow_incomplete_source))
        validate_docs_and_infrastructure(root)
    except (CheckFailure, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        for warning in warnings:
            print(f"WARNING: {warning}")
        print(
            "check_command_path: OK "
            f"validator={validator} source_complete={not warnings} "
            "live_evidence=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
