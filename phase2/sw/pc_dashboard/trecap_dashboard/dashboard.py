"""PC-side live dashboard and nonblocking command-control orchestration.

The application owns process-level wiring only: background UDP receive, bounded
display buffers, fixed-rate rendering, capture replay, and a serialized command
worker. It never implements DSP, touches FPGA CSRs directly, or acts as a
bit-accurate signoff authority.
"""

from __future__ import annotations

import argparse
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .command_client import CommandClient, CommandClientConfig
from .packet_parser import PacketParserError, TelemetryPacketParser, iter_capture_datagrams
from .plots import DashboardPlotter, HeadlessDashboardRenderer, PlotConfig
from .ring_buffers import DashboardSnapshot

try:
    from .ring_buffers import DashboardBufferConfig, DashboardTelemetryBuffers
except ImportError:
    from .ring_buffers import (
        DashboardRingBufferConfig as DashboardBufferConfig,
        DashboardRingBuffers as DashboardTelemetryBuffers,
    )

try:
    from .udp_receiver import BackgroundUdpReceiver, UdpEndpoint, UdpReceiver, UdpReceiverConfig
except ImportError:
    from .udp_receiver import (
        BackgroundTelemetryReceiver as BackgroundUdpReceiver,
        TelemetryUdpReceiver as UdpReceiver,
        UdpEndpoint,
        UdpReceiverConfig,
    )

DEFAULT_REFRESH_HZ = 20.0
DEFAULT_TEXT_REFRESH_HZ = 2.0
DEFAULT_EVENT_BUDGET_PER_REFRESH = 2048
DEFAULT_QUEUE_SIZE = 4096
DEFAULT_COMMAND_QUEUE_SIZE = 16
DEFAULT_TELEMETRY_PORT = 5005


@dataclass(frozen=True, slots=True)
class LiveCommandRequest:
    """One explicit UI command request."""

    action: str
    value: int | str | bool | None = None
    requested_time_ns: int = 0


@dataclass(frozen=True, slots=True)
class LiveCommandOutcome:
    """Nonblocking result returned from the serialized command worker."""

    request: LiveCommandRequest
    ok: bool
    summary: str
    completed_time_ns: int
    send_result: object | None = None
    state: str = "completed"

    @property
    def is_terminal(self) -> bool:
        return self.state in {"completed", "failed"}


class LiveCommandController:
    """Run one long-lived CommandClient on a worker thread."""

    _NO_VALUE_ACTIONS = {
        "PING": "ping",
        "CLEAR_METRICS": "clear_metrics",
        "CONFIGURE_DDR_RING": "configure_ddr_ring",
        "RESET_TRANSPORT": "reset_transport",
        "CLEAR_COUNTERS": "clear_counters",
        "START_BRAM_REPLAY": "start_bram_replay",
        "READ_STATUS_VERSION": "read_status_version",
    }
    _VALUE_ACTIONS = {
        "SET_THR2": "set_thr2",
        "SET_SOURCE_MODE": "set_source_mode",
        "SET_PACKET_ENABLE": "set_packet_enable",
        "SET_WAVE_DECIM": "set_wave_decim",
        "SET_SPEC_SHIFT": "set_spec_shift",
        "SET_SPEC_MODE": "set_spec_mode",
        "SET_TELEMETRY_ENABLE": "set_telemetry_enable",
    }

    def __init__(
        self,
        client: CommandClient,
        *,
        queue_size: int = DEFAULT_COMMAND_QUEUE_SIZE,
    ) -> None:
        if int(queue_size) < 1:
            raise ValueError("command queue_size must be >= 1")
        self.client = client
        self.requests: queue.Queue[LiveCommandRequest] = queue.Queue(maxsize=int(queue_size))
        self.outcomes: queue.Queue[LiveCommandOutcome] = queue.Queue(
            maxsize=max(8, int(queue_size) * 2)
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._client_close_lock = threading.Lock()
        self._client_closed = False
        self._accepting = False
        self.queue_drop_count = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        with self._client_close_lock:
            self._client_closed = False
        thread = threading.Thread(
            target=self._run,
            name="trecap-command-worker",
            daemon=True,
        )
        with self._state_lock:
            self._thread = thread
            self._accepting = True
        try:
            thread.start()
        except BaseException:
            with self._state_lock:
                self._accepting = False
                self._thread = None
            raise

    def stop(self, *, join_timeout_s: float = 4.0) -> None:
        self._stop_event.set()
        with self._state_lock:
            self._accepting = False
            thread = self._thread
        if thread is None:
            self._fail_pending("command worker stopped before request was sent")
            self._close_client_once()
            return
        thread.join(timeout=max(0.0, float(join_timeout_s)))
        if thread.is_alive():
            self._close_client_once()
            thread.join(timeout=1.0)
        self._fail_pending("command worker stopped before request was sent")
        with self._state_lock:
            if not thread.is_alive() and self._thread is thread:
                self._thread = None
        if thread.is_alive():
            self._publish(
                LiveCommandOutcome(
                    LiveCommandRequest("WORKER", None, time.time_ns()),
                    False,
                    "command worker did not stop before the shutdown deadline",
                    time.time_ns(),
                    state="failed",
                )
            )

    def submit(self, action: str, value: int | str | bool | None = None) -> bool:
        normalized = str(action).strip().upper().replace("-", "_")
        if normalized not in self._NO_VALUE_ACTIONS and normalized not in self._VALUE_ACTIONS:
            self._publish(
                LiveCommandOutcome(
                    LiveCommandRequest(normalized, value, time.time_ns()),
                    False,
                    f"unsupported live command: {normalized}",
                    time.time_ns(),
                    state="failed",
                )
            )
            return False
        request = LiveCommandRequest(normalized, value, time.time_ns())
        with self._state_lock:
            thread = self._thread
            accepting = self._accepting and thread is not None and thread.is_alive()
            if accepting:
                try:
                    self.requests.put_nowait(request)
                except queue.Full:
                    accepting = False
                    self.queue_drop_count += 1
                    summary = "command queue full; request not sent"
            else:
                summary = "command worker unavailable; request not sent"
        if not accepting:
            self._publish(
                LiveCommandOutcome(
                    request,
                    False,
                    summary,
                    time.time_ns(),
                    state="failed",
                )
            )
            return False
        return True

    def poll(self, *, max_items: int = 32) -> tuple[LiveCommandOutcome, ...]:
        if int(max_items) < 1:
            raise ValueError("max_items must be >= 1")
        items: list[LiveCommandOutcome] = []
        for _ in range(int(max_items)):
            try:
                items.append(self.outcomes.get_nowait())
            except queue.Empty:
                break
        return tuple(items)

    def _run(self) -> None:
        try:
            self.client.open()
            while not self._stop_event.is_set():
                try:
                    request = self.requests.get(timeout=0.05)
                except queue.Empty:
                    continue
                self._execute(request)
        except BaseException as exc:
            self._publish(
                LiveCommandOutcome(
                    LiveCommandRequest("WORKER", None, time.time_ns()),
                    False,
                    f"command worker failed: {exc}",
                    time.time_ns(),
                    state="failed",
                )
            )
        finally:
            with self._state_lock:
                self._accepting = False
            self._fail_pending("command worker stopped before request was sent")
            self._close_client_once()

    def _execute(self, request: LiveCommandRequest) -> None:
        self._publish(
            LiveCommandOutcome(
                request,
                True,
                f"{request.action} running",
                time.time_ns(),
                state="running",
            )
        )
        try:
            if request.action in self._NO_VALUE_ACTIONS:
                if request.value is not None:
                    raise ValueError(f"{request.action} does not accept a value")
                method_name = self._NO_VALUE_ACTIONS[request.action]
                send_result = getattr(self.client, method_name)()
            else:
                if request.value is None:
                    raise ValueError(f"{request.action} requires a value")
                method_name = self._VALUE_ACTIONS[request.action]
                send_result = getattr(self.client, method_name)(request.value)
            self._publish(
                LiveCommandOutcome(
                    request,
                    _command_result_succeeded(send_result),
                    _format_command_result(send_result),
                    time.time_ns(),
                    send_result,
                    "completed",
                )
            )
        except Exception as exc:
            self._publish(
                LiveCommandOutcome(
                    request,
                    False,
                    f"{request.action} failed: {exc}",
                    time.time_ns(),
                    state="failed",
                )
            )

    def _fail_pending(self, summary: str) -> None:
        while True:
            try:
                request = self.requests.get_nowait()
            except queue.Empty:
                return
            self._publish(
                LiveCommandOutcome(
                    request,
                    False,
                    summary,
                    time.time_ns(),
                    state="failed",
                )
            )

    def _close_client_once(self) -> None:
        with self._client_close_lock:
            if self._client_closed:
                return
            self.client.close()
            self._client_closed = True

    def _publish(self, outcome: LiveCommandOutcome) -> None:
        try:
            self.outcomes.put_nowait(outcome)
        except queue.Full:
            try:
                self.outcomes.get_nowait()
            except queue.Empty:
                pass
            try:
                self.outcomes.put_nowait(outcome)
            except queue.Full:
                pass


def _command_result_succeeded(send_result: object) -> bool:
    result = getattr(send_result, "result", None)
    if result is None:
        return True
    succeeded = getattr(result, "succeeded", None)
    return bool(succeeded() if callable(succeeded) else succeeded)


def _format_command_result(send_result: object) -> str:
    command_name = str(getattr(send_result, "command_name", "command"))
    packet = getattr(send_result, "packet", None)
    seq = getattr(packet, "seq", "?")
    attempts = getattr(send_result, "attempts", 1)
    diagnostic = getattr(send_result, "diagnostic_status", None)
    if diagnostic is not None:
        return f"{command_name} seq={seq} diagnostic STATUS bytes={len(diagnostic)}"
    result = getattr(send_result, "result", None)
    if result is None:
        qualifier = (
            "dry-run" if bool(getattr(send_result, "dry_run", False)) else "sent/unconfirmed"
        )
        return f"{command_name} seq={seq} {qualifier} attempts={attempts}"
    return (
        f"{command_name} seq={seq} {getattr(result, 'disposition_name', 'UNKNOWN')} "
        f"reason={getattr(result, 'reject_reason_name', 'UNKNOWN')} "
        f"status=0x{int(getattr(result, 'fpga_status', 0)):08x} "
        f"version=0x{int(getattr(result, 'csr_version', 0)):08x} "
        f"attempts={attempts}"
    )


@dataclass(frozen=True, slots=True)
class DashboardRuntimeConfig:
    """Runtime configuration for the PC dashboard process."""

    bind_host: str = "0.0.0.0"
    bind_port: int = DEFAULT_TELEMETRY_PORT
    expected_source: str | None = "192.168.10.2"
    capture_write: Path | None = None
    capture_read: Path | None = None
    capture_append: bool = False
    allow_wrap: bool = False
    enforce_udp_limit: bool = True
    text_only: bool = False
    refresh_hz: float = DEFAULT_REFRESH_HZ
    text_refresh_hz: float = DEFAULT_TEXT_REFRESH_HZ
    queue_size: int = DEFAULT_QUEUE_SIZE
    max_packets: int | None = None
    duration_s: float | None = None
    event_budget_per_refresh: int = DEFAULT_EVENT_BUDGET_PER_REFRESH
    title: str = "T-RECAP Phase 2 Telemetry"
    quiet: bool = False
    buffer_config: DashboardBufferConfig | None = None
    plot_config: PlotConfig | None = None
    command_config: CommandClientConfig | None = None
    live_controls: bool = False
    command_queue_size: int = DEFAULT_COMMAND_QUEUE_SIZE

    def validate(self) -> None:
        if not (1 <= int(self.bind_port) <= 65535):
            raise ValueError("bind_port must be in range 1..65535")
        if self.capture_write is not None and self.capture_read is not None:
            raise ValueError("capture_write and capture_read cannot both be set")
        if self.refresh_hz <= 0.0:
            raise ValueError("refresh_hz must be > 0")
        if self.text_refresh_hz <= 0.0:
            raise ValueError("text_refresh_hz must be > 0")
        if self.queue_size < 1:
            raise ValueError("queue_size must be >= 1")
        if self.max_packets is not None and self.max_packets < 1:
            raise ValueError("max_packets must be >= 1")
        if self.duration_s is not None and self.duration_s <= 0.0:
            raise ValueError("duration_s must be > 0")
        if self.event_budget_per_refresh < 1:
            raise ValueError("event_budget_per_refresh must be >= 1")
        if self.command_queue_size < 1:
            raise ValueError("command_queue_size must be >= 1")
        if self.live_controls and self.command_config is None:
            raise ValueError("live_controls require command_config")
        if self.buffer_config is not None:
            self.buffer_config.validate()
        if self.plot_config is not None:
            self.plot_config.validate()
        if self.command_config is not None:
            self.command_config.validate()


@dataclass(frozen=True, slots=True)
class DashboardRunSummary:
    packets_ingested: int
    parse_errors: int
    receiver_queue_drops: int
    sequence_gaps: int
    missing_sequences: int
    packets_by_type: dict[str, int]
    elapsed_seconds: float
    command_queue_drops: int = 0
    command_failures: int = 0


class TelemetryDashboardApp:
    """Coordinate UDP receive, decoded buffers, rendering, and live controls."""

    def __init__(
        self,
        config: DashboardRuntimeConfig | None = None,
        *,
        command_client: CommandClient | None = None,
    ) -> None:
        self.config = config or DashboardRuntimeConfig()
        self.config.validate()
        self.receiver = UdpReceiver(self._receiver_config())
        self.background: BackgroundUdpReceiver | None = None
        self.buffers = DashboardTelemetryBuffers(self.config.buffer_config)
        self.plotter = None if self.config.text_only else DashboardPlotter(self.config.plot_config)
        self._stop_requested = False
        self._packets_ingested = 0
        self._parse_errors = 0
        self._start_time_ns = 0
        self._receiver_queue_drops = 0
        self._last_capture_time_ns: int | None = None
        self._command_failures = 0
        self._last_command_status = "live controls disabled"
        self.command_controller: LiveCommandController | None = None

        controls_active = (
            bool(self.config.live_controls)
            and not self.config.text_only
            and self.config.capture_read is None
        )
        if controls_active:
            client = command_client or CommandClient(self.config.command_config)
            self.command_controller = LiveCommandController(
                client,
                queue_size=self.config.command_queue_size,
            )
            self._last_command_status = "live controls ready"
            assert self.plotter is not None
            self.plotter.set_command_submitter(self.submit_live_command)
            self.plotter.set_command_status(self._last_command_status)

    def request_stop(self) -> None:
        self._stop_requested = True

    def snapshot(self) -> DashboardSnapshot:
        now_ns = self._last_capture_time_ns if self.config.capture_read is not None else None
        try:
            return self.buffers.snapshot(now_ns=now_ns)
        except TypeError:
            return self.buffers.snapshot()

    def submit_live_command(
        self,
        action: str,
        value: int | str | bool | None = None,
    ) -> bool:
        controller = self.command_controller
        if controller is None:
            self._last_command_status = "live controls unavailable"
            if self.plotter is not None:
                self.plotter.set_command_status(self._last_command_status)
            return False
        accepted = controller.submit(action, value)
        self._last_command_status = (
            f"{str(action).upper()} queued" if accepted else f"{str(action).upper()} not queued"
        )
        if self.plotter is not None:
            self.plotter.set_command_status(self._last_command_status)
        return accepted

    def run(self) -> DashboardRunSummary:
        self._start_time_ns = time.time_ns()
        if self.config.capture_read is not None:
            self._run_capture_replay(self.config.capture_read)
        else:
            self._run_live()
        return self._summary()

    def start(self) -> None:
        if self.background is not None:
            return
        try:
            if hasattr(self.receiver, "start_background"):
                background = self.receiver.start_background(
                    queue_maxsize=self.config.queue_size
                )
            else:
                background = BackgroundUdpReceiver(
                    self.receiver,
                    queue_maxsize=self.config.queue_size,
                )
                background.start()
        except BaseException:
            self.receiver.close()
            raise
        self.background = background
        try:
            if self.command_controller is not None:
                self.command_controller.start()
            if self.plotter is not None:
                self.plotter.open()
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        background = self.background
        if background is not None:
            self._receiver_queue_drops = int(
                getattr(background, "queue_drop_count", 0) or 0
            )
            background.stop()
        else:
            self.receiver.close()
        self.background = None
        if self.command_controller is not None:
            self.command_controller.stop()
            self._poll_command_outcomes()
        if self.plotter is not None:
            self.plotter.close()

    def _run_capture_replay(self, path: Path) -> None:
        parser = TelemetryPacketParser(
            allow_wrap=self.config.allow_wrap,
            enforce_udp_limit=self.config.enforce_udp_limit,
            exact_length=True,
        )
        try:
            for index, (recv_time_ns, _host, _port, datagram) in enumerate(
                iter_capture_datagrams(path.read_bytes())
            ):
                try:
                    packet = parser.parse_datagram(datagram)
                except PacketParserError as exc:
                    raise RuntimeError(
                        f"failed to parse capture {path} record {index}: {exc}"
                    ) from exc
                self.buffers.ingest(packet, recv_time_ns=recv_time_ns)
                self._last_capture_time_ns = int(recv_time_ns)
                self._packets_ingested += 1
        except PacketParserError as exc:
            raise RuntimeError(f"failed to parse capture {path}: {exc}") from exc
        if self.plotter is None:
            self._print_snapshot(force=True)
            return
        self.plotter.update(
            self.snapshot(),
            receiver_stats=self._receiver_stats(),
            queue_drop_count=self._receiver_queue_drops,
        )
        self.plotter.show()

    def _run_live(self) -> None:
        try:
            self.start()
            assert self.background is not None
            if self.plotter is None:
                self._run_text_loop(self.background)
            else:
                self._run_gui_loop(self.background)
        finally:
            self.stop()

    def _run_gui_loop(self, background: BackgroundUdpReceiver) -> None:
        assert self.plotter is not None
        refresh_period = 1.0 / float(self.config.refresh_hz)
        next_refresh = 0.0
        while self._keep_running():
            self._drain_events(background)
            self._poll_command_outcomes()
            now = time.monotonic()
            if now >= next_refresh:
                self.plotter.update(
                    self.snapshot(),
                    receiver_stats=self._receiver_stats(),
                    queue_drop_count=int(getattr(background, "queue_drop_count", 0) or 0),
                )
                next_refresh = now + refresh_period
            self.plotter.pause(min(0.05, refresh_period))
        self._drain_events(background)
        self._poll_command_outcomes()
        self.plotter.update(
            self.snapshot(),
            receiver_stats=self._receiver_stats(),
            queue_drop_count=int(getattr(background, "queue_drop_count", 0) or 0),
        )

    def _run_text_loop(self, background: BackgroundUdpReceiver) -> None:
        refresh_period = 1.0 / float(self.config.text_refresh_hz)
        next_print = 0.0
        while self._keep_running():
            self._drain_events(background)
            now = time.monotonic()
            if now >= next_print:
                self._print_snapshot(force=False)
                next_print = now + refresh_period
            time.sleep(min(0.05, refresh_period))
        self._drain_events(background)
        self._print_snapshot(force=True)

    def _drain_events(self, background: BackgroundUdpReceiver) -> None:
        for _ in range(int(self.config.event_budget_per_refresh)):
            try:
                event = background.events.get_nowait()
            except queue.Empty:
                return
            self._handle_event(event)

    def _handle_event(self, event: object) -> None:
        packet = getattr(event, "packet", None)
        datagram = getattr(event, "datagram", None)
        error = getattr(event, "error", None)
        ok = bool(getattr(event, "ok", packet is not None and error is None))
        if ok and packet is not None:
            recv_time_ns = getattr(datagram, "recv_time_ns", None)
            self.buffers.ingest(packet, recv_time_ns=recv_time_ns)
            self._packets_ingested += 1
            return
        self._parse_errors += 1
        if not self.config.quiet and error is not None:
            host = getattr(datagram, "source_host", "unknown")
            kind = getattr(event, "error_kind", "parse_error")
            print(f"telemetry {kind} from {host}: {error}", file=sys.stderr)

    def _poll_command_outcomes(self) -> None:
        controller = self.command_controller
        if controller is None:
            return
        for outcome in controller.poll():
            self._last_command_status = outcome.summary
            if outcome.is_terminal and not outcome.ok:
                self._command_failures += 1
            if self.plotter is not None:
                self.plotter.set_command_status(outcome.summary)

    def _keep_running(self) -> bool:
        if self._stop_requested:
            return False
        if self.config.max_packets is not None and self._packets_ingested >= self.config.max_packets:
            return False
        if self.config.duration_s is not None and self._elapsed_seconds() >= self.config.duration_s:
            return False
        background = self.background
        if background is not None and getattr(background, "thread_error", None) is not None:
            raise RuntimeError("UDP receiver thread failed") from background.thread_error
        return True

    def _print_snapshot(self, *, force: bool) -> None:
        if self.config.quiet and not force:
            return
        renderer = HeadlessDashboardRenderer(self.config.plot_config)
        print(
            renderer.render(
                self.snapshot(),
                receiver_stats=self._receiver_stats(),
                queue_drop_count=self._receiver_queue_drops,
                command_status=self._last_command_status,
            )
        )
        print("-" * 72)

    def _summary(self) -> DashboardRunSummary:
        snapshot = self.snapshot()
        controller = self.command_controller
        command_queue_drops = int(getattr(controller, "queue_drop_count", 0) or 0)
        return DashboardRunSummary(
            packets_ingested=int(self._packets_ingested),
            parse_errors=int(self._parse_errors),
            receiver_queue_drops=int(self._receiver_queue_drops),
            sequence_gaps=int(snapshot.total_sequence_gaps),
            missing_sequences=int(snapshot.total_missing_sequences),
            packets_by_type=dict(snapshot.packets_by_type),
            elapsed_seconds=self._elapsed_seconds(),
            command_queue_drops=command_queue_drops,
            command_failures=int(self._command_failures),
        )

    def _elapsed_seconds(self) -> float:
        if self._start_time_ns == 0:
            return 0.0
        return (time.time_ns() - self._start_time_ns) / 1_000_000_000.0

    def _receiver_stats(self) -> object | None:
        return getattr(self.receiver, "counters", getattr(self.receiver, "stats", None))

    def _receiver_config(self) -> UdpReceiverConfig:
        expected = UdpEndpoint.parse(self.config.expected_source) if self.config.expected_source else None
        return UdpReceiverConfig(
            bind_host=self.config.bind_host,
            bind_port=self.config.bind_port,
            expected_source=expected,
            allow_wrap=self.config.allow_wrap,
            enforce_udp_limit=self.config.enforce_udp_limit,
            capture_path=self.config.capture_write,
            capture_append=self.config.capture_append,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PC dashboard for T-RECAP Phase 2 UDP telemetry.")
    parser.add_argument("--bind-host", default="0.0.0.0", help="UDP bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_TELEMETRY_PORT, help="UDP telemetry port")
    parser.add_argument("--expected-source", default="192.168.10.2", help="HPS source filter HOST or HOST:PORT; empty disables filtering")
    parser.add_argument("--capture-write", type=Path, default=None, help="write framed UDP capture")
    parser.add_argument("--capture-read", type=Path, default=None, help="replay framed UDP capture")
    parser.add_argument("--capture-append", action="store_true", help="append to capture file")
    parser.add_argument("--allow-wrap", action="store_true", help="allow WRAP records for DDR debug captures")
    parser.add_argument("--no-udp-limit", action="store_true", help="disable UDP no-fragment bound check")
    parser.add_argument("--text-only", action="store_true", help="run without matplotlib GUI")
    parser.add_argument("--no-gui", action="store_true", help="alias for --text-only")
    parser.add_argument("--refresh-hz", type=float, default=DEFAULT_REFRESH_HZ, help="GUI refresh rate")
    parser.add_argument("--text-refresh-hz", type=float, default=DEFAULT_TEXT_REFRESH_HZ, help="text refresh rate")
    parser.add_argument("--queue-size", type=int, default=DEFAULT_QUEUE_SIZE, help="background event queue size")
    parser.add_argument("--max-packets", type=int, default=None, help="stop after N parsed packets")
    parser.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    parser.add_argument("--title", default="T-RECAP Phase 2 Telemetry", help="dashboard window title")
    parser.add_argument("--quiet", action="store_true", help="suppress non-final text output")
    parser.add_argument("--wave-points", type=int, default=8192, help="wave buffer capacity")
    parser.add_argument("--spectrum-frames", type=int, default=256, help="spectrum frame buffer capacity")
    parser.add_argument("--metrics-points", type=int, default=1024, help="metrics buffer capacity")
    parser.add_argument("--status-points", type=int, default=512, help="status buffer capacity")
    return parser


def config_from_args(args: argparse.Namespace) -> DashboardRuntimeConfig:
    expected = str(args.expected_source) if args.expected_source else None
    return DashboardRuntimeConfig(
        bind_host=str(args.bind_host),
        bind_port=int(args.port),
        expected_source=expected,
        capture_write=args.capture_write,
        capture_read=args.capture_read,
        capture_append=bool(args.capture_append),
        allow_wrap=bool(args.allow_wrap),
        enforce_udp_limit=not bool(args.no_udp_limit),
        text_only=bool(args.text_only or args.no_gui),
        refresh_hz=float(args.refresh_hz),
        text_refresh_hz=float(args.text_refresh_hz),
        queue_size=int(args.queue_size),
        max_packets=args.max_packets,
        duration_s=args.duration,
        title=str(args.title),
        quiet=bool(args.quiet),
        buffer_config=DashboardBufferConfig(
            wave_points=int(args.wave_points),
            spectrum_frames=int(args.spectrum_frames),
            metrics_points=int(args.metrics_points),
            status_points=int(args.status_points),
        ),
        plot_config=PlotConfig(title=str(args.title), wave_points=int(args.wave_points)),
    )


def run_dashboard(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    app = TelemetryDashboardApp(config_from_args(args))

    def request_stop(_signum: int, _frame: object) -> None:
        app.request_stop()

    old_int = signal.getsignal(signal.SIGINT)
    old_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        app.run()
        return 0
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run_dashboard(argv)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"trecap dashboard error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


TrecapDashboardApp = TelemetryDashboardApp
TelemetryDashboardConfig = DashboardRuntimeConfig

__all__ = [
    "DashboardRunSummary",
    "DashboardRuntimeConfig",
    "LiveCommandController",
    "LiveCommandOutcome",
    "LiveCommandRequest",
    "TelemetryDashboardApp",
    "TelemetryDashboardConfig",
    "TrecapDashboardApp",
    "build_arg_parser",
    "config_from_args",
    "main",
    "run_dashboard",
]
