"""Revision G telemetry packet parser for the PC dashboard.

File class: [1] hand-written PC-side parser.

This module is deliberately limited to packet validation and payload decoding. It
must not implement FFT, IFFT, mask decisions, WOLA reconstruction, BRAM replay
signoff, or any HPS/FPGA control policy. All wire constants come from the
checked-in generated module ``sw/pc_dashboard/generated/trecap_packet.py``.
"""

from __future__ import annotations

import importlib.util
import io
import struct
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, Iterable, Iterator, Mapping, Sequence

CAPTURE_MAGIC = b"TRCPUDP1"
CAPTURE_RECORD_STRUCT = struct.Struct("<QHHI")
_INT16_TRIPLE_STRUCT = struct.Struct("<hhh")


class PacketParserError(ValueError):
    """Raised when a telemetry datagram violates the generated packet contract."""


def _load_generated_packet() -> ModuleType:
    """Load the generated packet constants without requiring a global install.

    The dashboard is normally run from ``sw/pc_dashboard`` with ``generated`` as a
    sibling directory. Editable installs can import ``generated.trecap_packet`` as
    a namespace package. Direct script execution uses the path fallback.
    """

    try:
        from generated import trecap_packet as generated_packet  # type: ignore

        return generated_packet
    except Exception:
        pass

    this_file = Path(__file__).resolve()
    candidates = [
        this_file.parents[1] / "generated" / "trecap_packet.py",
        this_file.parents[2] / "sw" / "pc_dashboard" / "generated" / "trecap_packet.py",
    ]
    for generated_path in candidates:
        if generated_path.is_file():
            spec = importlib.util.spec_from_file_location(
                "trecap_dashboard_generated_packet", generated_path
            )
            if spec is None or spec.loader is None:
                break
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise PacketParserError(
        "could not locate generated packet constants at "
        "sw/pc_dashboard/generated/trecap_packet.py; run `make gen-headers`"
    )


_gen = _load_generated_packet()


def _mask_from_bits(pair: Sequence[int]) -> int:
    lo = int(pair[0])
    hi = int(pair[1])
    return ((1 << (hi - lo + 1)) - 1) << lo


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PacketParserError(message)


def _u16_array(payload: bytes, offset: int, count: int) -> tuple[int, ...]:
    end = offset + 2 * count
    _require(end <= len(payload), "payload too short for uint16 array")
    return struct.unpack_from("<" + "H" * count, payload, offset)


def _u8_array(payload: bytes, offset: int, count: int) -> tuple[int, ...]:
    end = offset + count
    _require(end <= len(payload), "payload too short for uint8 array")
    return tuple(payload[offset:end])


@dataclass(frozen=True, slots=True)
class PacketFlags:
    """Decoded common telemetry-header flag bits."""

    raw: int
    payload_truncated: bool
    payload_scaled: bool
    aggregate_metrics: bool
    per_frame_metrics: bool
    crc_enabled: bool
    status_diagnostic: bool
    reserved: int

    @classmethod
    def from_raw(cls, raw: int) -> "PacketFlags":
        bits: Mapping[str, Sequence[int]] = _gen.COMMON_FLAG_BITS
        masks = {name: _mask_from_bits(pair) for name, pair in bits.items()}
        return cls(
            raw=int(raw),
            payload_truncated=bool(raw & masks.get("payload_truncated", 0x0001)),
            payload_scaled=bool(raw & masks.get("payload_scaled", 0x0002)),
            aggregate_metrics=bool(raw & masks.get("aggregate_metrics", 0x0004)),
            per_frame_metrics=bool(raw & masks.get("per_frame_metrics", 0x0008)),
            crc_enabled=bool(raw & masks.get("crc_enabled", 0x0010)),
            status_diagnostic=bool(raw & masks.get("status_diagnostic", 0x0020)),
            reserved=int(raw & masks.get("reserved_15_6", 0xFFC0)),
        )

    @property
    def metrics_class_count(self) -> int:
        return int(self.aggregate_metrics) + int(self.per_frame_metrics)


@dataclass(frozen=True, slots=True)
class TelemetryHeader:
    magic: int
    version: int
    header_bytes: int
    packet_type: int
    flags_raw: int
    seq: int
    timestamp: int
    payload_bytes: int
    header_crc: int
    packet_name: str
    flags: PacketFlags

    @property
    def wire_bytes(self) -> int:
        return int(self.header_bytes) + int(self.payload_bytes)

    @property
    def is_wrap(self) -> bool:
        return self.packet_name == "WRAP"

    @property
    def is_status_diagnostic(self) -> bool:
        return self.packet_name == "STATUS" and self.flags.status_diagnostic

    @property
    def participates_in_sequence(self) -> bool:
        return not self.is_wrap and not self.is_status_diagnostic


@dataclass(frozen=True, slots=True)
class WaveSample:
    sample_index: int
    xdel: int
    yout: int
    err: int


@dataclass(frozen=True, slots=True)
class WavePayload:
    sample_base: int
    nsamp: int
    channels: int
    stride: int
    samples: tuple[WaveSample, ...]


@dataclass(frozen=True, slots=True)
class Spec129Payload:
    frame_idx: int
    nbin: int
    spec_shift: int
    magnitudes: tuple[int, ...]
    mask_bits: tuple[bool, ...]
    raw_mask_bytes: bytes


@dataclass(frozen=True, slots=True)
class Spec64Payload:
    frame_idx: int
    nbin: int
    spec_shift: int
    magnitudes: tuple[int, ...]
    suppressed_count: tuple[int, ...]
    eligible_count: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MetricsPayload:
    frame_idx: int
    eligible_unique_bins: int
    eligible_suppressed_bins: int
    eligible_kept_mag2_lo: int
    eligible_total_mag2_lo: int
    sum_abs_err_lo: int
    sum_sq_err_lo: int
    max_abs_err: int
    overflow_flags: int

    @property
    def kept_energy_ratio(self) -> float | None:
        if self.eligible_total_mag2_lo == 0:
            return None
        return self.eligible_kept_mag2_lo / self.eligible_total_mag2_lo

    @property
    def suppressed_bin_ratio(self) -> float | None:
        if self.eligible_unique_bins == 0:
            return None
        return self.eligible_suppressed_bins / self.eligible_unique_bins


@dataclass(frozen=True, slots=True)
class StatusPayload:
    sample_count: int
    frame_count: int
    source_mode: int
    sample_rate: int
    packet_enable: int
    dma_drop_count: int
    udp_send_error_count: int
    malformed_record_count: int
    oversized_record_count: int
    command_reject_count: int
    sequence_gap_count: int
    overflow_flags: int
    thr2_lo: int
    thr2_hi: int
    packet_fifo_drop_count: int
    reserved: int

    @property
    def thr2(self) -> int:
        return (int(self.thr2_hi) << 32) | int(self.thr2_lo)


@dataclass(frozen=True, slots=True)
class WrapPayload:
    """Ring-control WRAP marker. It should not appear in normal UDP traffic."""


TelemetryPayload = (
    WavePayload | Spec129Payload | Spec64Payload | MetricsPayload | StatusPayload | WrapPayload
)


@dataclass(frozen=True, slots=True)
class ParsedPacket:
    header: TelemetryHeader
    payload: TelemetryPayload
    raw_payload: bytes
    raw_datagram: bytes

    @property
    def packet_name(self) -> str:
        return self.header.packet_name

    @property
    def seq(self) -> int:
        return self.header.seq

    @property
    def timestamp(self) -> int:
        return self.header.timestamp

    @property
    def participates_in_sequence(self) -> bool:
        return self.header.participates_in_sequence


def parse_header(datagram: bytes | bytearray | memoryview) -> TelemetryHeader:
    """Parse and minimally validate the 32-byte Revision G telemetry header."""

    data = bytes(datagram)
    header_bytes = int(_gen.TELEMETRY_HEADER_BYTES)
    _require(len(data) >= header_bytes, "datagram shorter than telemetry header")
    fields = _gen.TELEMETRY_HEADER_STRUCT.unpack_from(data, 0)
    magic, version, hbytes, packet_type, flags_raw, seq, timestamp, payload_bytes, header_crc = fields
    packet_name = _gen.PACKET_TYPE_NAMES.get(packet_type, "UNKNOWN")
    flags = PacketFlags.from_raw(flags_raw)
    return TelemetryHeader(
        magic=magic,
        version=version,
        header_bytes=hbytes,
        packet_type=packet_type,
        flags_raw=flags_raw,
        seq=seq,
        timestamp=timestamp,
        payload_bytes=payload_bytes,
        header_crc=header_crc,
        packet_name=packet_name,
        flags=flags,
    )


class TelemetryPacketParser:
    """Strict parser for one-record-per-UDP-datagram Revision G telemetry."""

    def __init__(
        self,
        *,
        allow_wrap: bool = False,
        enforce_udp_limit: bool = True,
        exact_length: bool = True,
    ) -> None:
        self.allow_wrap = bool(allow_wrap)
        self.enforce_udp_limit = bool(enforce_udp_limit)
        self.exact_length = bool(exact_length)

    def parse_datagram(self, datagram: bytes | bytearray | memoryview) -> ParsedPacket:
        data = bytes(datagram)
        header = parse_header(data)
        self._validate_header(header, data)
        payload_start = int(_gen.TELEMETRY_HEADER_BYTES)
        payload_end = payload_start + int(header.payload_bytes)
        payload = data[payload_start:payload_end]
        decoded = self._parse_payload(header, payload)
        return ParsedPacket(
            header=header,
            payload=decoded,
            raw_payload=payload,
            raw_datagram=data[:payload_end] if not self.exact_length else data,
        )

    def _validate_header(self, header: TelemetryHeader, data: bytes) -> None:
        _require(header.magic == int(_gen.TELEMETRY_MAGIC), f"bad telemetry magic 0x{header.magic:08x}")
        _require(
            header.version == int(_gen.TELEMETRY_HEADER_VERSION),
            f"unsupported telemetry header version {header.version}",
        )
        _require(
            header.header_bytes == int(_gen.TELEMETRY_HEADER_BYTES),
            f"bad header_bytes {header.header_bytes}",
        )
        _require(header.packet_name != "UNKNOWN", f"unknown packet type 0x{header.packet_type:04x}")
        _require(header.header_crc == 0, f"nonzero header_crc 0x{header.header_crc:08x}")
        _require(not header.flags.crc_enabled, "crc_enabled flag is reserved zero in Revision G")
        _require(header.flags.reserved == 0, f"reserved flags set 0x{header.flags.reserved:04x}")
        _require(
            not header.flags.status_diagnostic or header.packet_name == "STATUS",
            "status_diagnostic flag is legal only on STATUS packets",
        )
        if header.packet_name in {"PEAKS", "DEBUG"}:
            raise PacketParserError(f"{header.packet_name} is reserved-disabled in Revision G")
        if header.packet_name == "WRAP" and not self.allow_wrap:
            raise PacketParserError("WRAP is a DDR ring-control record and is not forwarded over UDP")

        wire_bytes = header.wire_bytes
        if self.exact_length:
            _require(len(data) == wire_bytes, f"datagram length {len(data)} != header+payload {wire_bytes}")
        else:
            _require(len(data) >= wire_bytes, f"record length {len(data)} < header+payload {wire_bytes}")
        if self.enforce_udp_limit:
            _require(
                wire_bytes <= int(_gen.UDP_NO_FRAGMENT_PAYLOAD_MAX_BYTES),
                f"datagram length {wire_bytes} exceeds no-fragment bound "
                f"{int(_gen.UDP_NO_FRAGMENT_PAYLOAD_MAX_BYTES)}",
            )

    def _parse_payload(self, header: TelemetryHeader, payload: bytes) -> TelemetryPayload:
        rule = _gen.PAYLOAD_RULES[header.packet_name]
        if rule.get("kind") == "exact":
            expected = int(rule["bytes"])
            _require(header.payload_bytes == expected, f"{header.packet_name} payload_bytes {header.payload_bytes} != {expected}")
        elif rule.get("kind") == "variable" and header.packet_name == "WAVE":
            min_bytes = int(rule["min_bytes"])
            max_bytes = int(rule["max_bytes"])
            _require(min_bytes <= header.payload_bytes <= max_bytes, "WAVE payload_bytes outside legal range")
        else:
            raise PacketParserError(f"unsupported payload rule for {header.packet_name}")

        if header.packet_name == "WAVE":
            return self._parse_wave(header, payload)
        if header.packet_name == "SPEC129":
            return self._parse_spec129(header, payload)
        if header.packet_name == "SPEC64":
            return self._parse_spec64(header, payload)
        if header.packet_name == "METRICS":
            return self._parse_metrics(header, payload)
        if header.packet_name == "STATUS":
            return self._parse_status(header, payload)
        if header.packet_name == "WRAP":
            _require(header.payload_bytes == 0 and payload == b"", "WRAP payload must be empty")
            return WrapPayload()
        raise PacketParserError(f"no decoder for packet type {header.packet_name}")

    def _parse_wave(self, header: TelemetryHeader, payload: bytes) -> WavePayload:
        off = _gen.PAYLOAD_OFFSETS["WAVE"]
        sample_base = struct.unpack_from("<Q", payload, off["sample_base"])[0]
        nsamp = struct.unpack_from("<H", payload, off["nsamp"])[0]
        channels = struct.unpack_from("<H", payload, off["channels"])[0]
        stride = struct.unpack_from("<H", payload, off["stride"])[0]
        reserved = struct.unpack_from("<H", payload, off["reserved"])[0]
        expected = int(_gen.expected_payload_bytes("WAVE", nsamp=nsamp))
        _require(header.payload_bytes == expected, f"WAVE payload_bytes {header.payload_bytes} != {expected}")
        _require(sample_base == header.timestamp, "WAVE timestamp must equal sample_base")
        _require(channels == 3, f"WAVE channels {channels} != 3")
        _require(stride >= 1, "WAVE stride must be nonzero")
        _require(reserved == 0, f"WAVE reserved field must be zero, got 0x{reserved:04x}")
        samples: list[WaveSample] = []
        sample_offset = int(off["sample"])
        for idx in range(nsamp):
            xdel, yout, err = _INT16_TRIPLE_STRUCT.unpack_from(payload, sample_offset + 6 * idx)
            samples.append(
                WaveSample(
                    sample_index=int(sample_base) + int(idx) * int(stride),
                    xdel=int(xdel),
                    yout=int(yout),
                    err=int(err),
                )
            )
        return WavePayload(sample_base, nsamp, channels, stride, tuple(samples))

    def _parse_spec129(self, header: TelemetryHeader, payload: bytes) -> Spec129Payload:
        off = _gen.PAYLOAD_OFFSETS["SPEC129"]
        frame_idx = struct.unpack_from("<Q", payload, off["frame_idx"])[0]
        nbin = struct.unpack_from("<H", payload, off["nbin"])[0]
        spec_shift = struct.unpack_from("<H", payload, off["spec_shift"])[0]
        _require(frame_idx == header.timestamp, "SPEC129 timestamp must equal frame_idx")
        _require(nbin == 129, f"SPEC129 nbin {nbin} != 129")
        _require(0 <= spec_shift <= 55, f"SPEC129 spec_shift {spec_shift} outside 0..55")
        magnitudes = _u16_array(payload, int(off["spec129"]), 129)
        mask_bytes = bytes(_u8_array(payload, int(off["mask_bits"]), 17))
        bits = tuple(bool((mask_bytes[k // 8] >> (k % 8)) & 1) for k in range(129))
        unused_final_bits = int(mask_bytes[-1]) & 0xFE
        _require(unused_final_bits == 0, "SPEC129 unused final mask bits must be zero")
        return Spec129Payload(frame_idx, nbin, spec_shift, magnitudes, bits, mask_bytes)

    def _parse_spec64(self, header: TelemetryHeader, payload: bytes) -> Spec64Payload:
        off = _gen.PAYLOAD_OFFSETS["SPEC64"]
        frame_idx = struct.unpack_from("<Q", payload, off["frame_idx"])[0]
        nbin = struct.unpack_from("<H", payload, off["nbin"])[0]
        spec_shift = struct.unpack_from("<H", payload, off["spec_shift"])[0]
        _require(frame_idx == header.timestamp, "SPEC64 timestamp must equal frame_idx")
        _require(nbin == 64, f"SPEC64 nbin {nbin} != 64")
        _require(0 <= spec_shift <= 55, f"SPEC64 spec_shift {spec_shift} outside 0..55")
        magnitudes = _u16_array(payload, int(off["spec64"]), 64)
        suppressed = _u8_array(payload, int(off["suppressed_count"]), 64)
        eligible = _u8_array(payload, int(off["eligible_count"]), 64)
        return Spec64Payload(frame_idx, nbin, spec_shift, magnitudes, suppressed, eligible)

    def _parse_metrics(self, header: TelemetryHeader, payload: bytes) -> MetricsPayload:
        _require(
            header.flags.metrics_class_count == 1,
            "METRICS must set exactly one metrics class flag",
        )
        _require(not header.flags.payload_scaled, "METRICS payload_scaled flag must be zero")
        fields = struct.unpack_from("<QIIQQQQII", payload, 0)
        return MetricsPayload(*[int(value) for value in fields])

    def _parse_status(self, header: TelemetryHeader, payload: bytes) -> StatusPayload:
        fields = struct.unpack_from("<QQIIIIIIIIIIIIII", payload, 0)
        decoded = StatusPayload(*[int(value) for value in fields])
        _require(decoded.reserved == 0, f"STATUS reserved field must be zero, got 0x{decoded.reserved:08x}")
        if not header.flags.status_diagnostic:
            _require(header.timestamp == decoded.sample_count, "STATUS timestamp must equal sample_count")
        else:
            _require(header.seq == 0, "diagnostic STATUS must use seq=0")
        return decoded


def parse_datagram(datagram: bytes | bytearray | memoryview, **kwargs: object) -> ParsedPacket:
    """Parse one telemetry datagram with the default strict parser."""

    return TelemetryPacketParser(**kwargs).parse_datagram(datagram)


def iter_capture_datagrams(source: bytes | bytearray | memoryview | BinaryIO) -> Iterator[tuple[int, str, int, bytes]]:
    """Yield datagrams from ``smoke_udp_recv.py`` framed capture files.

    Yields ``(recv_time_ns, source_host, source_port, datagram)``. The framing is
    intentionally kept here so the dashboard can replay bring-up captures without
    depending on the bring-up scripts as a library.
    """

    if isinstance(source, (bytes, bytearray, memoryview)):
        stream: BinaryIO = io.BytesIO(bytes(source))
    else:
        stream = source

    magic = stream.read(len(CAPTURE_MAGIC))
    _require(magic == CAPTURE_MAGIC, "capture magic mismatch; expected TRCPUDP1")
    while True:
        record_header = stream.read(CAPTURE_RECORD_STRUCT.size)
        if not record_header:
            return
        _require(
            len(record_header) == CAPTURE_RECORD_STRUCT.size,
            "truncated capture record header",
        )
        recv_time_ns, src_port, addr_len, datagram_len = CAPTURE_RECORD_STRUCT.unpack(record_header)
        addr_raw = stream.read(addr_len)
        datagram = stream.read(datagram_len)
        _require(len(addr_raw) == addr_len, "truncated capture address")
        _require(len(datagram) == datagram_len, "truncated capture datagram")
        source_host = addr_raw.decode("utf-8", errors="replace")
        yield int(recv_time_ns), source_host, int(src_port), datagram


def parse_capture(source: bytes | bytearray | memoryview | BinaryIO) -> tuple[ParsedPacket, ...]:
    """Parse all datagrams from a framed capture using the default strict parser."""

    parser = TelemetryPacketParser()
    return tuple(parser.parse_datagram(datagram) for _, _, _, datagram in iter_capture_datagrams(source))


def sequence_gaps(packets: Iterable[ParsedPacket]) -> tuple[tuple[int, int, int], ...]:
    """Return modulo-2^32 sequence gaps as ``(prev_seq, curr_seq, missing)``.

    WRAP records and diagnostic STATUS packets are excluded from sequence-gap
    logic, matching the telemetry contract used by the HPS streamer and dashboard.
    """

    gaps: list[tuple[int, int, int]] = []
    previous: int | None = None
    for packet in packets:
        if not packet.participates_in_sequence:
            continue
        current = int(packet.seq) & 0xFFFFFFFF
        if previous is not None:
            expected = (previous + 1) & 0xFFFFFFFF
            if current != expected:
                missing = (current - expected) & 0xFFFFFFFF
                gaps.append((previous, current, missing))
        previous = current
    return tuple(gaps)
