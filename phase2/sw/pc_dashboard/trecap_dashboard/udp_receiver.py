"""UDP receive utilities for T-RECAP Phase 2 PC telemetry.

File class: [1] hand-written PC-side transport helper.

This module terminates the PC-side UDP telemetry stream produced by the HPS
streamer. It deliberately stops at transport receive, source filtering, optional
capture writing, and packet-parser handoff. It must not implement FFT, IFFT,
mask decisions, WOLA reconstruction, BRAM replay signoff, or HPS/FPGA control
policy.
"""

from __future__ import annotations

import queue
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Callable, Iterator

from .packet_parser import (
    CAPTURE_MAGIC,
    CAPTURE_RECORD_STRUCT,
    PacketParserError,
    ParsedPacket,
    TelemetryPacketParser,
)

DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_TELEMETRY_PORT = 5005
DEFAULT_SOCKET_TIMEOUT_S = 0.1
DEFAULT_RX_BUFFER_BYTES = 65535
DEFAULT_CAPTURE_FLUSH_EVERY = 32


@dataclass(frozen=True, slots=True)
class UdpEndpoint:
    """IPv4/IPv6 UDP endpoint description used for source filtering."""

    host: str
    port: int | None = None

    @classmethod
    def parse(cls, text: str) -> "UdpEndpoint":
        """Parse ``HOST`` or ``HOST:PORT`` into an endpoint.

        Bracketed IPv6 notation is intentionally not required for the current
        direct-link DE1-SoC bring-up profile. IPv6 socket support still works if
        the caller passes host and port explicitly through the dataclass.
        """

        stripped = text.strip()
        if not stripped:
            raise ValueError("empty UDP endpoint")
        if stripped.count(":") == 1:
            host, port_text = stripped.rsplit(":", 1)
            if port_text:
                return cls(host=host, port=_parse_port(port_text))
        return cls(host=stripped, port=None)

    def matches(self, host: str, port: int) -> bool:
        if self.host and host != self.host:
            return False
        if self.port is not None and int(self.port) != int(port):
            return False
        return True


@dataclass(frozen=True, slots=True)
class UdpReceiverConfig:
    """Runtime configuration for the PC-side telemetry UDP receiver."""

    bind_host: str = DEFAULT_BIND_HOST
    bind_port: int = DEFAULT_TELEMETRY_PORT
    expected_source: UdpEndpoint | None = None
    socket_timeout_s: float = DEFAULT_SOCKET_TIMEOUT_S
    rx_buffer_bytes: int = DEFAULT_RX_BUFFER_BYTES
    socket_rcvbuf_bytes: int | None = None
    allow_reuse_addr: bool = True
    allow_wrap: bool = False
    enforce_udp_limit: bool = True
    capture_path: Path | None = None
    capture_append: bool = False
    capture_flush_every: int = DEFAULT_CAPTURE_FLUSH_EVERY

    def validate(self) -> None:
        _validate_port(self.bind_port, "bind_port")
        if self.expected_source is not None and self.expected_source.port is not None:
            _validate_port(self.expected_source.port, "expected_source.port")
        if self.socket_timeout_s < 0.0:
            raise ValueError("socket_timeout_s must be >= 0")
        if self.rx_buffer_bytes < 2048:
            raise ValueError("rx_buffer_bytes must be at least 2048 bytes")
        if self.socket_rcvbuf_bytes is not None and self.socket_rcvbuf_bytes < self.rx_buffer_bytes:
            raise ValueError("socket_rcvbuf_bytes must be >= rx_buffer_bytes")
        if self.capture_flush_every < 1:
            raise ValueError("capture_flush_every must be >= 1")


@dataclass(frozen=True, slots=True)
class ReceivedDatagram:
    """One accepted UDP datagram before telemetry parsing."""

    recv_time_ns: int
    source_host: str
    source_port: int
    data: bytes
    truncated: bool = False

    @property
    def byte_count(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class ReceivedPacket:
    """One accepted and parsed telemetry packet."""

    datagram: ReceivedDatagram
    packet: ParsedPacket


@dataclass(frozen=True, slots=True)
class ReceiverEvent:
    """Receive-loop event.

    ``packet`` is set for successfully parsed telemetry. ``error`` is set for a
    datagram that was accepted at the UDP/source-filter layer but failed packet
    validation. Source-filtered datagrams do not produce events.
    """

    datagram: ReceivedDatagram
    packet: ParsedPacket | None = None
    error: Exception | None = None
    error_kind: str | None = None

    @property
    def ok(self) -> bool:
        return self.packet is not None and self.error is None


@dataclass(slots=True)
class UdpReceiverStats:
    """Mutable counters for PC-side UDP receive bring-up."""

    datagrams_seen: int = 0
    datagrams_accepted: int = 0
    datagrams_source_rejected: int = 0
    datagrams_truncated_or_oversized: int = 0
    datagrams_socket_truncated: int = 0
    bytes_accepted: int = 0
    packets_parsed: int = 0
    payload_truncated_packet_count: int = 0
    parse_errors: int = 0
    socket_timeouts: int = 0
    socket_errors: int = 0
    capture_write_errors: int = 0
    sequence_gap_count: int = 0
    missing_sequence_count: int = 0
    duplicate_sequence_count: int = 0
    reordered_sequence_count: int = 0
    last_sequence: int | None = None
    first_recv_time_ns: int | None = None
    last_recv_time_ns: int | None = None
    first_packet_time_ns: int | None = None
    last_packet_time_ns: int | None = None
    last_error: str | None = None
    last_error_kind: str | None = None
    packets_by_type: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.datagrams_seen = 0
        self.datagrams_accepted = 0
        self.datagrams_source_rejected = 0
        self.datagrams_truncated_or_oversized = 0
        self.datagrams_socket_truncated = 0
        self.bytes_accepted = 0
        self.packets_parsed = 0
        self.payload_truncated_packet_count = 0
        self.parse_errors = 0
        self.socket_timeouts = 0
        self.socket_errors = 0
        self.capture_write_errors = 0
        self.sequence_gap_count = 0
        self.missing_sequence_count = 0
        self.duplicate_sequence_count = 0
        self.reordered_sequence_count = 0
        self.last_sequence = None
        self.first_recv_time_ns = None
        self.last_recv_time_ns = None
        self.first_packet_time_ns = None
        self.last_packet_time_ns = None
        self.last_error = None
        self.last_error_kind = None
        self.packets_by_type.clear()

    @property
    def socket_truncation_count(self) -> int:
        """Compatibility/readability alias for kernel-reported UDP truncation."""

        return int(self.datagrams_socket_truncated)

    @property
    def payload_truncated_packets(self) -> int:
        return int(self.payload_truncated_packet_count)

    def note_parsed_packet(
        self,
        packet: ParsedPacket,
        *,
        recv_time_ns: int | None = None,
    ) -> None:
        name = packet.packet_name
        self.packets_parsed += 1
        self.packets_by_type[name] = self.packets_by_type.get(name, 0) + 1
        packet_time_ns = int(time.time_ns() if recv_time_ns is None else recv_time_ns)
        if self.first_packet_time_ns is None:
            self.first_packet_time_ns = packet_time_ns
        self.last_packet_time_ns = packet_time_ns
        if packet.header.flags.payload_truncated:
            self.payload_truncated_packet_count += 1
        if not packet.participates_in_sequence:
            return
        current = int(packet.seq) & 0xFFFFFFFF
        previous = self.last_sequence
        if previous is None:
            self.last_sequence = current
            return

        delta = (current - int(previous)) & 0xFFFFFFFF
        if delta == 0:
            self.duplicate_sequence_count += 1
            return
        if delta < 0x80000000:
            if delta > 1:
                self.sequence_gap_count += 1
                self.missing_sequence_count += int(delta - 1)
            self.last_sequence = current
            return

        # Older/reordered and exact-half-range ambiguous serials never advance
        # the RFC1982 high-water mark and never become a multi-billion gap.
        self.reordered_sequence_count += 1


class FramedCaptureWriter:
    """Writer for ``smoke_udp_recv.py`` compatible framed capture files."""

    def __init__(
        self,
        path: str | Path,
        *,
        append: bool = False,
        flush_every: int = DEFAULT_CAPTURE_FLUSH_EVERY,
    ) -> None:
        self.path = Path(path)
        self.append = bool(append)
        self.flush_every = int(flush_every)
        self._stream: BinaryIO | None = None
        self._records_since_flush = 0

    def __enter__(self) -> "FramedCaptureWriter":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def open(self) -> None:
        if self._stream is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.append and self.path.exists():
            stream = self.path.open("r+b")
            try:
                _validate_existing_capture(stream, self.path)
                stream.seek(0, 2)
            except BaseException:
                stream.close()
                raise
        else:
            stream = self.path.open("wb")
            stream.write(CAPTURE_MAGIC)
        self._stream = stream
        self._records_since_flush = 0

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.flush()
            stream.close()

    def write(self, datagram: ReceivedDatagram) -> None:
        if self._stream is None:
            self.open()
        assert self._stream is not None
        host_raw = datagram.source_host.encode("utf-8")
        if len(host_raw) > 0xFFFF:
            raise ValueError("source host string too long for capture framing")
        if len(datagram.data) > 0xFFFFFFFF:
            raise ValueError("datagram too large for capture framing")
        self._stream.write(
            CAPTURE_RECORD_STRUCT.pack(
                int(datagram.recv_time_ns),
                int(datagram.source_port),
                len(host_raw),
                len(datagram.data),
            )
        )
        self._stream.write(host_raw)
        self._stream.write(datagram.data)
        self._records_since_flush += 1
        if self._records_since_flush >= self.flush_every:
            self._stream.flush()
            self._records_since_flush = 0


class TelemetryUdpReceiver:
    """Synchronous UDP receiver for one-record-per-datagram telemetry."""

    def __init__(
        self,
        config: UdpReceiverConfig | None = None,
        *,
        parser: TelemetryPacketParser | None = None,
    ) -> None:
        self.config = config or UdpReceiverConfig()
        self.config.validate()
        self.parser = parser or TelemetryPacketParser(
            allow_wrap=self.config.allow_wrap,
            enforce_udp_limit=self.config.enforce_udp_limit,
            exact_length=True,
        )
        self.stats = UdpReceiverStats()
        self._socket: socket.socket | None = None
        self._capture: FramedCaptureWriter | None = None

    def __enter__(self) -> "TelemetryUdpReceiver":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._socket is not None

    def open(self) -> None:
        if self._socket is not None:
            return
        family = _address_family_for_host(self.config.bind_host)
        sock = socket.socket(family, socket.SOCK_DGRAM)
        try:
            if self.config.allow_reuse_addr:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if self.config.socket_rcvbuf_bytes is not None:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, int(self.config.socket_rcvbuf_bytes))
            sock.settimeout(float(self.config.socket_timeout_s))
            sock.bind((self.config.bind_host, int(self.config.bind_port)))
            self._socket = sock
            if self.config.capture_path is not None:
                self._capture = FramedCaptureWriter(
                    self.config.capture_path,
                    append=self.config.capture_append,
                    flush_every=self.config.capture_flush_every,
                )
                self._capture.open()
        except Exception:
            sock.close()
            self.close()
            raise

    def close(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is not None:
            capture.close()
        sock = self._socket
        self._socket = None
        if sock is not None:
            sock.close()

    def fileno(self) -> int:
        if self._socket is None:
            raise RuntimeError("UDP receiver is not open")
        return int(self._socket.fileno())

    def receive_datagram(self) -> ReceivedDatagram | None:
        """Receive one accepted datagram, or return ``None`` on timeout."""

        if self._socket is None:
            raise RuntimeError("UDP receiver is not open")
        try:
            data, addr, truncated = self._receive_socket_datagram()
        except socket.timeout:
            self.stats.socket_timeouts += 1
            return None
        except BlockingIOError:
            self.stats.socket_timeouts += 1
            return None
        except OSError as exc:
            self.stats.socket_errors += 1
            self.stats.last_error = str(exc)
            raise

        recv_time_ns = time.time_ns()
        source_host = str(addr[0])
        source_port = int(addr[1])
        self.stats.datagrams_seen += 1
        if self.stats.first_recv_time_ns is None:
            self.stats.first_recv_time_ns = recv_time_ns
        self.stats.last_recv_time_ns = recv_time_ns
        if truncated:
            self.stats.datagrams_socket_truncated += 1
        if truncated or len(data) >= int(self.config.rx_buffer_bytes):
            self.stats.datagrams_truncated_or_oversized += 1
        if self.config.expected_source is not None and not self.config.expected_source.matches(
            source_host, source_port
        ):
            self.stats.datagrams_source_rejected += 1
            return None

        datagram = ReceivedDatagram(
            recv_time_ns=recv_time_ns,
            source_host=source_host,
            source_port=source_port,
            data=bytes(data),
            truncated=bool(truncated),
        )
        self.stats.datagrams_accepted += 1
        self.stats.bytes_accepted += len(datagram.data)
        if self._capture is not None and not datagram.truncated:
            try:
                self._capture.write(datagram)
            except OSError as exc:
                self.stats.capture_write_errors += 1
                self.stats.last_error = str(exc)
                raise
        return datagram

    def _receive_socket_datagram(self) -> tuple[bytes, tuple[object, ...], bool]:
        """Receive one UDP datagram and preserve the kernel truncation signal.

        Unix ``recvmsg`` reports ``MSG_TRUNC`` reliably. Platforms without
        ``recvmsg`` use a conservative ``recvfrom`` fallback; the configured
        receive buffer is required to exceed the legal Revision-G UDP bound, so
        an exact-buffer-length fallback datagram is invalid and safely treated
        as potentially truncated.
        """

        assert self._socket is not None
        sock = self._socket
        recvmsg = getattr(sock, "recvmsg", None)
        msg_trunc = int(getattr(socket, "MSG_TRUNC", 0))
        if callable(recvmsg) and msg_trunc != 0:
            data, _ancillary, msg_flags, addr = recvmsg(
                int(self.config.rx_buffer_bytes),
                0,
            )
            return bytes(data), tuple(addr), bool(int(msg_flags) & msg_trunc)

        data, addr = sock.recvfrom(int(self.config.rx_buffer_bytes))
        possibly_truncated = len(data) >= int(self.config.rx_buffer_bytes)
        return bytes(data), tuple(addr), possibly_truncated

    def receive_event(self) -> ReceiverEvent | None:
        """Receive and parse one accepted datagram.

        Timeout or source-filter rejection returns ``None``. Parser errors are
        returned as events so the dashboard can count/report bad telemetry
        without killing its background receive thread.
        """

        datagram = self.receive_datagram()
        if datagram is None:
            return None
        if datagram.truncated:
            error = PacketParserError("UDP datagram was truncated by the receive socket")
            self.stats.last_error = str(error)
            self.stats.last_error_kind = "socket_truncated"
            return ReceiverEvent(
                datagram=datagram,
                error=error,
                error_kind="socket_truncated",
            )
        try:
            packet = self.parser.parse_datagram(datagram.data)
        except PacketParserError as exc:
            self.stats.parse_errors += 1
            self.stats.last_error = str(exc)
            self.stats.last_error_kind = "parse_error"
            return ReceiverEvent(datagram=datagram, error=exc, error_kind="parse_error")
        self.stats.note_parsed_packet(packet, recv_time_ns=datagram.recv_time_ns)
        return ReceiverEvent(datagram=datagram, packet=packet)

    def iter_events(
        self,
        *,
        max_events: int | None = None,
        stop_event: threading.Event | None = None,
    ) -> Iterator[ReceiverEvent]:
        count = 0
        while stop_event is None or not stop_event.is_set():
            event = self.receive_event()
            if event is None:
                continue
            yield event
            count += 1
            if max_events is not None and count >= max_events:
                return

    def iter_packets(
        self,
        *,
        max_packets: int | None = None,
        stop_event: threading.Event | None = None,
    ) -> Iterator[ReceivedPacket]:
        count = 0
        for event in self.iter_events(stop_event=stop_event):
            if not event.ok or event.packet is None:
                continue
            yield ReceivedPacket(datagram=event.datagram, packet=event.packet)
            count += 1
            if max_packets is not None and count >= max_packets:
                return


class BackgroundTelemetryReceiver:
    """Threaded receiver that pushes parsed/errored events into a queue.

    The GUI should consume events from ``events`` and update its buffers on the
    UI cadence. This class still performs no plotting and no signal-processing.
    """

    def __init__(
        self,
        receiver: TelemetryUdpReceiver,
        *,
        queue_maxsize: int = 4096,
        on_event: Callable[[ReceiverEvent], None] | None = None,
    ) -> None:
        if queue_maxsize < 1:
            raise ValueError("queue_maxsize must be >= 1")
        self.receiver = receiver
        self.events: queue.Queue[ReceiverEvent] = queue.Queue(maxsize=int(queue_maxsize))
        self.on_event = on_event
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="trecap-udp-receiver", daemon=True)
        self.queue_drop_count = 0
        self.thread_error: BaseException | None = None

    def start(self) -> None:
        self.receiver.open()
        self.thread.start()

    def stop(self, *, join_timeout_s: float = 2.0) -> None:
        self.stop_event.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=join_timeout_s)
        self.receiver.close()

    def _run(self) -> None:
        try:
            for event in self.receiver.iter_events(stop_event=self.stop_event):
                if self.on_event is not None:
                    self.on_event(event)
                try:
                    self.events.put_nowait(event)
                except queue.Full:
                    self.queue_drop_count += 1
        except BaseException as exc:  # thread boundary; caller inspects thread_error
            self.thread_error = exc
            self.stop_event.set()


def _parse_port(text: str) -> int:
    try:
        port = int(text, 10)
    except ValueError as exc:
        raise ValueError(f"invalid UDP port {text!r}") from exc
    _validate_port(port, "port")
    return port


def _validate_existing_capture(stream: BinaryIO, path: Path) -> None:
    """Fail closed unless *stream* ends on a complete framed-record boundary."""

    stream.seek(0)
    magic = stream.read(len(CAPTURE_MAGIC))
    if magic != CAPTURE_MAGIC:
        raise ValueError(f"capture file {path} has bad magic")
    stream.seek(0, 2)
    file_size = int(stream.tell())
    stream.seek(len(CAPTURE_MAGIC))
    record_index = 0
    while int(stream.tell()) < file_size:
        remaining = file_size - int(stream.tell())
        if remaining < CAPTURE_RECORD_STRUCT.size:
            raise ValueError(
                f"capture file {path} has truncated record header at record {record_index}"
            )
        record_header = stream.read(CAPTURE_RECORD_STRUCT.size)
        _recv_time_ns, _src_port, addr_len, datagram_len = CAPTURE_RECORD_STRUCT.unpack(
            record_header
        )
        record_bytes = int(addr_len) + int(datagram_len)
        remaining = file_size - int(stream.tell())
        if record_bytes > remaining:
            raise ValueError(
                f"capture file {path} has truncated record payload at record {record_index}"
            )
        stream.seek(record_bytes, 1)
        record_index += 1


def _validate_port(port: int, name: str) -> None:
    if not (1 <= int(port) <= 65535):
        raise ValueError(f"{name} must be in range 1..65535")


def _address_family_for_host(host: str) -> socket.AddressFamily:
    if ":" in host and host not in {"", "0.0.0.0"}:
        return socket.AF_INET6
    return socket.AF_INET


# Stable aliases retained for launcher/dashboard code written against earlier
# class names. They do not duplicate implementation.
UdpReceiver = TelemetryUdpReceiver
BackgroundUdpReceiver = BackgroundTelemetryReceiver
TelemetryReceiverConfig = UdpReceiverConfig
