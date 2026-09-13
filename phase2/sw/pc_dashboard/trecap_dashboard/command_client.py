"""PC UDP command client with Revision-G v1 and Step-14 v2 support."""

from __future__ import annotations

import argparse
import importlib.util
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterable, Mapping, Sequence

DEFAULT_HPS_HOST = "192.168.10.2"
DEFAULT_COMMAND_PORT = 5006
DEFAULT_LOCAL_COMMAND_PORT = 5007
DEFAULT_TIMEOUT_S = 1.0
DEFAULT_RETRIES = 2
MAX_U32 = 0xFFFF_FFFF
MAX_THR2 = (1 << 56) - 1
MAX_SPEC_SHIFT = 55
MAX_WAVE_DECIM = 0xFFFF


class CommandClientError(ValueError):
    """Raised when a request or result is not safe to use."""


def _load_generated_packet() -> ModuleType:
    try:
        from generated import trecap_packet as generated_packet  # type: ignore

        return generated_packet
    except Exception:
        pass
    this_file = Path(__file__).resolve()
    for candidate in (
        this_file.parents[1] / "generated" / "trecap_packet.py",
        this_file.parents[2] / "sw" / "pc_dashboard" / "generated" / "trecap_packet.py",
    ):
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "trecap_dashboard_generated_packet", candidate
            )
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    raise CommandClientError(
        "generated packet constants not found; run `make gen-headers` before using commands"
    )


_gen = _load_generated_packet()


def _bit_mask(pair: Sequence[int]) -> int:
    lo, hi = int(pair[0]), int(pair[1])
    return ((1 << (hi - lo + 1)) - 1) << lo


_PACKET_BITS: Mapping[str, Sequence[int]] = _gen.CSR_BITS["PACKET_ENABLE"]
PACKET_ENABLE_WAVE = _bit_mask(_PACKET_BITS["WAVE_EN"])
PACKET_ENABLE_SPEC = _bit_mask(_PACKET_BITS["SPEC_EN"])
PACKET_ENABLE_METRICS = _bit_mask(_PACKET_BITS["METRICS_EN"])
PACKET_ENABLE_STATUS = _bit_mask(_PACKET_BITS["STATUS_EN"])
PACKET_ENABLE_STATUS_ONLY = PACKET_ENABLE_STATUS
PACKET_ENABLE_FULL_DEMO = (
    PACKET_ENABLE_WAVE
    | PACKET_ENABLE_SPEC
    | PACKET_ENABLE_METRICS
    | PACKET_ENABLE_STATUS
)
PACKET_ENABLE_ALLOWED_MASK = PACKET_ENABLE_FULL_DEMO


def _u32(value: int, name: str) -> int:
    value_i = int(value)
    if not (0 <= value_i <= MAX_U32):
        raise CommandClientError(f"{name} must fit in uint32")
    return value_i


def _put(buf: bytearray, offsets: Mapping[str, int], name: str, value: int, width: int) -> None:
    off = int(offsets[name])
    buf[off : off + width] = int(value).to_bytes(width, "little", signed=False)


def _get(buf: bytes, offsets: Mapping[str, int], name: str, width: int) -> int:
    off = int(offsets[name])
    return int.from_bytes(buf[off : off + width], "little", signed=False)


def command_type(command: str | int) -> int:
    if isinstance(command, str):
        name = command.strip().upper().replace("-", "_")
        if name not in _gen.COMMAND_TYPES:
            raise CommandClientError(f"unknown command type: {command}")
        return int(_gen.COMMAND_TYPES[name])
    value = int(command)
    if value not in _gen.COMMAND_TYPE_NAMES:
        raise CommandClientError(f"unknown command type ID: {value}")
    return value


def command_name(command: str | int) -> str:
    return str(_gen.COMMAND_TYPE_NAMES[command_type(command)])


def validate_thr2(thr2: int) -> None:
    if not (0 <= int(thr2) <= MAX_THR2):
        raise CommandClientError("THR2 must fit in unsigned 56-bit range")


def split_thr2(thr2: int) -> tuple[int, int]:
    validate_thr2(thr2)
    return int(thr2) & MAX_U32, (int(thr2) >> 32) & 0x00FF_FFFF


def join_thr2(lo: int, hi: int) -> int:
    value = (_u32(hi, "thr2_hi") << 32) | _u32(lo, "thr2_lo")
    validate_thr2(value)
    return value


def validate_source_mode(source_mode: int) -> None:
    if not (0 <= int(source_mode) <= 3):
        raise CommandClientError("source mode must be in range 0..3")


def validate_spec_mode(spec_mode: int) -> None:
    if not (0 <= int(spec_mode) <= 2):
        raise CommandClientError("spectrum mode must be in range 0..2")


def validate_telemetry_enable(enabled: int | bool) -> None:
    if int(enabled) not in (0, 1):
        raise CommandClientError("telemetry enable must be 0 or 1")


def validate_packet_enable(mask: int) -> None:
    value = _u32(mask, "packet_enable")
    if value & ~PACKET_ENABLE_ALLOWED_MASK:
        raise CommandClientError(
            "PACKET_ENABLE may only set WAVE, SPEC, METRICS, and STATUS in Revision G"
        )


def packet_enable_from_names(names: Iterable[str] | str) -> int:
    tokens = (
        [part for part in names.replace(",", " ").split() if part]
        if isinstance(names, str)
        else list(names)
    )
    aliases = {
        "WAVE": PACKET_ENABLE_WAVE,
        "SPEC": PACKET_ENABLE_SPEC,
        "SPEC64": PACKET_ENABLE_SPEC,
        "SPEC129": PACKET_ENABLE_SPEC,
        "METRICS": PACKET_ENABLE_METRICS,
        "STATUS": PACKET_ENABLE_STATUS,
        "STATUS_ONLY": PACKET_ENABLE_STATUS_ONLY,
        "FULL": PACKET_ENABLE_FULL_DEMO,
        "FULL_DEMO": PACKET_ENABLE_FULL_DEMO,
        "NONE": 0,
        "OFF": 0,
        "DISABLED": 0,
    }
    mask = 0
    for token in tokens:
        key = str(token).strip().upper().replace("-", "_")
        if key not in aliases:
            raise CommandClientError(f"unsupported packet-enable token: {token}")
        mask |= aliases[key]
    validate_packet_enable(mask)
    return mask


def packet_enable_profile(profile: str) -> int:
    key = profile.strip().upper().replace("-", "_")
    if key in {"STATUS", "STATUS_ONLY"}:
        return PACKET_ENABLE_STATUS_ONLY
    if key in {"FULL", "FULL_DEMO"}:
        return PACKET_ENABLE_FULL_DEMO
    return packet_enable_from_names(profile)


def validate_wave_decim(decim: int) -> None:
    if not (1 <= int(decim) <= MAX_WAVE_DECIM):
        raise CommandClientError("WAVE_DECIM must be in range 1..65535")


def validate_spec_shift(spec_shift: int) -> None:
    if not (0 <= int(spec_shift) <= MAX_SPEC_SHIFT):
        raise CommandClientError("SPEC_SHIFT must be in range 0..55")


def _require_zero(command: str, *values: int) -> None:
    if any(int(value) != 0 for value in values):
        raise CommandClientError(f"{command} reserved arguments must be zero")


def validate_command_packet(packet: "CommandPacket") -> None:
    cmd_type = command_type(packet.cmd_type)
    version = int(packet.version)
    if version not in _gen.COMMAND_VERSIONS_SUPPORTED:
        raise CommandClientError(f"unsupported command version: {version}")
    allowed = (
        _gen.COMMAND_V1_TYPES
        if version == _gen.COMMAND_VERSION_V1
        else _gen.COMMAND_V2_TYPES
    )
    if cmd_type not in allowed:
        raise CommandClientError(
            f"{command_name(cmd_type)} is not available in command version {version}"
        )
    _u32(packet.seq, "seq")
    _u32(packet.arg0, "arg0")
    _u32(packet.arg1, "arg1")
    _u32(packet.arg2, "arg2")
    if packet.crc32 != 0:
        raise CommandClientError("command CRC is disabled; crc32 must be zero")

    if cmd_type == _gen.COMMAND_TYPES["SET_THR2"]:
        join_thr2(packet.arg0, packet.arg1)
        _require_zero("SET_THR2", packet.arg2)
    elif cmd_type == _gen.COMMAND_TYPES["CLEAR_METRICS"]:
        _require_zero("CLEAR_METRICS", packet.arg0, packet.arg1, packet.arg2)
    elif cmd_type == _gen.COMMAND_TYPES["SET_SOURCE_MODE"]:
        validate_source_mode(packet.arg0)
        _require_zero("SET_SOURCE_MODE", packet.arg1, packet.arg2)
    elif cmd_type == _gen.COMMAND_TYPES["SET_PACKET_ENABLE"]:
        validate_packet_enable(packet.arg0)
        _require_zero("SET_PACKET_ENABLE", packet.arg1, packet.arg2)
    elif cmd_type == _gen.COMMAND_TYPES["SET_WAVE_DECIM"]:
        validate_wave_decim(packet.arg0)
        _require_zero("SET_WAVE_DECIM", packet.arg1, packet.arg2)
    elif cmd_type == _gen.COMMAND_TYPES["SET_SPEC_SHIFT"]:
        validate_spec_shift(packet.arg0)
        _require_zero("SET_SPEC_SHIFT", packet.arg1, packet.arg2)
    elif cmd_type == _gen.COMMAND_TYPES["PING"]:
        return  # all PING arguments are ignored in both versions
    elif cmd_type == _gen.COMMAND_TYPES["SET_SPEC_MODE"]:
        validate_spec_mode(packet.arg0)
        _require_zero("SET_SPEC_MODE", packet.arg1, packet.arg2)
    elif cmd_type == _gen.COMMAND_TYPES["SET_TELEMETRY_ENABLE"]:
        validate_telemetry_enable(packet.arg0)
        _require_zero("SET_TELEMETRY_ENABLE", packet.arg1, packet.arg2)
    else:
        _require_zero(command_name(cmd_type), packet.arg0, packet.arg1, packet.arg2)


@dataclass(frozen=True, slots=True)
class CommandPacket:
    """One exact 28-byte little-endian request."""

    cmd_type: int
    seq: int
    arg0: int = 0
    arg1: int = 0
    arg2: int = 0
    crc32: int = 0
    version: int = int(_gen.COMMAND_VERSION_CURRENT)

    @property
    def command_name(self) -> str:
        return command_name(self.cmd_type)

    def validate(self) -> None:
        validate_command_packet(self)

    def to_bytes(self) -> bytes:
        self.validate()
        out = bytearray(int(_gen.COMMAND_PACKET_BYTES))
        offsets = _gen.COMMAND_OFFSETS
        _put(out, offsets, "magic", int(_gen.COMMAND_MAGIC), 4)
        _put(out, offsets, "version", self.version, 2)
        _put(out, offsets, "cmd_type", self.cmd_type, 2)
        _put(out, offsets, "seq", self.seq, 4)
        _put(out, offsets, "arg0", self.arg0, 4)
        _put(out, offsets, "arg1", self.arg1, 4)
        _put(out, offsets, "arg2", self.arg2, 4)
        _put(out, offsets, "crc32", self.crc32, 4)
        return bytes(out)

    @classmethod
    def from_bytes(cls, data: bytes | bytearray | memoryview) -> "CommandPacket":
        raw = bytes(data)
        if len(raw) != int(_gen.COMMAND_PACKET_BYTES):
            raise CommandClientError(
                f"command packet must be exactly {_gen.COMMAND_PACKET_BYTES} bytes"
            )
        offsets = _gen.COMMAND_OFFSETS
        if _get(raw, offsets, "magic", 4) != int(_gen.COMMAND_MAGIC):
            raise CommandClientError("bad command magic")
        packet = cls(
            _get(raw, offsets, "cmd_type", 2),
            _get(raw, offsets, "seq", 4),
            _get(raw, offsets, "arg0", 4),
            _get(raw, offsets, "arg1", 4),
            _get(raw, offsets, "arg2", 4),
            _get(raw, offsets, "crc32", 4),
            version=_get(raw, offsets, "version", 2),
        )
        packet.validate()
        return packet


@dataclass(frozen=True, slots=True)
class CommandResult:
    """One exact 32-byte version-2 command result."""

    cmd_type: int
    seq: int
    disposition: int
    reject_reason: int
    fpga_status: int
    csr_version: int
    crc32: int = 0

    @property
    def command_name(self) -> str:
        return command_name(self.cmd_type)

    @property
    def disposition_name(self) -> str:
        return str(_gen.COMMAND_DISPOSITION_NAMES[self.disposition])

    @property
    def reject_reason_name(self) -> str:
        return str(_gen.COMMAND_REJECT_REASON_NAMES[self.reject_reason])

    @property
    def succeeded(self) -> bool:
        return self.disposition in {
            int(_gen.COMMAND_DISPOSITIONS["APPLIED"]),
            int(_gen.COMMAND_DISPOSITIONS["NOOP"]),
        }

    def validate(self) -> None:
        command_type(self.cmd_type)
        _u32(self.seq, "result.seq")
        _u32(self.fpga_status, "result.fpga_status")
        _u32(self.csr_version, "result.csr_version")
        if self.disposition not in _gen.COMMAND_DISPOSITION_NAMES:
            raise CommandClientError(f"unknown command disposition: {self.disposition}")
        if self.reject_reason not in _gen.COMMAND_REJECT_REASON_NAMES:
            raise CommandClientError(f"unknown command reject reason: {self.reject_reason}")
        if self.crc32 != 0:
            raise CommandClientError("command-result CRC is disabled; crc32 must be zero")
        if self.succeeded and self.reject_reason != _gen.COMMAND_REJECT_REASONS["NONE"]:
            raise CommandClientError("APPLIED/NOOP command result must use reject reason NONE")

    def to_bytes(self) -> bytes:
        self.validate()
        out = bytearray(int(_gen.COMMAND_RESULT_BYTES))
        offsets = _gen.COMMAND_RESULT_OFFSETS
        _put(out, offsets, "magic", int(_gen.COMMAND_RESULT_MAGIC), 4)
        _put(out, offsets, "version", int(_gen.COMMAND_RESULT_VERSION), 2)
        _put(out, offsets, "cmd_type", self.cmd_type, 2)
        _put(out, offsets, "seq", self.seq, 4)
        _put(out, offsets, "disposition", self.disposition, 4)
        _put(out, offsets, "reject_reason", self.reject_reason, 4)
        _put(out, offsets, "fpga_status", self.fpga_status, 4)
        _put(out, offsets, "csr_version", self.csr_version, 4)
        _put(out, offsets, "crc32", self.crc32, 4)
        return bytes(out)

    @classmethod
    def from_bytes(cls, data: bytes | bytearray | memoryview) -> "CommandResult":
        raw = bytes(data)
        if len(raw) != int(_gen.COMMAND_RESULT_BYTES):
            raise CommandClientError(
                f"command result must be exactly {_gen.COMMAND_RESULT_BYTES} bytes"
            )
        offsets = _gen.COMMAND_RESULT_OFFSETS
        if _get(raw, offsets, "magic", 4) != int(_gen.COMMAND_RESULT_MAGIC):
            raise CommandClientError("bad command-result magic")
        if _get(raw, offsets, "version", 2) != int(_gen.COMMAND_RESULT_VERSION):
            raise CommandClientError("bad command-result version")
        result = cls(
            _get(raw, offsets, "cmd_type", 2),
            _get(raw, offsets, "seq", 4),
            _get(raw, offsets, "disposition", 4),
            _get(raw, offsets, "reject_reason", 4),
            _get(raw, offsets, "fpga_status", 4),
            _get(raw, offsets, "csr_version", 4),
            _get(raw, offsets, "crc32", 4),
        )
        result.validate()
        return result


def _validate_diagnostic_status(data: bytes | bytearray | memoryview) -> bytes:
    """Validate the exact Revision-G STATUS response used by PING."""

    raw = bytes(data)
    expected_payload = int(_gen.expected_payload_bytes("STATUS"))
    expected_bytes = int(_gen.TELEMETRY_HEADER_BYTES) + expected_payload
    if len(raw) != expected_bytes:
        raise CommandClientError(
            f"PING diagnostic STATUS must be exactly {expected_bytes} bytes"
        )
    (
        magic,
        version,
        header_bytes,
        packet_type,
        flags,
        seq,
        _timestamp,
        payload_bytes,
        header_crc,
    ) = _gen.TELEMETRY_HEADER_STRUCT.unpack_from(raw)
    diagnostic_mask = _bit_mask(_gen.COMMON_FLAG_BITS["status_diagnostic"])
    if magic != int(_gen.TELEMETRY_MAGIC):
        raise CommandClientError("bad PING diagnostic telemetry magic")
    if version != int(_gen.TELEMETRY_HEADER_VERSION):
        raise CommandClientError("bad PING diagnostic telemetry version")
    if header_bytes != int(_gen.TELEMETRY_HEADER_BYTES):
        raise CommandClientError("bad PING diagnostic header size")
    if packet_type != int(_gen.PACKET_TYPES["STATUS"]):
        raise CommandClientError("PING response is not STATUS")
    if flags != diagnostic_mask:
        raise CommandClientError("PING STATUS flags must equal status_diagnostic only")
    if seq != 0:
        raise CommandClientError("PING diagnostic STATUS sequence must be zero")
    if payload_bytes != expected_payload:
        raise CommandClientError("bad PING diagnostic STATUS payload size")
    if header_crc != 0:
        raise CommandClientError("PING diagnostic STATUS header CRC must be zero")
    reserved_off = int(_gen.TELEMETRY_HEADER_BYTES) + int(
        _gen.PAYLOAD_OFFSETS["STATUS"]["reserved"]
    )
    if int.from_bytes(raw[reserved_off : reserved_off + 4], "little") != 0:
        raise CommandClientError("PING diagnostic STATUS reserved payload word must be zero")
    return raw


@dataclass(frozen=True, slots=True)
class CommandClientConfig:
    host: str = DEFAULT_HPS_HOST
    port: int = DEFAULT_COMMAND_PORT
    bind_host: str | None = None
    bind_port: int = DEFAULT_LOCAL_COMMAND_PORT
    timeout_s: float = DEFAULT_TIMEOUT_S
    sequence_start: int = 1
    protocol_version: int = int(_gen.COMMAND_VERSION_CURRENT)
    retries: int = DEFAULT_RETRIES
    allow_broadcast: bool = False

    def validate(self) -> None:
        if not self.host:
            raise CommandClientError("command host must not be empty")
        if not (1 <= int(self.port) <= 65535):
            raise CommandClientError("command port must be in range 1..65535")
        if not (1 <= int(self.bind_port) <= 65535):
            raise CommandClientError("bind_port must be in range 1..65535")
        if float(self.timeout_s) < 0.0:
            raise CommandClientError("timeout_s must be >= 0")
        if int(self.protocol_version) not in _gen.COMMAND_VERSIONS_SUPPORTED:
            raise CommandClientError("protocol_version must be 1 or 2")
        if int(self.retries) < 0:
            raise CommandClientError("retries must be >= 0")
        _u32(self.sequence_start, "sequence_start")


@dataclass(slots=True)
class CommandClientStats:
    commands_sent: int = 0
    bytes_sent: int = 0
    results_received: int = 0
    result_timeouts: int = 0
    retries: int = 0
    ignored_results: int = 0
    diagnostic_statuses: int = 0
    session_pings: int = 0
    last_seq: int | None = None
    last_cmd_type: int | None = None
    last_send_time_ns: int | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class CommandSendResult:
    packet: CommandPacket
    destination: tuple[str, int]
    bytes_sent: int
    send_time_ns: int
    result: CommandResult | None = None
    diagnostic_status: bytes | None = None
    attempts: int = 1
    dry_run: bool = False

    @property
    def command_name(self) -> str:
        return self.packet.command_name


class CommandClient:
    """Bound UDP client with v1 compatibility and v2 correlated retries."""

    def __init__(self, config: CommandClientConfig | None = None) -> None:
        self.config = config or CommandClientConfig()
        self.config.validate()
        self.destination = (self.config.host, int(self.config.port))
        self.stats = CommandClientStats()
        self._socket: socket.socket | None = None
        self._next_seq = int(self.config.sequence_start) & MAX_U32
        self._peer_probe_sent = False
        self._expected_source_host = self.config.host

    def __enter__(self) -> "CommandClient":
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def open(self) -> None:
        if self._socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(float(self.config.timeout_s))
            if self.config.allow_broadcast:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((self.config.bind_host or "0.0.0.0", int(self.config.bind_port)))
            self._expected_source_host = socket.gethostbyname(self.config.host)
        except Exception:
            sock.close()
            raise
        self._socket = sock

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is not None:
            sock.close()

    def _seq(self, explicit: int | None) -> int:
        if explicit is not None:
            return _u32(explicit, "seq")
        out = self._next_seq
        self._next_seq = (self._next_seq + 1) & MAX_U32
        return out

    def build(
        self,
        command: str | int,
        *,
        seq: int | None = None,
        arg0: int = 0,
        arg1: int = 0,
        arg2: int = 0,
        version: int | None = None,
    ) -> CommandPacket:
        packet = CommandPacket(
            command_type(command),
            self._seq(seq),
            _u32(arg0, "arg0"),
            _u32(arg1, "arg1"),
            _u32(arg2, "arg2"),
            version=int(self.config.protocol_version if version is None else version),
        )
        packet.validate()
        return packet

    @staticmethod
    def _expects_result(packet: CommandPacket) -> bool:
        return (
            packet.version == int(_gen.COMMAND_VERSION_V2)
            and packet.cmd_type != int(_gen.COMMAND_TYPES["PING"])
        )

    def _ensure_peer_probe(self, packet: CommandPacket) -> None:
        if not self._expects_result(packet) or self._peer_probe_sent:
            return
        probe = CommandPacket(
            int(_gen.COMMAND_TYPES["PING"]),
            (int(packet.seq) - 1) & MAX_U32,
            version=int(_gen.COMMAND_VERSION_V2),
        )
        self.send_packet(probe, _skip_probe=True)

    def _send_datagram(self, data: bytes, packet: CommandPacket) -> tuple[int, int]:
        self.open()
        assert self._socket is not None
        sent = self._socket.sendto(data, self.destination)
        if sent != len(data):
            raise CommandClientError(f"partial UDP command send: {sent}/{len(data)}")
        now = time.time_ns()
        self.stats.commands_sent += 1
        self.stats.bytes_sent += sent
        self.stats.last_seq = packet.seq
        self.stats.last_cmd_type = packet.cmd_type
        self.stats.last_send_time_ns = now
        self.stats.last_error = None
        return sent, now

    def _receive_correlated(self, packet: CommandPacket) -> CommandResult:
        assert self._socket is not None
        deadline = time.monotonic() + float(self.config.timeout_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining < 0.0:
                raise socket.timeout("command-result timeout")
            self._socket.settimeout(remaining)
            raw, source = self._socket.recvfrom(65535)
            if source != (self._expected_source_host, int(self.config.port)):
                self.stats.ignored_results += 1
                continue
            if len(raw) >= 4 and int.from_bytes(raw[:4], "little") == int(
                _gen.TELEMETRY_MAGIC
            ):
                _validate_diagnostic_status(raw)
                self.stats.diagnostic_statuses += 1
                continue
            try:
                result = CommandResult.from_bytes(raw)
            except CommandClientError:
                self.stats.ignored_results += 1
                continue
            if result.cmd_type != packet.cmd_type or result.seq != packet.seq:
                self.stats.ignored_results += 1
                continue
            self.stats.results_received += 1
            return result

    def _receive_diagnostic_status(self) -> bytes:
        assert self._socket is not None
        try:
            raw, source = self._socket.recvfrom(65535)
        except (socket.timeout, TimeoutError, BlockingIOError) as exc:
            raise CommandClientError(
                "timed out waiting for PING diagnostic STATUS; no non-PING command was sent"
            ) from exc
        expected_source = (self._expected_source_host, int(self.config.port))
        if source != expected_source:
            raise CommandClientError(
                "PING diagnostic STATUS came from an unexpected source endpoint"
            )
        diagnostic = _validate_diagnostic_status(raw)
        self.stats.diagnostic_statuses += 1
        return diagnostic

    def send_packet(
        self, packet: CommandPacket, *, _skip_probe: bool = False
    ) -> CommandSendResult:
        data = packet.to_bytes()
        if not _skip_probe:
            self._ensure_peer_probe(packet)
        expects_result = self._expects_result(packet)
        max_attempts = 1 + (int(self.config.retries) if expects_result else 0)
        total_sent = 0
        last_now = 0
        for attempt in range(1, max_attempts + 1):
            try:
                sent, last_now = self._send_datagram(data, packet)
                total_sent += sent
                if packet.cmd_type == int(_gen.COMMAND_TYPES["PING"]):
                    self.stats.session_pings += 1
                    diagnostic = self._receive_diagnostic_status()
                    if packet.version == int(_gen.COMMAND_VERSION_V2):
                        self._peer_probe_sent = True
                    return CommandSendResult(
                        packet,
                        self.destination,
                        total_sent,
                        last_now,
                        diagnostic_status=diagnostic,
                        attempts=attempt,
                    )
                if not expects_result:
                    return CommandSendResult(
                        packet, self.destination, total_sent, last_now, attempts=attempt
                    )
                result = self._receive_correlated(packet)
                return CommandSendResult(
                    packet,
                    self.destination,
                    total_sent,
                    last_now,
                    result=result,
                    attempts=attempt,
                )
            except (socket.timeout, TimeoutError, BlockingIOError) as exc:
                self.stats.result_timeouts += 1
                self.stats.last_error = str(exc)
                if attempt >= max_attempts:
                    raise CommandClientError(
                        f"timed out waiting for correlated {packet.command_name} result "
                        f"after {max_attempts} attempt(s)"
                    ) from exc
                self.stats.retries += 1
        raise AssertionError("unreachable command retry state")

    def send(
        self,
        command: str | int,
        *,
        seq: int | None = None,
        arg0: int = 0,
        arg1: int = 0,
        arg2: int = 0,
    ) -> CommandSendResult:
        command_id = command_type(command)
        if (
            int(self.config.protocol_version) == int(_gen.COMMAND_VERSION_V2)
            and command_id != int(_gen.COMMAND_TYPES["PING"])
            and not self._peer_probe_sent
        ):
            self.ping()
        packet = self.build(command_id, seq=seq, arg0=arg0, arg1=arg1, arg2=arg2)
        return self.send_packet(packet)

    def ping(
        self,
        *,
        seq: int | None = None,
        arg0: int = 0,
        arg1: int = 0,
        arg2: int = 0,
    ) -> CommandSendResult:
        return self.send("PING", seq=seq, arg0=arg0, arg1=arg1, arg2=arg2)

    def clear_metrics(self, *, seq: int | None = None) -> CommandSendResult:
        return self.send("CLEAR_METRICS", seq=seq)

    def set_thr2(self, thr2: int, *, seq: int | None = None) -> CommandSendResult:
        lo, hi = split_thr2(thr2)
        return self.send("SET_THR2", seq=seq, arg0=lo, arg1=hi)

    def set_source_mode(self, source_mode: int, *, seq: int | None = None) -> CommandSendResult:
        validate_source_mode(source_mode)
        return self.send("SET_SOURCE_MODE", seq=seq, arg0=int(source_mode))

    def set_packet_enable(
        self, mask: int | str | Iterable[str], *, seq: int | None = None
    ) -> CommandSendResult:
        value = packet_enable_from_names(mask) if not isinstance(mask, int) else int(mask)
        validate_packet_enable(value)
        return self.send("SET_PACKET_ENABLE", seq=seq, arg0=value)

    def set_packet_profile(self, profile: str, *, seq: int | None = None) -> CommandSendResult:
        return self.set_packet_enable(packet_enable_profile(profile), seq=seq)

    def set_wave_decim(self, decim: int, *, seq: int | None = None) -> CommandSendResult:
        validate_wave_decim(decim)
        return self.send("SET_WAVE_DECIM", seq=seq, arg0=int(decim))

    def set_spec_shift(self, spec_shift: int, *, seq: int | None = None) -> CommandSendResult:
        validate_spec_shift(spec_shift)
        return self.send("SET_SPEC_SHIFT", seq=seq, arg0=int(spec_shift))

    def set_spec_mode(self, spec_mode: int, *, seq: int | None = None) -> CommandSendResult:
        validate_spec_mode(spec_mode)
        return self.send("SET_SPEC_MODE", seq=seq, arg0=int(spec_mode))

    def set_telemetry_enable(
        self, enabled: int | bool, *, seq: int | None = None
    ) -> CommandSendResult:
        validate_telemetry_enable(enabled)
        return self.send("SET_TELEMETRY_ENABLE", seq=seq, arg0=int(enabled))

    def configure_ddr_ring(self, *, seq: int | None = None) -> CommandSendResult:
        return self.send("CONFIGURE_DDR_RING", seq=seq)

    def reset_transport(self, *, seq: int | None = None) -> CommandSendResult:
        return self.send("RESET_TRANSPORT", seq=seq)

    def clear_counters(self, *, seq: int | None = None) -> CommandSendResult:
        return self.send("CLEAR_COUNTERS", seq=seq)

    def start_bram_replay(self, *, seq: int | None = None) -> CommandSendResult:
        return self.send("START_BRAM_REPLAY", seq=seq)

    def read_status_version(self, *, seq: int | None = None) -> CommandSendResult:
        sent = self.send("READ_STATUS_VERSION", seq=seq)
        if (
            not sent.dry_run
            and sent.result is not None
            and sent.result.disposition != int(_gen.COMMAND_DISPOSITIONS["NOOP"])
        ):
            raise CommandClientError("READ_STATUS_VERSION must return a NOOP disposition")
        return sent


class DryRunCommandClient(CommandClient):
    """Validate and record exact requests without opening a socket."""

    def __init__(self, config: CommandClientConfig | None = None) -> None:
        super().__init__(config)
        self.sent_packets: list[CommandPacket] = []

    def open(self) -> None:
        return

    def close(self) -> None:
        return

    def send_packet(
        self, packet: CommandPacket, *, _skip_probe: bool = False
    ) -> CommandSendResult:
        data = packet.to_bytes()
        if not _skip_probe:
            self._ensure_peer_probe(packet)
        self.sent_packets.append(packet)
        if packet.cmd_type == int(_gen.COMMAND_TYPES["PING"]):
            self.stats.session_pings += 1
            if packet.version == int(_gen.COMMAND_VERSION_V2):
                self._peer_probe_sent = True
        now = time.time_ns()
        self.stats.commands_sent += 1
        self.stats.bytes_sent += len(data)
        self.stats.last_seq = packet.seq
        self.stats.last_cmd_type = packet.cmd_type
        self.stats.last_send_time_ns = now
        self.stats.last_error = None
        return CommandSendResult(
            packet, self.destination, len(data), now, attempts=1, dry_run=True
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send a T-RECAP command to the HPS streamer.")
    parser.add_argument("command", choices=[name.lower() for name in _gen.COMMAND_TYPES])
    parser.add_argument("value", nargs="?", help="command value when required")
    parser.add_argument("--host", default=DEFAULT_HPS_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_COMMAND_PORT)
    parser.add_argument("--bind-host", default=None)
    parser.add_argument("--bind-port", type=int, default=DEFAULT_LOCAL_COMMAND_PORT)
    parser.add_argument("--protocol-version", type=int, choices=(1, 2), default=2)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--seq", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _int_value(text: str | None, command: str) -> int:
    if text is None:
        raise CommandClientError(f"{command} requires a value")
    return int(text, 0)


def command_from_args(args: argparse.Namespace) -> CommandSendResult:
    cls = DryRunCommandClient if args.dry_run else CommandClient
    client = cls(
        CommandClientConfig(
            host=str(args.host),
            port=int(args.port),
            bind_host=args.bind_host,
            bind_port=int(args.bind_port),
            protocol_version=int(args.protocol_version),
            retries=int(args.retries),
        )
    )
    command = str(args.command).upper()
    with client:
        if command == "SET_THR2":
            return client.set_thr2(_int_value(args.value, command), seq=args.seq)
        if command == "CLEAR_METRICS":
            return client.clear_metrics(seq=args.seq)
        if command == "SET_SOURCE_MODE":
            return client.set_source_mode(_int_value(args.value, command), seq=args.seq)
        if command == "SET_PACKET_ENABLE":
            value = args.value if args.value is not None else "status"
            if value.strip().lower().startswith("0x") or value.strip().isdigit():
                return client.set_packet_enable(int(value, 0), seq=args.seq)
            return client.set_packet_enable(value, seq=args.seq)
        if command == "SET_WAVE_DECIM":
            return client.set_wave_decim(_int_value(args.value, command), seq=args.seq)
        if command == "SET_SPEC_SHIFT":
            return client.set_spec_shift(_int_value(args.value, command), seq=args.seq)
        if command == "PING":
            return client.ping(seq=args.seq)
        if command == "SET_SPEC_MODE":
            return client.set_spec_mode(_int_value(args.value, command), seq=args.seq)
        if command == "SET_TELEMETRY_ENABLE":
            return client.set_telemetry_enable(_int_value(args.value, command), seq=args.seq)
        if command == "CONFIGURE_DDR_RING":
            return client.configure_ddr_ring(seq=args.seq)
        if command == "RESET_TRANSPORT":
            return client.reset_transport(seq=args.seq)
        if command == "CLEAR_COUNTERS":
            return client.clear_counters(seq=args.seq)
        if command == "START_BRAM_REPLAY":
            return client.start_bram_replay(seq=args.seq)
        if command == "READ_STATUS_VERSION":
            return client.read_status_version(seq=args.seq)
    raise CommandClientError(f"unsupported command: {command}")


def main(argv: Sequence[str] | None = None) -> int:
    result = command_from_args(build_arg_parser().parse_args(argv))
    suffix = ""
    if result.result is not None:
        suffix = (
            f" disposition={result.result.disposition_name}"
            f" reason={result.result.reject_reason_name}"
            f" status=0x{result.result.fpga_status:08x}"
            f" version=0x{result.result.csr_version:08x}"
        )
    print(
        f"{'dry-run ' if result.dry_run else ''}sent {result.command_name} "
        f"seq={result.packet.seq} bytes={result.bytes_sent} attempts={result.attempts} "
        f"to {result.destination[0]}:{result.destination[1]}{suffix}"
    )
    return 0


__all__ = [
    "CommandClient",
    "CommandClientConfig",
    "CommandClientError",
    "CommandClientStats",
    "CommandPacket",
    "CommandResult",
    "CommandSendResult",
    "DryRunCommandClient",
    "PACKET_ENABLE_ALLOWED_MASK",
    "PACKET_ENABLE_FULL_DEMO",
    "PACKET_ENABLE_METRICS",
    "PACKET_ENABLE_SPEC",
    "PACKET_ENABLE_STATUS",
    "PACKET_ENABLE_STATUS_ONLY",
    "PACKET_ENABLE_WAVE",
    "command_name",
    "command_type",
    "join_thr2",
    "packet_enable_from_names",
    "packet_enable_profile",
    "split_thr2",
    "validate_command_packet",
    "validate_packet_enable",
    "validate_source_mode",
    "validate_spec_mode",
    "validate_spec_shift",
    "validate_telemetry_enable",
    "validate_thr2",
    "validate_wave_decim",
]


if __name__ == "__main__":
    raise SystemExit(main())
