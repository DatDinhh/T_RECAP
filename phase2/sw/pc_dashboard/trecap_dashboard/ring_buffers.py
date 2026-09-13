"""In-memory dashboard ring buffers for T-RECAP Phase 2 telemetry.

File class: [1] hand-written PC-side buffering helper.

The buffers in this module hold already decoded telemetry packets for plotting
and status panels. They must not implement FFT, IFFT, mask decisions, WOLA
reconstruction, BRAM replay signoff, HPS control policy, or any replacement for
the reference model.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Generic, Iterable, Iterator, TypeVar

from .packet_parser import (
    MetricsPayload,
    ParsedPacket,
    Spec64Payload,
    Spec129Payload,
    StatusPayload,
    WavePayload,
    WaveSample,
)

T = TypeVar("T")


class FixedRing(Generic[T]):
    """Small typed wrapper around ``deque(maxlen=...)`` with drop counters."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("ring capacity must be >= 1")
        self.capacity = int(capacity)
        self._items: Deque[T] = deque(maxlen=self.capacity)
        self.total_appended = 0
        self.dropped_oldest = 0

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def append(self, item: T) -> None:
        if len(self._items) == self.capacity:
            self.dropped_oldest += 1
        self._items.append(item)
        self.total_appended += 1

    def extend(self, items: Iterable[T]) -> None:
        for item in items:
            self.append(item)

    def clear(self) -> None:
        self._items.clear()
        self.total_appended = 0
        self.dropped_oldest = 0

    def snapshot(self) -> tuple[T, ...]:
        return tuple(self._items)

    def last(self) -> T | None:
        if not self._items:
            return None
        return self._items[-1]


@dataclass(frozen=True, slots=True)
class PacketSummary:
    recv_time_ns: int
    packet_name: str
    seq: int
    timestamp: int
    payload_bytes: int
    diagnostic: bool = False
    payload_truncated: bool = False


@dataclass(frozen=True, slots=True)
class SequenceGapEvent:
    recv_time_ns: int
    previous_seq: int
    current_seq: int
    missing_count: int


@dataclass(frozen=True, slots=True)
class WavePoint:
    recv_time_ns: int
    sample_index: int
    xdel: int
    yout: int
    err: int

    @classmethod
    def from_wave_sample(cls, recv_time_ns: int, sample: WaveSample) -> "WavePoint":
        return cls(
            recv_time_ns=int(recv_time_ns),
            sample_index=int(sample.sample_index),
            xdel=int(sample.xdel),
            yout=int(sample.yout),
            err=int(sample.err),
        )


@dataclass(frozen=True, slots=True)
class SpectrumFrame:
    recv_time_ns: int
    packet_name: str
    frame_idx: int
    spec_shift: int
    magnitudes: tuple[int, ...]
    mask_bits: tuple[bool, ...] | None = None
    suppressed_count: tuple[int, ...] | None = None
    eligible_count: tuple[int, ...] | None = None

    @property
    def bin_count(self) -> int:
        return len(self.magnitudes)


@dataclass(frozen=True, slots=True)
class MetricsPoint:
    recv_time_ns: int
    frame_idx: int
    eligible_unique_bins: int
    eligible_suppressed_bins: int
    eligible_kept_mag2_lo: int
    eligible_total_mag2_lo: int
    sum_abs_err_lo: int
    sum_sq_err_lo: int
    max_abs_err: int
    overflow_flags: int
    kept_energy_ratio: float | None
    suppressed_bin_ratio: float | None
    aggregate_metrics: bool = False
    per_frame_metrics: bool = False
    payload_truncated: bool = False

    @classmethod
    def from_payload(cls, recv_time_ns: int, payload: MetricsPayload) -> "MetricsPoint":
        return cls(
            recv_time_ns=int(recv_time_ns),
            frame_idx=int(payload.frame_idx),
            eligible_unique_bins=int(payload.eligible_unique_bins),
            eligible_suppressed_bins=int(payload.eligible_suppressed_bins),
            eligible_kept_mag2_lo=int(payload.eligible_kept_mag2_lo),
            eligible_total_mag2_lo=int(payload.eligible_total_mag2_lo),
            sum_abs_err_lo=int(payload.sum_abs_err_lo),
            sum_sq_err_lo=int(payload.sum_sq_err_lo),
            max_abs_err=int(payload.max_abs_err),
            overflow_flags=int(payload.overflow_flags),
            kept_energy_ratio=payload.kept_energy_ratio,
            suppressed_bin_ratio=payload.suppressed_bin_ratio,
        )

    @classmethod
    def from_packet(cls, recv_time_ns: int, packet: ParsedPacket) -> "MetricsPoint":
        """Build a display point while preserving packet-level METRICS flags."""

        if not isinstance(packet.payload, MetricsPayload):
            raise TypeError("MetricsPoint requires a METRICS packet")
        payload = packet.payload
        flags = packet.header.flags
        return cls(
            recv_time_ns=int(recv_time_ns),
            frame_idx=int(payload.frame_idx),
            eligible_unique_bins=int(payload.eligible_unique_bins),
            eligible_suppressed_bins=int(payload.eligible_suppressed_bins),
            eligible_kept_mag2_lo=int(payload.eligible_kept_mag2_lo),
            eligible_total_mag2_lo=int(payload.eligible_total_mag2_lo),
            sum_abs_err_lo=int(payload.sum_abs_err_lo),
            sum_sq_err_lo=int(payload.sum_sq_err_lo),
            max_abs_err=int(payload.max_abs_err),
            overflow_flags=int(payload.overflow_flags),
            kept_energy_ratio=payload.kept_energy_ratio,
            suppressed_bin_ratio=payload.suppressed_bin_ratio,
            aggregate_metrics=bool(flags.aggregate_metrics),
            per_frame_metrics=bool(flags.per_frame_metrics),
            payload_truncated=bool(flags.payload_truncated),
        )


@dataclass(frozen=True, slots=True)
class StatusPoint:
    recv_time_ns: int
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
    thr2: int
    packet_fifo_drop_count: int
    diagnostic: bool
    payload_truncated: bool = False

    @classmethod
    def from_packet(cls, recv_time_ns: int, packet: ParsedPacket) -> "StatusPoint":
        if not isinstance(packet.payload, StatusPayload):
            raise TypeError("StatusPoint requires a STATUS packet")
        payload = packet.payload
        return cls(
            recv_time_ns=int(recv_time_ns),
            sample_count=int(payload.sample_count),
            frame_count=int(payload.frame_count),
            source_mode=int(payload.source_mode),
            sample_rate=int(payload.sample_rate),
            packet_enable=int(payload.packet_enable),
            dma_drop_count=int(payload.dma_drop_count),
            udp_send_error_count=int(payload.udp_send_error_count),
            malformed_record_count=int(payload.malformed_record_count),
            oversized_record_count=int(payload.oversized_record_count),
            command_reject_count=int(payload.command_reject_count),
            sequence_gap_count=int(payload.sequence_gap_count),
            overflow_flags=int(payload.overflow_flags),
            thr2=int(payload.thr2),
            packet_fifo_drop_count=int(payload.packet_fifo_drop_count),
            diagnostic=bool(packet.header.flags.status_diagnostic),
            payload_truncated=bool(packet.header.flags.payload_truncated),
        )


@dataclass(frozen=True, slots=True)
class DashboardRingBufferConfig:
    wave_points: int = 8192
    spectrum_frames: int = 256
    metrics_points: int = 1024
    status_points: int = 512
    packet_summaries: int = 2048
    sequence_gaps: int = 256
    packet_rate_window_s: float = 2.0

    def validate(self) -> None:
        for name, value in (
            ("wave_points", self.wave_points),
            ("spectrum_frames", self.spectrum_frames),
            ("metrics_points", self.metrics_points),
            ("status_points", self.status_points),
            ("packet_summaries", self.packet_summaries),
            ("sequence_gaps", self.sequence_gaps),
        ):
            if int(value) < 1:
                raise ValueError(f"{name} must be >= 1")
        if float(self.packet_rate_window_s) <= 0.0:
            raise ValueError("packet_rate_window_s must be > 0")


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    packets: tuple[PacketSummary, ...]
    wave: tuple[WavePoint, ...]
    spectra: tuple[SpectrumFrame, ...]
    metrics: tuple[MetricsPoint, ...]
    status: tuple[StatusPoint, ...]
    sequence_gaps: tuple[SequenceGapEvent, ...]
    packets_by_type: dict[str, int]
    total_packets: int
    total_wave_points: int
    total_sequence_gaps: int
    total_missing_sequences: int
    packet_rate_hz: float = 0.0
    total_payload_truncated_packets: int = 0
    total_duplicate_sequences: int = 0
    total_reordered_sequences: int = 0


@dataclass(slots=True)
class DashboardBufferStats:
    total_packets: int = 0
    total_wave_points: int = 0
    total_sequence_gaps: int = 0
    total_missing_sequences: int = 0
    total_payload_truncated_packets: int = 0
    total_duplicate_sequences: int = 0
    total_reordered_sequences: int = 0
    last_sequence: int | None = None
    packets_by_type: dict[str, int] = field(default_factory=dict)

    def clear(self) -> None:
        self.total_packets = 0
        self.total_wave_points = 0
        self.total_sequence_gaps = 0
        self.total_missing_sequences = 0
        self.total_payload_truncated_packets = 0
        self.total_duplicate_sequences = 0
        self.total_reordered_sequences = 0
        self.last_sequence = None
        self.packets_by_type.clear()


class DashboardRingBuffers:
    """Decoded-telemetry storage for the PC dashboard.

    The class preserves recent samples/frames/status for plotting. It does not
    recompute spectra, masks, or reconstruction output; it stores what the FPGA
    and HPS telemetry path sent.
    """

    def __init__(self, config: DashboardRingBufferConfig | None = None) -> None:
        self.config = config or DashboardRingBufferConfig()
        self.config.validate()
        self.packets: FixedRing[PacketSummary] = FixedRing(self.config.packet_summaries)
        self.wave: FixedRing[WavePoint] = FixedRing(self.config.wave_points)
        self.spectra: FixedRing[SpectrumFrame] = FixedRing(self.config.spectrum_frames)
        self.metrics: FixedRing[MetricsPoint] = FixedRing(self.config.metrics_points)
        self.status: FixedRing[StatusPoint] = FixedRing(self.config.status_points)
        self.sequence_gaps: FixedRing[SequenceGapEvent] = FixedRing(self.config.sequence_gaps)
        self.stats = DashboardBufferStats()
        self._packet_rate_times_ns: Deque[int] = deque(maxlen=self.config.packet_summaries)

    def clear(self) -> None:
        self.packets.clear()
        self.wave.clear()
        self.spectra.clear()
        self.metrics.clear()
        self.status.clear()
        self.sequence_gaps.clear()
        self._packet_rate_times_ns.clear()
        self.stats.clear()

    def ingest(self, packet: ParsedPacket, *, recv_time_ns: int | None = None) -> None:
        """Insert one parsed telemetry packet into the appropriate buffers."""

        t_ns = int(time.time_ns() if recv_time_ns is None else recv_time_ns)
        self._record_packet_summary(packet, t_ns)
        payload = packet.payload
        if isinstance(payload, WavePayload):
            self._ingest_wave(payload, t_ns)
        elif isinstance(payload, Spec129Payload):
            self._ingest_spec129(payload, t_ns)
        elif isinstance(payload, Spec64Payload):
            self._ingest_spec64(payload, t_ns)
        elif isinstance(payload, MetricsPayload):
            self.metrics.append(MetricsPoint.from_packet(t_ns, packet))
        elif isinstance(payload, StatusPayload):
            self.status.append(StatusPoint.from_packet(t_ns, packet))
        # WRAP is normally not forwarded over UDP. If a parser is configured to
        # allow it for offline DDR-ring debug, the summary is enough.

    def ingest_many(self, packets: Iterable[ParsedPacket], *, recv_time_ns: int | None = None) -> None:
        for packet in packets:
            self.ingest(packet, recv_time_ns=recv_time_ns)

    def latest_status(self) -> StatusPoint | None:
        return self.status.last()

    def latest_metrics(self) -> MetricsPoint | None:
        return self.metrics.last()

    def latest_spectrum(self) -> SpectrumFrame | None:
        return self.spectra.last()

    def latest_wave(self, count: int | None = None) -> tuple[WavePoint, ...]:
        data = self.wave.snapshot()
        if count is None or count >= len(data):
            return data
        if count < 0:
            raise ValueError("count must be >= 0")
        return data[-count:]

    def wave_columns(self, count: int | None = None) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
        """Return recent WAVE data as ``sample_index, xdel, yout, err`` tuples."""

        points = self.latest_wave(count)
        return (
            tuple(point.sample_index for point in points),
            tuple(point.xdel for point in points),
            tuple(point.yout for point in points),
            tuple(point.err for point in points),
        )

    def snapshot(self, now_ns: int | None = None) -> DashboardSnapshot:
        snapshot_time_ns = int(time.time_ns() if now_ns is None else now_ns)
        return DashboardSnapshot(
            packets=self.packets.snapshot(),
            wave=self.wave.snapshot(),
            spectra=self.spectra.snapshot(),
            metrics=self.metrics.snapshot(),
            status=self.status.snapshot(),
            sequence_gaps=self.sequence_gaps.snapshot(),
            packets_by_type=dict(self.stats.packets_by_type),
            total_packets=int(self.stats.total_packets),
            total_wave_points=int(self.stats.total_wave_points),
            total_sequence_gaps=int(self.stats.total_sequence_gaps),
            total_missing_sequences=int(self.stats.total_missing_sequences),
            packet_rate_hz=self._packet_rate_hz(snapshot_time_ns),
            total_payload_truncated_packets=int(
                self.stats.total_payload_truncated_packets
            ),
            total_duplicate_sequences=int(self.stats.total_duplicate_sequences),
            total_reordered_sequences=int(self.stats.total_reordered_sequences),
        )

    def _record_packet_summary(self, packet: ParsedPacket, recv_time_ns: int) -> None:
        self.stats.total_packets += 1
        self.stats.packets_by_type[packet.packet_name] = self.stats.packets_by_type.get(packet.packet_name, 0) + 1
        payload_truncated = bool(packet.header.flags.payload_truncated)
        if payload_truncated:
            self.stats.total_payload_truncated_packets += 1
        self._packet_rate_times_ns.append(int(recv_time_ns))
        self.packets.append(
            PacketSummary(
                recv_time_ns=int(recv_time_ns),
                packet_name=packet.packet_name,
                seq=int(packet.seq),
                timestamp=int(packet.timestamp),
                payload_bytes=int(packet.header.payload_bytes),
                diagnostic=bool(packet.header.flags.status_diagnostic),
                payload_truncated=payload_truncated,
            )
        )
        if packet.participates_in_sequence:
            current = int(packet.seq) & 0xFFFFFFFF
            previous = self.stats.last_sequence
            if previous is None:
                self.stats.last_sequence = current
                return

            delta = (current - int(previous)) & 0xFFFFFFFF
            if delta == 0:
                self.stats.total_duplicate_sequences += 1
                return
            if delta < 0x80000000:
                if delta > 1:
                    missing = delta - 1
                    self.stats.total_sequence_gaps += 1
                    self.stats.total_missing_sequences += int(missing)
                    self.sequence_gaps.append(
                        SequenceGapEvent(
                            recv_time_ns=int(recv_time_ns),
                            previous_seq=int(previous),
                            current_seq=current,
                            missing_count=int(missing),
                        )
                    )
                self.stats.last_sequence = current
                return

            # RFC1982 says deltas in the backward half of the uint32 space are
            # older/reordered (the exact half-range is ambiguous). Do not move
            # the high-water mark and, critically, do not report a huge gap.
            self.stats.total_reordered_sequences += 1

    def _packet_rate_hz(self, now_ns: int) -> float:
        window_ns = max(1, int(float(self.config.packet_rate_window_s) * 1_000_000_000.0))
        cutoff_ns = int(now_ns) - window_ns
        while self._packet_rate_times_ns and self._packet_rate_times_ns[0] < cutoff_ns:
            self._packet_rate_times_ns.popleft()
        return len(self._packet_rate_times_ns) / float(self.config.packet_rate_window_s)

    def _ingest_wave(self, payload: WavePayload, recv_time_ns: int) -> None:
        points = [WavePoint.from_wave_sample(recv_time_ns, sample) for sample in payload.samples]
        self.wave.extend(points)
        self.stats.total_wave_points += len(points)

    def _ingest_spec129(self, payload: Spec129Payload, recv_time_ns: int) -> None:
        self.spectra.append(
            SpectrumFrame(
                recv_time_ns=int(recv_time_ns),
                packet_name="SPEC129",
                frame_idx=int(payload.frame_idx),
                spec_shift=int(payload.spec_shift),
                magnitudes=tuple(int(v) for v in payload.magnitudes),
                mask_bits=tuple(bool(v) for v in payload.mask_bits),
            )
        )

    def _ingest_spec64(self, payload: Spec64Payload, recv_time_ns: int) -> None:
        self.spectra.append(
            SpectrumFrame(
                recv_time_ns=int(recv_time_ns),
                packet_name="SPEC64",
                frame_idx=int(payload.frame_idx),
                spec_shift=int(payload.spec_shift),
                magnitudes=tuple(int(v) for v in payload.magnitudes),
                suppressed_count=tuple(int(v) for v in payload.suppressed_count),
                eligible_count=tuple(int(v) for v in payload.eligible_count),
            )
        )


# Stable aliases retained for dashboard code written against earlier class
# names. They refer to the same implementation and do not duplicate state.
DashboardBufferConfig = DashboardRingBufferConfig
DashboardTelemetryBuffers = DashboardRingBuffers
