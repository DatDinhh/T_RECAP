#!/usr/bin/env python3
"""Validate the checked-in Step-13 HPS transport source contract.

The checker is intentionally source-only. It does not access /dev/mem, inspect
the active target device tree, send network traffic, start systemd, invoke FPGA
tools, or claim HPS/board execution evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from check_ddr_ring_ownership import (  # reuse the repository schema fallback
    CheckFailure,
    validate_contract_schema,
)


CONTRACT_REL = Path("config/boards/de1soc_hps_transport.json")
SCHEMA_REL = Path("spec/schemas/de1soc_hps_transport.schema.json")
DOC_REL = Path("docs/architecture/de1soc_hps_transport.md")
CONFIG_REL = Path("sw/hps/config/trecap_hps_config.json")
CONFIG_SOURCE_REL = Path("sw/hps/src/config.c")
CONFIG_HEADER_REL = Path("sw/hps/include/trecap_hps_config.h")
RING_REL = Path("sw/hps/src/ring_reader.c")
RING_HEADER_REL = Path("sw/hps/include/ring_reader.h")
CSR_REL = Path("sw/hps/src/csr_map.c")
UDP_REL = Path("sw/hps/src/udp_sender.c")
STREAMER_REL = Path("sw/hps/src/trecap_udp_streamer.c")
RUNNER_REL = Path("sw/hps/scripts/run_udp_streamer.sh")
SERVICE_REL = Path("sw/hps/systemd/trecap_udp_streamer.service")
TEST_REL = Path("sw/hps/tests/test_step13_hps_transport.c")


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


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if type(actual) is not type(expected) or actual != expected:
        raise CheckFailure(f"{context}: expected {expected!r}, got {actual!r}")


def require_token(text: str, token: str, context: str) -> None:
    if token not in text:
        raise CheckFailure(f"{context}: missing required token {token!r}")


def require_tokens(text: str, tokens: Iterable[str], context: str) -> None:
    for token in tokens:
        require_token(text, token, context)


def require_ordered(text: str, tokens: Iterable[str], context: str) -> None:
    cursor = 0
    for token in tokens:
        position = text.find(token, cursor)
        if position < 0:
            raise CheckFailure(f"{context}: missing ordered token {token!r}")
        cursor = position + len(token)


def forbid_regex(text: str, pattern: str, context: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL):
        raise CheckFailure(f"{context}: forbidden source pattern present: {pattern}")


def source_slice(text: str, start_token: str, end_token: str, context: str) -> str:
    start = text.find(start_token)
    if start < 0:
        raise CheckFailure(f"{context}: missing start token {start_token!r}")
    end = text.find(end_token, start + len(start_token))
    if end < 0:
        raise CheckFailure(f"{context}: missing end token {end_token!r}")
    return text[start:end]


def validate_contract(root: Path, force_fallback: bool) -> str:
    contract = load_json(root / CONTRACT_REL)
    schema = load_json(root / SCHEMA_REL)
    if not isinstance(contract, dict) or not isinstance(schema, dict):
        raise CheckFailure("Step-13 contract and schema roots must be objects")
    validator = validate_contract_schema(contract, schema, force_fallback)

    expected_top = {
        "schema": "trecap_phase2_de1soc_hps_transport_v1",
        "file_class": "[1] hand-written Step-13 HPS transport contract",
        "project": "T_RECAP_Phase2",
        "board": "de1soc",
        "contract_stage": "step13_hps_transport_source_implemented",
        "status": (
            "source_implemented_host_tests_available_pending_hps_linux_network_"
            "systemd_and_hardware_evidence"
        ),
    }
    for key, expected in expected_top.items():
        require_equal(contract.get(key), expected, f"contract.{key}")

    implementation = contract.get("implementation_state")
    if not isinstance(implementation, dict):
        raise CheckFailure("contract.implementation_state must be an object")
    true_source = (
        "csr_and_reserved_ddr_mapping_source_implemented",
        "ring_consumer_source_implemented",
        "runtime_record_validation_source_implemented",
        "wrap_consume_source_implemented",
        "five_telemetry_types_source_implemented",
        "udp_packetization_source_implemented",
        "consumer_commit_source_implemented",
        "malformed_exactly_once_latch_source_implemented",
        "dummy_udp_counter_source_implemented",
        "host_unit_test_source_implemented",
    )
    false_evidence = (
        "host_unit_test_execution_evidence_in_package",
        "hps_linux_runtime_evidence",
        "active_reserved_memory_runtime_evidence",
        "csr_mmap_runtime_evidence",
        "reserved_ddr_mmap_runtime_evidence",
        "udp_network_runtime_evidence",
        "systemd_runtime_evidence",
        "quartus_compile_evidence",
        "hardware_evidence",
        "hardware_signoff",
    )
    for key in true_source:
        require_equal(implementation.get(key), True, f"implementation_state.{key}")
    for key in false_evidence:
        require_equal(implementation.get(key), False, f"implementation_state.{key}")

    ownership = contract.get("source_ownership")
    if not isinstance(ownership, dict):
        raise CheckFailure("contract.source_ownership must be an object")
    for key, relative in ownership.items():
        if not isinstance(relative, str) or not (root / relative).is_file():
            raise CheckFailure(f"source_ownership.{key}: missing file {relative!r}")
    return validator


def validate_runtime_config(root: Path) -> None:
    cfg = load_json(root / CONFIG_REL)
    if not isinstance(cfg, dict):
        raise CheckFailure("HPS runtime config root must be an object")
    expected = {
        "schema": "trecap_phase2_hps_runtime_config_v1",
        "project": "T_RECAP_Phase2",
        "board": "de1soc",
        "csr_base_phys": "0x00000000ff200000",
        "csr_span_bytes": 4096,
        "ring_base_hps_phys": "0x000000003e000000",
        "ring_base_fpga": "0x000000003e000000",
        "ring_size_bytes": 33554432,
        "ring_guard_bytes": 64,
        "transport_version_major": 1,
        "transport_version_minor": 8,
        "require_trusted_peer": True,
        "use_nonblocking_udp": True,
        "allow_cached_ring_mapping": False,
        "stop_on_malformed_record": False,
    }
    for key, value in expected.items():
        require_equal(cfg.get(key), value, f"runtime_config.{key}")

    source = read_text(root / CONFIG_SOURCE_REL)
    header = read_text(root / CONFIG_HEADER_REL)
    require_tokens(
        source,
        (
            "trecap_config_validate_flat_json",
            "duplicate top-level config key",
            '"require_trusted_peer",\n                                      true',
            '"use_nonblocking_udp",\n                                      true',
            '"allow_cached_ring_mapping",\n                                      true',
            '"stop_on_malformed_record",\n                                      true',
            "trecap_hps_config_validate_live_ddr_reservation",
            "trecap_config_buffer_has_embedded_nul",
            "saw_unmasked_system_ram",
            "use_nonblocking_udp must be true to keep ring service bounded",
            'fopen("/proc/iomem", "r")',
            '"System RAM"',
            '"live reserved-memory node lacks no-map"',
            '"live reserved-memory node must not contain reusable"',
        ),
        CONFIG_SOURCE_REL.as_posix(),
    )
    forbid_regex(source, r"saw_nonzero_range|bool\s+saw_system_ram", CONFIG_SOURCE_REL.as_posix())
    require_tokens(
        header,
        (
            "TRECAP_HPS_DE1SOC_CSR_BASE",
            "TRECAP_HPS_DE1SOC_CSR_SPAN_BYTES",
            "TRECAP_HPS_DE1SOC_LIVE_DT_NODE",
        ),
        CONFIG_HEADER_REL.as_posix(),
    )


def validate_ring_reader(root: Path) -> None:
    ring = read_text(root / RING_REL)
    header = read_text(root / RING_HEADER_REL)
    require_tokens(
        header,
        (
            "TRECAP_RING_READER_RESET_REQUIRED",
            "TRECAP_RING_READER_RECONFIG_REQUIRED",
            "TRECAP_RING_READER_RD0_REQUIRED",
            "TRECAP_RING_READER_ACTIVE",
            "TRECAP_RING_READER_MALFORMED_LATCHED",
            "TRECAP_RING_ERR_DISABLED",
            "malformed_disable_commit_confirmed",
        ),
        RING_HEADER_REL.as_posix(),
    )
    require_tokens(
        ring,
        (
            "O_RDONLY | O_SYNC",
            "PROT_READ",
            "if (cacheable_mapping)",
            "trecap_ring_used_bytes(wr, rd) < (uint64_t)TPKT_HEADER_BYTES",
            "udp_datagram_bytes64",
            "ddr_record_bytes64",
            "record exceeds UDP datagram bound",
            "WRAP physical-tail padding is nonzero",
            "view->absolute_next_rd = rd + (uint64_t)tail",
            "reader->state = TRECAP_RING_READER_MALFORMED_LATCHED",
            "reader->counters.malformed_record_count += 1u",
            "trecap_csr_set_control_levels(reader->csr, false, false)",
            "trecap_csr_require_control_levels(reader->csr, false, false)",
            "trecap_csr_require_ring_configured(reader->csr)",
            "trecap_csr_commit_ring_rd(reader->csr, reader->rd)",
        ),
        RING_REL.as_posix(),
    )
    handler = source_slice(
        ring,
        "trecap_ring_status_t trecap_ring_reader_handle_malformed",
        "\n}",
        "malformed handler",
    )
    require_ordered(
        handler,
        (
            "TRECAP_RING_READER_MALFORMED_LATCHED",
            "malformed_record_count += 1u",
            "trecap_csr_set_control_levels",
            "trecap_csr_commit_ring_rd",
        ),
        "malformed exactly-once latch order",
    )
    require_equal(
        ring.count("counters.malformed_record_count += 1u"),
        1,
        "ring malformed counter owner count",
    )
    forbid_regex(ring, r"reader->rd\s*=\s*view->absolute_next_rd", RING_REL.as_posix())


def validate_streamer_udp_and_policy(root: Path) -> None:
    streamer = read_text(root / STREAMER_REL)
    csr = read_text(root / CSR_REL)
    udp = read_text(root / UDP_REL)
    runner = read_text(root / RUNNER_REL)
    service = read_text(root / SERVICE_REL)

    require_tokens(
        streamer,
        (
            '"--dummy-udp-counter"',
            "trecap_streamer_open_dummy_udp",
            "trecap_streamer_run_dummy_udp_counter",
            "trecap_status_build_diagnostic",
            "trecap_hps_config_validate_live_ddr_reservation",
            "TRECAP_STREAMER_EXIT_MALFORMED_LATCHED",
            "TRECAP_RING_READER_MALFORMED_LATCHED",
            "state->transport_enabled = false",
            "TRECAP_RING_RECORD_CLASS_WRAP",
            "TRECAP_RING_RECORD_CLASS_OVERSIZED",
            "TRECAP_STREAMER_COMMAND_BUDGET_PER_PASS",
            "state->csr_identity_verified = true",
            "state->csr_mapped && state->csr_identity_verified",
            "trecap_csr_require_control_levels(&state->csr, false, true)",
            "trecap_csr_require_control_levels(&state->csr, true, true)",
        ),
        STREAMER_REL.as_posix(),
    )
    require_tokens(
        csr,
        (
            "trecap_csr_require_control_levels",
            "TCSR_STATUS_TELEMETRY_ENABLED_MASK",
            "TCSR_STATUS_RING_WRITER_ENABLED_MASK",
            "trecap_csr_require_ring_configured",
            "TCSR_STATUS_MALFORMED_CONFIG_MASK",
            "TCSR_STATUS_RING_CONFIGURED_MASK",
        ),
        CSR_REL.as_posix(),
    )
    forbid_regex(streamer, r"malformed_record_count\s*\+=", STREAMER_REL.as_posix())
    service_one = source_slice(
        streamer,
        "static int trecap_streamer_service_one_record",
        "static int trecap_streamer_service_ring",
        "streamer record service",
    )
    require_ordered(
        service_one,
        (
            "trecap_streamer_send_record_view",
            "trecap_ring_reader_advance",
            "trecap_ring_reader_note_forwarded",
        ),
        "send/commit/accounting order",
    )
    require_tokens(
        udp,
        (
            "sendmsg(sender->fd, msg, MSG_NOSIGNAL)",
            "timeout_style",
            "TRECAP_UDP_ERR_TIMEOUT",
            "sender->counters.send_error_count += 1u",
        ),
        UDP_REL.as_posix(),
    )
    require_tokens(
        runner,
        (
            "DUMMY_UDP_COUNTER=0",
            "--dummy-udp-counter)",
            "dummy UDP mode: CSR/DDR reservation check is not applicable",
            "live DT reg mismatch",
            "/proc/iomem is empty, masked, or lacks System RAM evidence",
            "unmasked_system_ram_ranges",
            "proof_cmd=(sudo -E python3)",
        ),
        RUNNER_REL.as_posix(),
    )
    require_tokens(
        service,
        (
            "Environment=TRECAP_MALFORMED_POLICY=",
            "RestartPreventExitStatus=3",
            "$TRECAP_MALFORMED_POLICY",
        ),
        SERVICE_REL.as_posix(),
    )
    forbid_regex(service, r"TRECAP_MALFORMED_POLICY=--stop-on-malformed", SERVICE_REL.as_posix())


def validate_test_and_document(root: Path) -> None:
    test = read_text(root / TEST_REL)
    doc = read_text(root / DOC_REL)
    require_tokens(
        test,
        (
            "test_valid_packet_types",
            "test_iomem_fail_closed",
            "test_embedded_nul_config_rejected",
            "test_fail_closed_reset_and_identity_cleanup",
            "test_command_budget",
            "test_wrap_record",
            "test_oversized_and_hostile_length",
            "test_malformed_latch_and_rearm",
            "test_invalid_atomic_pointer_latches",
            "test_malformed_mmio_failure_stays_latched",
            "test_commit_and_send_failures",
            "test_dummy_counter",
            "STEP13_HPS_TRANSPORT_PASS",
            "__wrap_sendmsg",
        ),
        TEST_REL.as_posix(),
    )
    require_tokens(
        doc,
        (
            "Step 13",
            "latch-and-stay-alive",
            "--dummy-udp-counter",
            "WAVE",
            "SPEC64",
            "SPEC129",
            "METRICS",
            "STATUS",
            "does not prove",
        ),
        DOC_REL.as_posix(),
    )


def run_checks(root: Path, force_fallback: bool) -> str:
    validator = validate_contract(root, force_fallback)
    validate_runtime_config(root)
    validate_ring_reader(root)
    validate_streamer_udp_and_policy(root)
    validate_test_and_document(root)
    return validator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repo_root_from_script())
    parser.add_argument("--force-fallback-schema-validator", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    try:
        validator = run_checks(root, args.force_fallback_schema_validator)
    except CheckFailure as exc:
        print(f"ERROR: Step-13 HPS transport source check failed: {exc}", file=sys.stderr)
        return 1
    print("Step-13 DE1-SoC HPS transport source check: PASS")
    print(f"  schema validator : {validator}")
    print("  ring/UDP         : 5 telemetry types, WRAP, bounded send, commit-after-consume")
    print("  malformed        : exactly-once latch; reset + reconfigure + Rd0 required")
    print("  dummy M0         : diagnostic STATUS with monotonic counter, no CSR/DDR mapping")
    print("  evidence         : source-only; HPS/Linux/network/systemd/hardware pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
