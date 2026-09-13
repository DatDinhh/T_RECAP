#!/usr/bin/env python3
"""Dependency-free Step-14 generated-contract and PC command-client tests."""

from __future__ import annotations

import copy
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

PC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PC_ROOT.parents[1]
for candidate in (PC_ROOT, REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from generated import trecap_packet as gen  # noqa: E402
from trecap_dashboard.command_client import (  # noqa: E402
    CommandClient,
    CommandClientConfig,
    CommandClientError,
    CommandPacket,
    CommandResult,
    DryRunCommandClient,
)
from trecap_dashboard.config import CommandDefaults, load_dashboard_config  # noqa: E402


HPS_ENDPOINT = ("192.168.10.2", 5006)


def diagnostic_status(*, flags: int | None = None, seq: int = 0, reserved: int = 0) -> bytes:
    payload_bytes = gen.expected_payload_bytes("STATUS")
    diagnostic_mask = 1 << gen.COMMON_FLAG_BITS["status_diagnostic"][0]
    header = gen.TELEMETRY_HEADER_STRUCT.pack(
        gen.TELEMETRY_MAGIC,
        gen.TELEMETRY_HEADER_VERSION,
        gen.TELEMETRY_HEADER_BYTES,
        gen.PACKET_TYPES["STATUS"],
        diagnostic_mask if flags is None else flags,
        seq,
        0,
        payload_bytes,
        0,
    )
    payload = bytearray(payload_bytes)
    off = gen.PAYLOAD_OFFSETS["STATUS"]["reserved"]
    payload[off : off + 4] = int(reserved).to_bytes(4, "little")
    return header + payload


def applied_result(packet: CommandPacket, *, disposition: str = "APPLIED") -> bytes:
    return CommandResult(
        packet.cmd_type,
        packet.seq,
        gen.COMMAND_DISPOSITIONS[disposition],
        gen.COMMAND_REJECT_REASONS["NONE"],
        0x0000_2001,
        0x0001_0008,
    ).to_bytes()


class FakeSocket:
    def __init__(self, on_send=None) -> None:
        self.on_send = on_send
        self.events: list[tuple[str, object]] = []
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.rx: list[tuple[bytes, tuple[str, int]] | BaseException] = []
        self.closed = False
        self.timeout = None

    def settimeout(self, value) -> None:
        self.timeout = value
        self.events.append(("timeout", value))

    def setsockopt(self, *args) -> None:
        self.events.append(("setsockopt", args))

    def bind(self, endpoint) -> None:
        self.events.append(("bind", endpoint))

    def sendto(self, data, endpoint) -> int:
        raw = bytes(data)
        self.events.append(("send", endpoint))
        self.sent.append((raw, endpoint))
        if self.on_send is not None:
            self.on_send(self, CommandPacket.from_bytes(raw))
        return len(raw)

    def recvfrom(self, _size):
        self.events.append(("recv", None))
        if not self.rx:
            raise socket.timeout("fake timeout")
        item = self.rx.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class GeneratedContractTests(unittest.TestCase):
    def test_exact_request_and_result_abi(self) -> None:
        self.assertEqual(gen.COMMAND_STRUCT.format, "<IHHIIIII")
        self.assertEqual(gen.COMMAND_STRUCT.size, 28)
        self.assertEqual(gen.COMMAND_RESULT_STRUCT.size, 32)
        self.assertEqual(gen.COMMAND_RESULT_MAGIC, 0x54524352)
        self.assertEqual(gen.COMMAND_RESULT_VERSION, 2)
        self.assertEqual(
            gen.COMMAND_RESULT_OFFSETS,
            {
                "magic": 0,
                "version": 4,
                "cmd_type": 6,
                "seq": 8,
                "disposition": 12,
                "reject_reason": 16,
                "fpga_status": 20,
                "csr_version": 24,
                "crc32": 28,
            },
        )

    def test_exact_command_ids_versions_dispositions_and_reasons(self) -> None:
        self.assertEqual(list(gen.COMMAND_TYPES.values()), list(range(1, 15)))
        self.assertEqual(gen.COMMAND_V1_TYPES, frozenset(range(1, 8)))
        self.assertEqual(gen.COMMAND_V2_TYPES, frozenset(range(1, 15)))
        self.assertEqual(
            gen.COMMAND_DISPOSITIONS,
            {"APPLIED": 0, "NOOP": 1, "REJECTED": 2, "FAILED": 3},
        )
        self.assertEqual(
            gen.COMMAND_REJECT_REASONS,
            {
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
            },
        )

    def test_generated_c_and_sv_mirrors(self) -> None:
        c_header = (REPO_ROOT / "sw/hps/include/generated/trecap_packet.h").read_text()
        sv_pkg = (REPO_ROOT / "rtl/include/generated/trecap_packet_pkg.sv").read_text()
        for needle in (
            "TCMD_VERSION_V1",
            "TCMD_VERSION_V2",
            "TCMD_RESULT_BYTES",
            "TCMD_RESULT_REJECT_REASON_OFFSET",
            "TCMD_TYPE_READ_STATUS_VERSION",
            "TCMD_REJECT_VERSION_MISMATCH",
        ):
            self.assertIn(needle, c_header)
            self.assertIn(needle, sv_pkg)

    def test_schema_has_frozen_step14_shapes(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "spec/schemas/packet_layouts.schema.json").read_text()
        )
        packet = json.loads((REPO_ROOT / "spec/generated/packet_layouts.json").read_text())
        self.assertEqual(packet["common_header"]["fields"][1]["required_value"], 1)
        self.assertEqual(packet["command_packet"]["fields"][1]["supported_values"], [1, 2])
        self.assertEqual(schema["properties"]["command_packet"]["properties"]["fields"]["maxItems"], 8)
        self.assertEqual(schema["properties"]["command_packet"]["properties"]["command_types"]["maxItems"], 14)
        self.assertEqual(schema["properties"]["command_result"]["properties"]["fields"]["maxItems"], 9)
        frozen_pairs = (
            (
                packet["command_packet"]["fields"],
                schema["properties"]["command_packet"]["properties"]["fields"],
            ),
            (
                packet["command_packet"]["command_types"],
                schema["properties"]["command_packet"]["properties"]["command_types"],
            ),
            (
                packet["command_result"]["fields"],
                schema["properties"]["command_result"]["properties"]["fields"],
            ),
            (
                packet["command_result"]["dispositions"],
                schema["properties"]["command_result"]["properties"]["dispositions"],
            ),
            (
                packet["command_result"]["reject_reasons"],
                schema["properties"]["command_result"]["properties"]["reject_reasons"],
            ),
        )
        for source_values, rule in frozen_pairs:
            frozen_values = [item["const"] for item in rule["prefixItems"]]
            self.assertEqual(frozen_values, source_values)
            self.assertIs(rule["items"], False)

        # Representative dangerous ABI mutations must differ from the frozen schema.
        bad_intro = copy.deepcopy(packet["command_packet"]["command_types"])
        bad_intro[7]["introduced_in_version"] = 1
        self.assertNotEqual(
            bad_intro,
            [item["const"] for item in frozen_pairs[1][1]["prefixItems"]],
        )
        bad_offset = copy.deepcopy(packet["command_result"]["fields"])
        bad_offset[0]["offset"] = 4
        self.assertNotEqual(
            bad_offset,
            [item["const"] for item in frozen_pairs[2][1]["prefixItems"]],
        )
        bad_reason = copy.deepcopy(packet["command_result"]["reject_reasons"])
        bad_reason[13]["code"] = 12
        self.assertNotEqual(
            bad_reason,
            [item["const"] for item in frozen_pairs[4][1]["prefixItems"]],
        )


class PacketAndResultTests(unittest.TestCase):
    def test_v1_exact_seven_and_v2_exact_fourteen(self) -> None:
        for cmd in range(1, 8):
            args = (1, 2, 3) if cmd == gen.COMMAND_TYPES["PING"] else (0, 0, 0)
            if cmd == gen.COMMAND_TYPES["SET_WAVE_DECIM"]:
                args = (1, 0, 0)
            packet = CommandPacket(cmd, 9, *args, version=1)
            self.assertEqual(CommandPacket.from_bytes(packet.to_bytes()), packet)
        with self.assertRaises(CommandClientError):
            CommandPacket(gen.COMMAND_TYPES["SET_SPEC_MODE"], 1, version=1).to_bytes()
        for cmd in range(1, 15):
            arg0 = 1 if cmd in {
                gen.COMMAND_TYPES["SET_WAVE_DECIM"],
                gen.COMMAND_TYPES["SET_TELEMETRY_ENABLE"],
            } else 0
            CommandPacket(cmd, cmd, arg0=arg0, version=2).to_bytes()

    def test_ping_arguments_ignored_in_both_versions(self) -> None:
        for version in (1, 2):
            packet = CommandPacket(
                gen.COMMAND_TYPES["PING"],
                0xFFFF_FFFF,
                0x1111_2222,
                0x3333_4444,
                0x5555_6666,
                version=version,
            )
            self.assertEqual(len(packet.to_bytes()), 28)

    def test_reserved_and_range_rejects(self) -> None:
        bad = [
            CommandPacket(gen.COMMAND_TYPES["SET_SPEC_MODE"], 1, 3, version=2),
            CommandPacket(gen.COMMAND_TYPES["SET_TELEMETRY_ENABLE"], 1, 2, version=2),
            CommandPacket(gen.COMMAND_TYPES["CONFIGURE_DDR_RING"], 1, 1, version=2),
            CommandPacket(gen.COMMAND_TYPES["SET_SPEC_SHIFT"], 1, 56, version=2),
            CommandPacket(gen.COMMAND_TYPES["SET_WAVE_DECIM"], 1, 0, version=2),
        ]
        for packet in bad:
            with self.subTest(packet=packet):
                with self.assertRaises(CommandClientError):
                    packet.to_bytes()

    def test_result_roundtrip_and_semantic_rejects(self) -> None:
        result = CommandResult(
            gen.COMMAND_TYPES["READ_STATUS_VERSION"],
            123,
            gen.COMMAND_DISPOSITIONS["NOOP"],
            gen.COMMAND_REJECT_REASONS["NONE"],
            0xDEAD_BEEF,
            0x0001_0008,
        )
        self.assertEqual(CommandResult.from_bytes(result.to_bytes()), result)
        for malformed in (result.to_bytes()[:-1], result.to_bytes() + b"\0"):
            with self.assertRaises(CommandClientError):
                CommandResult.from_bytes(malformed)
        with self.assertRaises(CommandClientError):
            CommandResult(
                1,
                1,
                gen.COMMAND_DISPOSITIONS["APPLIED"],
                gen.COMMAND_REJECT_REASONS["IO"],
                0,
                0,
            ).to_bytes()


class CommandClientSocketTests(unittest.TestCase):
    def make_client(self, fake: FakeSocket, *, retries: int = 0) -> CommandClient:
        config = CommandClientConfig(timeout_s=0.01, retries=retries)
        with mock.patch("trecap_dashboard.command_client.socket.socket", return_value=fake):
            client = CommandClient(config)
            client.open()
        return client

    def test_bind_ping_handshake_then_correlated_result(self) -> None:
        def on_send(fake: FakeSocket, packet: CommandPacket) -> None:
            if packet.command_name == "PING":
                fake.rx.append((diagnostic_status(), HPS_ENDPOINT))
            else:
                fake.rx.append((applied_result(packet), HPS_ENDPOINT))

        fake = FakeSocket(on_send)
        client = self.make_client(fake)
        sent = client.set_spec_mode(2)
        packets = [CommandPacket.from_bytes(raw) for raw, _ in fake.sent]
        self.assertEqual([p.command_name for p in packets], ["PING", "SET_SPEC_MODE"])
        self.assertEqual(fake.events[1], ("bind", ("0.0.0.0", 5007)))
        self.assertEqual(packets[0].version, 2)
        self.assertEqual(sent.result.disposition_name, "APPLIED")
        self.assertEqual(sent.attempts, 1)

    def test_timeout_retries_byte_identical_non_ping_request(self) -> None:
        mutation_count = 0

        def on_send(fake: FakeSocket, packet: CommandPacket) -> None:
            nonlocal mutation_count
            if packet.command_name == "PING":
                fake.rx.append((diagnostic_status(), HPS_ENDPOINT))
                return
            mutation_count += 1
            if mutation_count == 1:
                fake.rx.append(socket.timeout("lost first result"))
            else:
                fake.rx.append((applied_result(packet), HPS_ENDPOINT))

        fake = FakeSocket(on_send)
        client = self.make_client(fake, retries=1)
        sent = client.clear_counters()
        mutation_bytes = [raw for raw, _ in fake.sent][1:]
        self.assertEqual(len(mutation_bytes), 2)
        self.assertEqual(mutation_bytes[0], mutation_bytes[1])
        self.assertEqual(sent.attempts, 2)
        self.assertEqual(client.stats.retries, 1)

    def test_ping_handshake_failure_sends_no_non_ping_command(self) -> None:
        def on_send(fake: FakeSocket, packet: CommandPacket) -> None:
            if packet.command_name == "PING":
                fake.rx.append((diagnostic_status(), ("192.168.10.99", 5006)))

        fake = FakeSocket(on_send)
        client = self.make_client(fake)
        with self.assertRaises(CommandClientError):
            client.reset_transport()
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(CommandPacket.from_bytes(fake.sent[0][0]).command_name, "PING")

    def test_ping_diagnostic_strict_flags_seq_and_reserved(self) -> None:
        invalid = [
            diagnostic_status(flags=(1 << gen.COMMON_FLAG_BITS["status_diagnostic"][0]) | 1),
            diagnostic_status(seq=1),
            diagnostic_status(reserved=1),
        ]
        for raw in invalid:
            with self.subTest():
                fake = FakeSocket(
                    lambda sock, packet, value=raw: sock.rx.append((value, HPS_ENDPOINT))
                )
                client = self.make_client(fake)
                with self.assertRaises(CommandClientError):
                    client.read_status_version()
                self.assertEqual(len(fake.sent), 1)

    def test_read_status_version_requires_noop(self) -> None:
        def on_send(fake: FakeSocket, packet: CommandPacket) -> None:
            if packet.command_name == "PING":
                fake.rx.append((diagnostic_status(), HPS_ENDPOINT))
            else:
                fake.rx.append((applied_result(packet, disposition="NOOP"), HPS_ENDPOINT))

        fake = FakeSocket(on_send)
        client = self.make_client(fake)
        sent = client.read_status_version()
        self.assertEqual(sent.result.disposition_name, "NOOP")
        self.assertEqual(sent.result.fpga_status, 0x0000_2001)
        self.assertEqual(sent.result.csr_version, 0x0001_0008)

    def test_v1_is_fire_and_forget_and_rejects_v2_only_type(self) -> None:
        fake = FakeSocket()
        config = CommandClientConfig(protocol_version=1, retries=0)
        with mock.patch("trecap_dashboard.command_client.socket.socket", return_value=fake):
            client = CommandClient(config)
            sent = client.clear_metrics()
        self.assertIsNone(sent.result)
        self.assertEqual(len(fake.sent), 1)
        with self.assertRaises(CommandClientError):
            client.set_spec_mode(1)

    def test_v1_ping_awaits_status_seq_zero_without_command_result(self) -> None:
        def on_send(fake: FakeSocket, packet: CommandPacket) -> None:
            self.assertEqual(packet.version, 1)
            self.assertEqual(packet.command_name, "PING")
            fake.rx.append((diagnostic_status(seq=0), HPS_ENDPOINT))

        fake = FakeSocket(on_send)
        config = CommandClientConfig(protocol_version=1, retries=0)
        with mock.patch("trecap_dashboard.command_client.socket.socket", return_value=fake):
            client = CommandClient(config)
            sent = client.ping(arg0=1, arg1=2, arg2=3)
        self.assertIsNone(sent.result)
        self.assertEqual(sent.diagnostic_status, diagnostic_status(seq=0))
        self.assertEqual(len(fake.sent), 1)


class ConfigAndDryRunTests(unittest.TestCase):
    def test_canonical_defaults(self) -> None:
        defaults = CommandDefaults()
        self.assertEqual(defaults.port, 5006)
        self.assertEqual(defaults.bind_port, 5007)
        self.assertEqual(defaults.protocol_version, 2)
        direct = load_dashboard_config(PC_ROOT / "configs/dashboard_direct_link.json")
        self.assertEqual(direct.command.bind_port, 5007)
        self.assertEqual(direct.command.protocol_version, 2)

    def test_every_v2_command_builder_and_single_implicit_ping(self) -> None:
        client = DryRunCommandClient()
        actions = [
            lambda: client.set_thr2(1),
            client.clear_metrics,
            lambda: client.set_source_mode(0),
            lambda: client.set_packet_enable(0),
            lambda: client.set_wave_decim(1),
            lambda: client.set_spec_shift(0),
            lambda: client.ping(arg0=1, arg1=2, arg2=3),
            lambda: client.set_spec_mode(0),
            lambda: client.set_telemetry_enable(False),
            client.configure_ddr_ring,
            client.reset_transport,
            client.clear_counters,
            client.start_bram_replay,
            client.read_status_version,
        ]
        for action in actions:
            action()
        names = [packet.command_name for packet in client.sent_packets]
        self.assertEqual(names.count("PING"), 2)  # one implicit and one requested
        self.assertEqual(set(names), set(gen.COMMAND_TYPES))


if __name__ == "__main__":
    unittest.main(verbosity=2)
