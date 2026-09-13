#!/usr/bin/env python3
"""Dependency-free Step-15 PC dashboard regression.

This test intentionally avoids a GUI backend, NumPy, pytest, a live UDP peer,
and FPGA hardware.  It exercises the source-level contracts beneath the GUI:

* bounded WAVE/METRICS/STATUS/SPEC history and a rectangular spectrogram;
* receive-time packet rate and RFC1982 sequence classification;
* separate DDR/FIFO drops plus protocol/socket truncation health;
* capture-append and live-control configuration propagation;
* a persistent, serialized, nonblocking command worker; and
* preservation of receiver queue-drop state and startup rollback at shutdown.

The public Step-15 API expected by this test is deliberately small:
``spectrogram_matrix(frames, max_frames=..., max_bins=...)`` returns an object
with ``frame_idx``, ``values``, ``suppression``, and ``packet_name``;
``LiveCommandController`` exposes ``start``, ``submit``, ``poll``, and ``stop``.
The helper accessors below tolerate minor field-name variations in display-only
objects, but they do not weaken any behavioral assertion.
"""

from __future__ import annotations

import json
import math
import socket
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence


PC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PC_ROOT.parents[1]
for candidate in (PC_ROOT, REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from generated import trecap_packet as gen  # noqa: E402
from trecap_dashboard import dashboard as dashboard_module  # noqa: E402
from trecap_dashboard import plots as plots_module  # noqa: E402
from trecap_dashboard.config import load_dashboard_config  # noqa: E402
from trecap_dashboard.packet_parser import (  # noqa: E402
    CAPTURE_MAGIC,
    MetricsPayload,
    PacketFlags,
    ParsedPacket,
    Spec64Payload,
    Spec129Payload,
    StatusPayload,
    TelemetryHeader,
    WavePayload,
    WaveSample,
    WrapPayload,
)
from trecap_dashboard.ring_buffers import (  # noqa: E402
    DashboardRingBufferConfig,
    DashboardRingBuffers,
)
from trecap_dashboard.udp_receiver import (  # noqa: E402
    FramedCaptureWriter,
    ReceivedDatagram,
    TelemetryUdpReceiver,
    UdpReceiverConfig,
    UdpReceiverStats,
)


NSEC = 1_000_000_000


def _flag_mask(name: str) -> int:
    lo, hi = gen.COMMON_FLAG_BITS[name]
    return ((1 << (int(hi) - int(lo) + 1)) - 1) << int(lo)


def _flags(*names: str) -> PacketFlags:
    raw = 0
    for name in names:
        raw |= _flag_mask(name)
    return PacketFlags.from_raw(raw)


def _payload_bytes(name: str, payload: object) -> int:
    if name == "WAVE":
        assert isinstance(payload, WavePayload)
        return int(gen.expected_payload_bytes(name, nsamp=payload.nsamp))
    return int(gen.expected_payload_bytes(name))


def _packet(
    name: str,
    payload: object,
    *,
    seq: int,
    timestamp: int = 0,
    flag_names: Sequence[str] = (),
) -> ParsedPacket:
    flags = _flags(*flag_names)
    header = TelemetryHeader(
        magic=int(gen.TELEMETRY_MAGIC),
        version=int(gen.TELEMETRY_HEADER_VERSION),
        header_bytes=int(gen.TELEMETRY_HEADER_BYTES),
        packet_type=int(gen.PACKET_TYPES[name]),
        flags_raw=int(flags.raw),
        seq=int(seq) & 0xFFFF_FFFF,
        timestamp=int(timestamp),
        payload_bytes=_payload_bytes(name, payload),
        header_crc=0,
        packet_name=name,
        flags=flags,
    )
    return ParsedPacket(header, payload, b"", b"")


def _status_packet(
    seq: int,
    *,
    sample_count: int | None = None,
    dma_drop_count: int = 0,
    packet_fifo_drop_count: int = 0,
    malformed_record_count: int = 0,
    oversized_record_count: int = 0,
    diagnostic: bool = False,
    payload_truncated: bool = False,
) -> ParsedPacket:
    sample = int(seq if sample_count is None else sample_count)
    payload = StatusPayload(
        sample_count=sample,
        frame_count=sample // 128,
        source_mode=2,
        sample_rate=48_000,
        packet_enable=0xF,
        dma_drop_count=int(dma_drop_count),
        udp_send_error_count=5,
        malformed_record_count=int(malformed_record_count),
        oversized_record_count=int(oversized_record_count),
        command_reject_count=6,
        sequence_gap_count=7,
        overflow_flags=0x12,
        thr2_lo=0x3456_789A,
        thr2_hi=0x0012_3456,
        packet_fifo_drop_count=int(packet_fifo_drop_count),
        reserved=0,
    )
    names: list[str] = []
    if diagnostic:
        names.append("status_diagnostic")
        seq = 0
    if payload_truncated:
        names.append("payload_truncated")
    return _packet("STATUS", payload, seq=seq, timestamp=sample, flag_names=names)


def _wave_packet(seq: int, *, sample_base: int = 100, stride: int = 2) -> ParsedPacket:
    samples = tuple(
        WaveSample(
            sample_index=sample_base + index * stride,
            xdel=10 + index,
            yout=8 + index,
            err=2,
        )
        for index in range(3)
    )
    payload = WavePayload(sample_base, len(samples), 3, stride, samples)
    return _packet("WAVE", payload, seq=seq, timestamp=sample_base)


def _metrics_packet(
    seq: int,
    *,
    frame_idx: int,
    total_energy: int,
    aggregate: bool = False,
    truncated: bool = False,
) -> ParsedPacket:
    payload = MetricsPayload(
        frame_idx=frame_idx,
        eligible_unique_bins=0 if total_energy == 0 else 100,
        eligible_suppressed_bins=0 if total_energy == 0 else 25,
        eligible_kept_mag2_lo=0 if total_energy == 0 else total_energy // 4,
        eligible_total_mag2_lo=total_energy,
        sum_abs_err_lo=11,
        sum_sq_err_lo=22,
        max_abs_err=3,
        overflow_flags=0,
    )
    names = ["aggregate_metrics" if aggregate else "per_frame_metrics"]
    if truncated:
        names.append("payload_truncated")
    return _packet("METRICS", payload, seq=seq, timestamp=frame_idx, flag_names=names)


def _spec64_packet(seq: int, frame_idx: int) -> ParsedPacket:
    magnitudes = tuple(frame_idx * 100 + index for index in range(64))
    suppressed = tuple(index % 4 for index in range(64))
    eligible = tuple(4 for _ in range(64))
    payload = Spec64Payload(frame_idx, 64, 20, magnitudes, suppressed, eligible)
    return _packet("SPEC64", payload, seq=seq, timestamp=frame_idx)


def _spec129_packet(seq: int, frame_idx: int) -> ParsedPacket:
    magnitudes = tuple(frame_idx * 100 + index for index in range(129))
    mask = tuple(index % 5 == 0 for index in range(129))
    raw_mask = bytearray(17)
    for index, bit in enumerate(mask):
        if bit:
            raw_mask[index // 8] |= 1 << (index % 8)
    payload = Spec129Payload(frame_idx, 129, 21, magnitudes, mask, bytes(raw_mask))
    return _packet("SPEC129", payload, seq=seq, timestamp=frame_idx)


def _wrap_packet() -> ParsedPacket:
    return _packet("WRAP", WrapPayload(), seq=0, timestamp=0)


def _as_tuple(value: object) -> tuple[Any, ...]:
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()
    return tuple(value)  # type: ignore[arg-type]


def _matrix_rows(value: object) -> tuple[tuple[Any, ...], ...]:
    return tuple(_as_tuple(row) for row in _as_tuple(value))


def _field(obj: object, *names: str) -> object:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AssertionError(f"{type(obj).__name__} lacks required field; expected one of {names}")


def _wait_for_outcomes(controller: object, count: int, timeout_s: float = 2.0) -> tuple[Any, ...]:
    deadline = time.monotonic() + timeout_s
    collected: list[Any] = []
    while len(collected) < count and time.monotonic() < deadline:
        events = controller.poll(max_items=max(32, count * 2))
        collected.extend(
            event
            for event in events
            if bool(getattr(event, "is_terminal", True))
        )
        if len(collected) < count:
            time.sleep(0.005)
    if len(collected) != count:
        raise AssertionError(
            f"timed out waiting for {count} command outcomes; got {len(collected)}"
        )
    return tuple(collected)


class DashboardBufferTests(unittest.TestCase):
    def test_all_required_payloads_and_wave_stride_are_preserved(self) -> None:
        buffers = DashboardRingBuffers(
            DashboardRingBufferConfig(
                wave_points=8,
                spectrum_frames=4,
                metrics_points=4,
                status_points=4,
                packet_summaries=16,
                sequence_gaps=4,
                packet_rate_window_s=1.0,
            )
        )
        buffers.ingest(_status_packet(1), recv_time_ns=0)
        buffers.ingest(_wave_packet(2), recv_time_ns=1)
        buffers.ingest(_metrics_packet(3, frame_idx=1, total_energy=100), recv_time_ns=2)
        buffers.ingest(_spec64_packet(4, 1), recv_time_ns=3)
        buffers.ingest(_spec129_packet(5, 2), recv_time_ns=4)
        snapshot = buffers.snapshot(now_ns=4)

        self.assertEqual(snapshot.total_packets, 5)
        self.assertEqual(tuple(point.sample_index for point in snapshot.wave), (100, 102, 104))
        self.assertEqual(snapshot.status[-1].source_mode, 2)
        self.assertEqual(snapshot.metrics[-1].frame_idx, 1)
        self.assertEqual(
            tuple(frame.packet_name for frame in snapshot.spectra),
            ("SPEC64", "SPEC129"),
        )

    def test_packet_rate_uses_inclusive_receive_time_window(self) -> None:
        buffers = DashboardRingBuffers(
            DashboardRingBufferConfig(packet_rate_window_s=1.0)
        )
        for seq, recv_time_ns in enumerate((0, NSEC // 4, NSEC // 2, 3 * NSEC // 4), 1):
            buffers.ingest(_status_packet(seq), recv_time_ns=recv_time_ns)

        self.assertAlmostEqual(buffers.snapshot(now_ns=NSEC).packet_rate_hz, 4.0)
        self.assertAlmostEqual(buffers.snapshot(now_ns=NSEC + 1).packet_rate_hz, 3.0)

    def test_rfc1982_wrap_diagnostic_duplicate_and_reorder(self) -> None:
        buffers = DashboardRingBuffers(DashboardRingBufferConfig())
        packets = (
            _status_packet(0xFFFF_FFFE),
            _status_packet(0xFFFF_FFFF),
            _status_packet(0, diagnostic=True),
            _wrap_packet(),
            _status_packet(0),
            _status_packet(0),  # duplicate
            _status_packet(0xFFFF_FFFF),  # reordered old packet
            _status_packet(2),  # one truly missing sequence
            _status_packet(0x8000_0002),  # exact half-range: ambiguous/reordered
        )
        for index, packet in enumerate(packets):
            buffers.ingest(packet, recv_time_ns=index)
        snapshot = buffers.snapshot(now_ns=len(packets))

        self.assertEqual(snapshot.total_sequence_gaps, 1)
        self.assertEqual(snapshot.total_missing_sequences, 1)
        self.assertEqual(snapshot.total_duplicate_sequences, 1)
        self.assertEqual(snapshot.total_reordered_sequences, 2)
        self.assertEqual(len(snapshot.sequence_gaps), 1)
        self.assertEqual(snapshot.sequence_gaps[0].previous_seq, 0)
        self.assertEqual(snapshot.sequence_gaps[0].current_seq, 2)

    def test_metrics_class_and_na_semantics_survive_buffering(self) -> None:
        buffers = DashboardRingBuffers(DashboardRingBufferConfig())
        buffers.ingest(
            _metrics_packet(1, frame_idx=10, total_energy=0, truncated=True),
            recv_time_ns=10,
        )
        buffers.ingest(
            _metrics_packet(2, frame_idx=11, total_energy=400, aggregate=True),
            recv_time_ns=11,
        )
        snapshot = buffers.snapshot(now_ns=11)
        first, second = snapshot.metrics

        self.assertTrue(first.per_frame_metrics)
        self.assertFalse(first.aggregate_metrics)
        self.assertTrue(first.payload_truncated)
        self.assertIsNone(first.kept_energy_ratio)
        self.assertIsNone(first.suppressed_bin_ratio)
        self.assertTrue(second.aggregate_metrics)
        self.assertFalse(second.per_frame_metrics)
        self.assertAlmostEqual(second.kept_energy_ratio or 0.0, 0.25)
        self.assertAlmostEqual(second.suppressed_bin_ratio or 0.0, 0.25)
        self.assertEqual(snapshot.total_payload_truncated_packets, 1)

        series = plots_module.metrics_series(snapshot.metrics)
        self.assertTrue(math.isnan(series.kept_energy_ratio[0]))
        self.assertTrue(math.isnan(series.suppressed_bin_ratio[0]))

    def test_spectrogram_is_bounded_rectangular_and_resets_on_mode_change(self) -> None:
        buffers = DashboardRingBuffers(
            DashboardRingBufferConfig(spectrum_frames=4, packet_summaries=16)
        )
        for packet in (
            _spec64_packet(1, 1),
            _spec64_packet(2, 2),
            _spec129_packet(3, 3),
            _spec129_packet(4, 4),
            _spec129_packet(5, 5),
        ):
            buffers.ingest(packet, recv_time_ns=packet.timestamp)
        snapshot = buffers.snapshot(now_ns=5)
        self.assertLessEqual(len(snapshot.spectra), 4)

        helper = getattr(plots_module, "spectrogram_matrix", None)
        self.assertTrue(callable(helper), "plots.spectrogram_matrix is required by Step 15")
        matrix = helper(snapshot.spectra, max_frames=4, max_bins=129)
        frame_idx = tuple(
            int(value)
            for value in _as_tuple(_field(matrix, "frame_idx", "frame_indices"))
        )
        values = _matrix_rows(_field(matrix, "values", "magnitudes", "matrix"))
        suppression = _matrix_rows(
            _field(matrix, "suppression", "suppression_values", "overlay")
        )
        packet_name = str(_field(matrix, "packet_name", "mode", "kind"))

        self.assertEqual(packet_name, "SPEC129")
        self.assertEqual(frame_idx, (3, 4, 5))
        self.assertEqual(len(values), 3)
        self.assertTrue(all(len(row) == 129 for row in values))
        self.assertEqual(values[-1], tuple(_spec129_packet(9, 5).payload.magnitudes))
        self.assertEqual(len(suppression), len(values))
        self.assertTrue(all(len(row) == 129 for row in suppression))


class HealthAndReceiverTests(unittest.TestCase):
    def test_distinct_drop_and_malformed_truncated_health_is_visible(self) -> None:
        buffers = DashboardRingBuffers(
            DashboardRingBufferConfig(packet_rate_window_s=1.0)
        )
        buffers.ingest(
            _status_packet(
                1,
                dma_drop_count=11,
                packet_fifo_drop_count=22,
                malformed_record_count=33,
                oversized_record_count=44,
                payload_truncated=True,
            ),
            recv_time_ns=NSEC,
        )
        snapshot = buffers.snapshot(now_ns=NSEC)
        status = snapshot.status[-1]
        self.assertEqual(status.dma_drop_count, 11)
        self.assertEqual(status.packet_fifo_drop_count, 22)
        self.assertEqual(status.malformed_record_count, 33)
        self.assertEqual(status.oversized_record_count, 44)
        self.assertTrue(status.payload_truncated)

        receiver_stats = UdpReceiverStats(
            datagrams_seen=9,
            datagrams_accepted=8,
            datagrams_socket_truncated=2,
            datagrams_truncated_or_oversized=3,
            parse_errors=4,
            last_error="truncated test datagram",
            last_error_kind="socket_truncated",
        )
        summary = plots_module.summarize_snapshot(snapshot)
        self.assertAlmostEqual(float(_field(summary, "packet_rate_hz", "packet_rate")), 1.0)
        self.assertEqual(
            int(_field(summary, "total_payload_truncated_packets", "payload_truncated_packets")),
            1,
        )

        text = plots_module.format_status_text(
            snapshot,
            receiver_stats=receiver_stats,
            command_status="PING seq=42 APPLIED",
            max_lines=128,
        ).lower()
        normalized = text.replace("-", "_").replace(" ", "_")
        for token in (
            "packet_rate",
            "sequence",
            "dma_drop",
            "packet_fifo",
            "malformed",
            "truncated",
            "truncated/oversized",
        ):
            self.assertIn(token, normalized)

        capped = plots_module.format_status_text(
            snapshot,
            receiver_stats=receiver_stats,
            command_status="PING seq=42 APPLIED",
            max_lines=34,
        )
        self.assertIn("last command", capped)
        self.assertIn("PING seq=42 APPLIED", capped)

    def test_udp_stats_use_same_rfc1982_classification_and_flags(self) -> None:
        stats = UdpReceiverStats()
        packets = (
            _status_packet(10, payload_truncated=True),
            _status_packet(10),
            _status_packet(9),
            _status_packet(12),
            _status_packet(0, diagnostic=True),
        )
        for index, packet in enumerate(packets):
            stats.note_parsed_packet(packet, recv_time_ns=100 + index)

        self.assertEqual(stats.payload_truncated_packet_count, 1)
        self.assertEqual(stats.duplicate_sequence_count, 1)
        self.assertEqual(stats.reordered_sequence_count, 1)
        self.assertEqual(stats.sequence_gap_count, 1)
        self.assertEqual(stats.missing_sequence_count, 1)
        self.assertEqual(stats.first_packet_time_ns, 100)
        self.assertEqual(stats.last_packet_time_ns, 104)

    def test_kernel_socket_truncation_is_not_parsed_as_valid_telemetry(self) -> None:
        class TruncatedSocket:
            def recvmsg(
                self,
                _size: int,
                _ancillary_size: int,
            ) -> tuple[bytes, list[object], int, tuple[str, int]]:
                return b"partial", [], int(socket.MSG_TRUNC), ("192.168.10.2", 5005)

            def close(self) -> None:
                pass

        receiver = TelemetryUdpReceiver(UdpReceiverConfig(expected_source=None))
        receiver._socket = TruncatedSocket()  # type: ignore[assignment]
        event = receiver.receive_event()
        receiver._socket = None

        self.assertIsNotNone(event)
        assert event is not None
        self.assertFalse(event.ok)
        self.assertTrue(event.datagram.truncated)
        self.assertEqual(event.error_kind, "socket_truncated")
        self.assertEqual(receiver.stats.datagrams_socket_truncated, 1)
        self.assertEqual(receiver.stats.datagrams_truncated_or_oversized, 1)
        self.assertEqual(receiver.stats.packets_parsed, 0)
        self.assertEqual(receiver.stats.parse_errors, 0)


class ConfigAndDashboardLifecycleTests(unittest.TestCase):
    def test_canonical_config_propagates_step15_runtime_fields(self) -> None:
        cfg = load_dashboard_config(PC_ROOT / "configs/dashboard_direct_link.json")
        self.assertFalse(cfg.capture.capture_append)
        self.assertTrue(cfg.display.live_controls)
        self.assertTrue(cfg.display.show_suppression_overlay)
        self.assertEqual(cfg.display.command_queue_size, 16)
        self.assertEqual(cfg.display.spectrogram_frames, 128)
        self.assertAlmostEqual(cfg.display.packet_rate_window_s, 1.0)

        runtime = cfg.to_dashboard_runtime_config()
        self.assertFalse(runtime.capture_append)
        self.assertTrue(runtime.live_controls)
        self.assertEqual(runtime.command_queue_size, 16)
        self.assertIsNotNone(runtime.command_config)
        self.assertTrue(runtime.plot_config.show_suppression_overlay)
        self.assertAlmostEqual(runtime.buffer_config.packet_rate_window_s, 1.0)

        # Live controls are intentionally disabled for capture replay/headless use;
        # config propagation still keeps the declared endpoint contract available.
        runtime_receiver = dashboard_module.TelemetryDashboardApp(
            dashboard_module.DashboardRuntimeConfig(
                text_only=True,
                capture_append=runtime.capture_append,
            )
        )._receiver_config()
        self.assertEqual(runtime_receiver.capture_append, runtime.capture_append)

    def test_capture_append_true_round_trips_through_loader_and_runtime(self) -> None:
        source = json.loads(
            (PC_ROOT / "configs/dashboard_direct_link.json").read_text(encoding="utf-8")
        )
        source["capture"]["capture_write"] = "capture.bin"
        source["capture"]["capture_read"] = None
        source["capture"]["capture_append"] = True
        source["display"]["text_only"] = True
        source["display"]["live_controls"] = False
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dashboard.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            cfg = load_dashboard_config(path)

        runtime = cfg.to_dashboard_runtime_config()
        self.assertTrue(cfg.capture.capture_append)
        self.assertTrue(runtime.capture_append)
        app = dashboard_module.TelemetryDashboardApp(runtime)
        self.assertTrue(app._receiver_config().capture_append)

    def test_capture_append_rejects_incomplete_existing_stream_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.capture"
            original = CAPTURE_MAGIC + b"partial"
            path.write_bytes(original)
            writer = FramedCaptureWriter(path, append=True)
            with self.assertRaisesRegex(ValueError, "truncated record header"):
                writer.open()
            self.assertEqual(path.read_bytes(), original)

    def test_capture_append_preserves_one_magic_and_complete_records(self) -> None:
        first = ReceivedDatagram(10, "192.168.10.2", 5005, b"first")
        second = ReceivedDatagram(20, "192.168.10.2", 5005, b"second")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "valid.capture"
            with FramedCaptureWriter(path) as writer:
                writer.write(first)
            with FramedCaptureWriter(path, append=True) as writer:
                writer.write(second)
            data = path.read_bytes()

        self.assertTrue(data.startswith(CAPTURE_MAGIC))
        self.assertEqual(data.count(CAPTURE_MAGIC), 1)
        records = tuple(dashboard_module.iter_capture_datagrams(data))
        self.assertEqual(tuple(record[3] for record in records), (b"first", b"second"))

    def test_receiver_queue_drop_survives_background_shutdown_in_summary(self) -> None:
        class FakeBackground:
            queue_drop_count = 7

            def __init__(self) -> None:
                self.stopped = False

            def stop(self) -> None:
                self.stopped = True

        app = dashboard_module.TelemetryDashboardApp(
            dashboard_module.DashboardRuntimeConfig(text_only=True)
        )
        background = FakeBackground()
        app.background = background  # type: ignore[assignment]
        app.stop()
        summary = app._summary()

        self.assertTrue(background.stopped)
        self.assertIsNone(app.background)
        self.assertEqual(summary.receiver_queue_drops, 7)

    def test_partial_live_startup_failure_rolls_back_background_resources(self) -> None:
        class FakeBackground:
            queue_drop_count = 3

            def __init__(self) -> None:
                self.stopped = False

            def stop(self) -> None:
                self.stopped = True

        app = dashboard_module.TelemetryDashboardApp(
            dashboard_module.DashboardRuntimeConfig(text_only=True)
        )
        background = FakeBackground()

        def fail_after_background_start() -> None:
            app.background = background  # type: ignore[assignment]
            raise RuntimeError("injected dashboard startup failure")

        app.start = fail_after_background_start  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "injected dashboard startup failure"):
            app._run_live()

        self.assertTrue(background.stopped)
        self.assertIsNone(app.background)
        self.assertEqual(app._receiver_queue_drops, 3)

    def test_receiver_open_failure_is_not_masked_by_unstarted_thread_cleanup(self) -> None:
        class BindFailureReceiver:
            def __init__(self) -> None:
                self.close_count = 0

            def open(self) -> None:
                raise OSError("injected telemetry bind failure")

            def close(self) -> None:
                self.close_count += 1

        app = dashboard_module.TelemetryDashboardApp(
            dashboard_module.DashboardRuntimeConfig(text_only=True)
        )
        receiver = BindFailureReceiver()
        app.receiver = receiver  # type: ignore[assignment]

        with self.assertRaisesRegex(OSError, "injected telemetry bind failure"):
            app._run_live()

        self.assertIsNone(app.background)
        self.assertGreaterEqual(receiver.close_count, 1)


@dataclass
class _FakeCommandResult:
    disposition_name: str = "APPLIED"
    reject_reason_name: str = "NONE"
    fpga_status: int = 0x2001
    csr_version: int = 0x0001_0008

    def succeeded(self) -> bool:
        return self.disposition_name in {"APPLIED", "NOOP"}


class _PersistentFakeCommandClient:
    """Thread-safe fake that exposes the Step-14 CommandClient surface."""

    def __init__(self, *, sequence_start: int = 41) -> None:
        self.sequence = int(sequence_start)
        self.open_count = 0
        self.close_count = 0
        self.calls: list[tuple[str, object | None, int, int]] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_first = True
        self._lock = threading.Lock()

    def open(self) -> None:
        self.open_count += 1

    def close(self) -> None:
        self.close_count += 1
        self.release.set()

    def _send(self, name: str, value: object | None = None) -> object:
        if self.block_first:
            self.block_first = False
            self.entered.set()
            if not self.release.wait(timeout=2.0):
                raise TimeoutError("test gate timed out")
        with self._lock:
            seq = self.sequence
            self.sequence = (self.sequence + 1) & 0xFFFF_FFFF
            self.calls.append((name, value, seq, threading.get_ident()))
        result = _FakeCommandResult()
        if name == "SET_SPEC_MODE" and value == 99:
            result = _FakeCommandResult("REJECTED", "ARGUMENT_RANGE")
        if name == "CLEAR_COUNTERS" and value == "raise":
            raise OSError("injected command failure")
        return SimpleNamespace(
            command_name=name,
            packet=SimpleNamespace(seq=seq),
            result=result,
            attempts=1,
            diagnostic_status=None,
            dry_run=False,
        )

    def ping(self) -> object:
        return self._send("PING")

    def set_thr2(self, value: object) -> object:
        return self._send("SET_THR2", value)

    def read_status_version(self) -> object:
        return self._send("READ_STATUS_VERSION")

    def set_spec_mode(self, value: object) -> object:
        return self._send("SET_SPEC_MODE", value)

    def clear_counters(self) -> object:
        return self._send("CLEAR_COUNTERS")


class LiveCommandControllerTests(unittest.TestCase):
    def test_submit_is_nonblocking_and_one_client_serializes_sequences(self) -> None:
        controller_class = getattr(dashboard_module, "LiveCommandController", None)
        self.assertIsNotNone(controller_class, "dashboard.LiveCommandController is required")
        client = _PersistentFakeCommandClient(sequence_start=41)
        controller = controller_class(client, queue_size=8)
        controller.start()
        try:
            self.assertTrue(controller.submit("PING"))
            self.assertTrue(client.entered.wait(timeout=1.0))
            running_events = controller.poll()
            self.assertEqual(len(running_events), 1)
            self.assertEqual(running_events[0].state, "running")
            self.assertIn("running", running_events[0].summary)

            # The worker is deliberately blocked inside PING. A live GUI submit
            # must still enqueue immediately rather than executing on this thread.
            begin = time.monotonic()
            self.assertTrue(controller.submit("SET_THR2", 123))
            self.assertTrue(controller.submit("READ_STATUS_VERSION"))
            self.assertLess(time.monotonic() - begin, 0.1)
            client.release.set()

            outcomes = _wait_for_outcomes(controller, 3)
            self.assertEqual(tuple(outcome.request.action for outcome in outcomes), (
                "PING",
                "SET_THR2",
                "READ_STATUS_VERSION",
            ))
            self.assertTrue(all(outcome.ok for outcome in outcomes))
            self.assertTrue(all(outcome.send_result is not None for outcome in outcomes))
            self.assertEqual(tuple(call[0] for call in client.calls), (
                "PING",
                "SET_THR2",
                "READ_STATUS_VERSION",
            ))
            self.assertEqual(tuple(call[2] for call in client.calls), (41, 42, 43))
            self.assertEqual(len({call[3] for call in client.calls}), 1)
            self.assertNotEqual(client.calls[0][3], threading.get_ident())
            self.assertEqual(client.open_count, 1)
        finally:
            client.release.set()
            controller.stop()
        self.assertEqual(client.close_count, 1)

    def test_worker_open_failure_rejects_later_submissions(self) -> None:
        class OpenFailureClient(_PersistentFakeCommandClient):
            def open(self) -> None:
                self.open_count += 1
                raise OSError("injected command bind failure")

        client = OpenFailureClient()
        client.block_first = False
        controller = dashboard_module.LiveCommandController(client, queue_size=2)
        controller.start()
        deadline = time.monotonic() + 1.0
        while controller.is_running and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(controller.is_running)
        self.assertFalse(controller.submit("PING"))
        outcomes = controller.poll(max_items=8)
        self.assertTrue(any("bind failure" in item.summary for item in outcomes))
        self.assertTrue(any("unavailable" in item.summary for item in outcomes))
        self.assertTrue(all(item.is_terminal for item in outcomes))
        controller.stop()
        self.assertEqual(client.close_count, 1)

    def test_rejected_result_and_worker_exception_are_reported_not_raised_in_gui(self) -> None:
        controller_class = getattr(dashboard_module, "LiveCommandController", None)
        self.assertIsNotNone(controller_class, "dashboard.LiveCommandController is required")
        client = _PersistentFakeCommandClient(sequence_start=100)
        client.block_first = False

        # CLEAR_COUNTERS has no wire argument. Override the fake method itself to
        # inject a transport failure without changing the controller API.
        def fail_clear() -> object:
            raise OSError("injected command failure")

        client.clear_counters = fail_clear  # type: ignore[method-assign]
        controller = controller_class(client, queue_size=4)
        controller.start()
        try:
            self.assertTrue(controller.submit("SET_SPEC_MODE", 99))
            self.assertTrue(controller.submit("CLEAR_COUNTERS"))
            rejected, failed = _wait_for_outcomes(controller, 2)
            self.assertFalse(rejected.ok)
            self.assertIsNotNone(rejected.send_result)
            self.assertIn("REJECTED", rejected.summary)
            self.assertFalse(failed.ok)
            self.assertIsNone(failed.send_result)
            self.assertIn("injected command failure", failed.summary)
            self.assertTrue(controller.is_running)
        finally:
            controller.stop()

    def test_invalid_action_is_rejected_without_touching_client(self) -> None:
        controller_class = getattr(dashboard_module, "LiveCommandController", None)
        self.assertIsNotNone(controller_class, "dashboard.LiveCommandController is required")
        client = _PersistentFakeCommandClient()
        client.block_first = False
        controller = controller_class(client, queue_size=1)
        self.assertFalse(controller.submit("DIRECT_CSR_WRITE", 0xDEAD_BEEF))
        (outcome,) = controller.poll()
        self.assertFalse(outcome.ok)
        self.assertIn("unsupported", outcome.summary.lower())
        self.assertEqual(client.calls, [])
        controller.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
