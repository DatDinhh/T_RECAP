#!/usr/bin/env python3
"""Run the T-RECAP Phase 2 PC dashboard.

File class: [1] hand-written PC-side launcher.

This script loads the PC dashboard direct-link configuration, applies explicit
CLI overrides, optionally sends a small set of HPS command packets, and then
runs the UDP telemetry dashboard. It is an observability/control launcher only.
It must not implement FFT, IFFT, mask selection, WOLA reconstruction, BRAM
replay signoff, HPS DDR access, FPGA CSR mmap, or Ethernet in FPGA fabric.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import signal
import sys
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Sequence


def _repo_root() -> Path:
    """Return repository root for a checkout-style invocation."""

    return Path(__file__).resolve().parents[3]


def _pc_dashboard_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _setup_import_path() -> None:
    """Make local package and generated constants importable without install."""

    pc_root = _pc_dashboard_root()
    repo_root = _repo_root()
    for path in (pc_root, repo_root):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


_setup_import_path()

from trecap_dashboard.command_client import (  # noqa: E402
    CommandClient,
    CommandClientError,
    DryRunCommandClient,
    packet_enable_profile,
)
from trecap_dashboard.config import (  # noqa: E402
    DashboardConfig,
    DashboardConfigError,
    load_dashboard_config,
)
from trecap_dashboard.dashboard import DashboardRunSummary, TelemetryDashboardApp  # noqa: E402

DEFAULT_CONFIG = _pc_dashboard_root() / "configs" / "dashboard_direct_link.json"
DEFAULT_HPS_CONFIG = _repo_root() / "sw" / "hps" / "config" / "trecap_hps_config.json"


class RunDashboardError(RuntimeError):
    """Raised for launch/configuration failures."""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the T-RECAP Phase 2 PC dashboard for HPS UDP telemetry.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="PC dashboard JSON config; use --hps-config to derive from HPS config instead",
    )
    parser.add_argument(
        "--hps-config",
        type=Path,
        default=None,
        help="load sw/hps/config/trecap_hps_config.json style config instead of PC config",
    )
    parser.add_argument("--print-config", action="store_true", help="print resolved config and exit")
    parser.add_argument("--preflight-only", action="store_true", help="validate config/imports and exit")

    net = parser.add_argument_group("telemetry receive")
    net.add_argument("--bind-host", default=None, help="override UDP telemetry bind host")
    net.add_argument("--port", "--telemetry-port", dest="bind_port", type=int, default=None, help="override UDP telemetry port")
    net.add_argument("--expected-source", default=None, help="override expected HPS source host or HOST:PORT; empty disables filter")
    net.add_argument("--no-source-filter", action="store_true", help="accept telemetry from any source")
    net.add_argument("--allow-wrap", action="store_true", help="allow WRAP records for DDR-ring debug captures")
    net.add_argument("--no-udp-limit", action="store_true", help="disable generated UDP no-fragment limit check")

    cap = parser.add_argument_group("capture")
    cap.add_argument("--capture-write", type=Path, default=None, help="write framed UDP capture")
    cap.add_argument("--capture-read", type=Path, default=None, help="replay framed UDP capture instead of listening live")
    cap.add_argument("--capture-append", action="store_true", help="append to capture-write path when supported by config")

    disp = parser.add_argument_group("display")
    disp.add_argument("--text-only", action="store_true", help="run without matplotlib GUI")
    disp.add_argument("--gui", action="store_true", help="force GUI even if config says text-only")
    disp.add_argument("--refresh-hz", type=float, default=None, help="GUI refresh rate")
    disp.add_argument("--text-refresh-hz", type=float, default=None, help="text-mode refresh rate")
    disp.add_argument("--queue-size", type=int, default=None, help="background receiver queue size")
    disp.add_argument("--max-packets", type=int, default=None, help="exit after N parsed packets")
    disp.add_argument("--duration", type=float, default=None, help="exit after N seconds")
    disp.add_argument("--title", default=None, help="dashboard title")
    disp.add_argument("--quiet", action="store_true", help="suppress periodic text output")
    disp.add_argument("--wave-points", type=int, default=None, help="wave buffer capacity")
    disp.add_argument("--spectrum-frames", type=int, default=None, help="spectrum frame capacity")
    disp.add_argument("--spectrogram-frames", type=int, default=None, help="spectrogram history depth")
    disp.add_argument("--metrics-points", type=int, default=None, help="metrics buffer capacity")
    disp.add_argument("--status-points", type=int, default=None, help="status buffer capacity")
    disp.add_argument("--packet-summaries", type=int, default=None, help="packet summary capacity")
    disp.add_argument("--sequence-gaps", type=int, default=None, help="sequence-gap event capacity")
    disp.add_argument(
        "--packet-rate-window-s",
        type=float,
        default=None,
        help="rolling packet-rate measurement window in seconds",
    )
    disp.add_argument("--status-lines", type=int, default=None, help="maximum status-panel lines")
    disp.add_argument("--command-queue-size", type=int, default=None, help="live-command worker queue capacity")
    live = disp.add_mutually_exclusive_group()
    live.add_argument(
        "--live-controls",
        dest="live_controls",
        action="store_true",
        help="enable live HPS-mediated dashboard command controls",
    )
    live.add_argument(
        "--no-live-controls",
        dest="live_controls",
        action="store_false",
        help="disable live dashboard command controls",
    )
    parser.set_defaults(live_controls=None)

    cmd = parser.add_argument_group("HPS command path and optional pre-run commands")
    cmd.add_argument("--command-host", default=None, help="override HPS command host")
    cmd.add_argument("--command-port", type=int, default=None, help="override HPS command UDP port")
    cmd.add_argument("--command-bind-host", default=None, help="local command bind host")
    cmd.add_argument("--command-bind-port", type=int, default=None, help="local command bind port")
    cmd.add_argument("--command-timeout", type=float, default=None, help="command socket timeout seconds")
    cmd.add_argument("--command-protocol-version", type=int, choices=(1, 2), default=None, help="command protocol version")
    cmd.add_argument("--command-retries", type=int, default=None, help="v2 result retry count")
    cmd.add_argument("--dry-run-commands", action="store_true", help="validate commands without sending UDP")
    cmd.add_argument("--ping", action="store_true", help="send PING before starting dashboard")
    cmd.add_argument("--clear-metrics", action="store_true", help="send CLEAR_METRICS before starting dashboard")
    cmd.add_argument("--set-thr2", type=_int_arg, default=None, help="send SET_THR2 value")
    cmd.add_argument("--set-source-mode", type=_int_arg, default=None, help="send SET_SOURCE_MODE value")
    cmd.add_argument("--set-packet-profile", choices=["status-only", "full-demo"], default=None, help="send packet-enable profile")
    cmd.add_argument("--set-packet-enable", default=None, help="send packet-enable mask or names, e.g. 'status wave metrics spec'")
    cmd.add_argument("--set-wave-decim", type=_int_arg, default=None, help="send SET_WAVE_DECIM value")
    cmd.add_argument("--set-spec-shift", type=_int_arg, default=None, help="send SET_SPEC_SHIFT value")
    cmd.add_argument("--set-spec-mode", type=_int_arg, default=None, help="send SET_SPEC_MODE value 0..2")
    telemetry = cmd.add_mutually_exclusive_group()
    telemetry.add_argument("--enable-telemetry", action="store_true", help="transactionally enable telemetry")
    telemetry.add_argument("--disable-telemetry", action="store_true", help="transactionally disable telemetry")
    cmd.add_argument("--configure-ddr-ring", action="store_true", help="configure the trusted runtime DDR ring tuple")
    cmd.add_argument("--reset-transport", action="store_true", help="transactionally reset transport")
    cmd.add_argument("--clear-counters", action="store_true", help="clear FPGA transport diagnostic counters")
    cmd.add_argument("--start-bram-replay", action="store_true", help="request BRAM replay admission")
    cmd.add_argument("--read-status-version", action="store_true", help="read raw FPGA STATUS and VERSION")
    return parser


def _int_arg(text: str) -> int:
    return int(str(text).replace("_", ""), 0)


def _load_config(args: argparse.Namespace) -> DashboardConfig:
    if args.hps_config is not None:
        cfg = load_dashboard_config(args.hps_config)
    else:
        cfg = load_dashboard_config(args.config)
    return _apply_config_overrides(cfg, args)


def _apply_config_overrides(cfg: DashboardConfig, args: argparse.Namespace) -> DashboardConfig:
    network = cfg.network
    command = cfg.command
    capture = cfg.capture
    display = cfg.display

    if args.bind_host is not None:
        network = replace(network, bind_host=str(args.bind_host))
    if args.bind_port is not None:
        network = replace(network, bind_port=int(args.bind_port))
    if args.no_source_filter:
        network = replace(network, expected_source=None)
    elif args.expected_source is not None:
        source = str(args.expected_source).strip()
        network = replace(network, expected_source=source or None)
    if args.allow_wrap:
        network = replace(network, allow_wrap=True)
    if args.no_udp_limit:
        network = replace(network, enforce_udp_limit=False)

    if args.capture_write is not None:
        capture = replace(capture, capture_write=args.capture_write)
    if args.capture_read is not None:
        capture = replace(capture, capture_read=args.capture_read)
    if args.capture_append:
        capture = replace(capture, capture_append=True)

    if args.text_only:
        display = replace(display, text_only=True)
    if args.gui:
        display = replace(display, text_only=False)
    if args.refresh_hz is not None:
        display = replace(display, refresh_hz=float(args.refresh_hz))
    if args.text_refresh_hz is not None:
        display = replace(display, text_refresh_hz=float(args.text_refresh_hz))
    if args.queue_size is not None:
        display = replace(display, queue_size=int(args.queue_size))
    if args.max_packets is not None:
        display = replace(display, max_packets=int(args.max_packets))
    if args.duration is not None:
        display = replace(display, duration_s=float(args.duration))
    if args.title is not None:
        display = replace(display, title=str(args.title))
    if args.quiet:
        display = replace(display, quiet=True)
    if args.packet_rate_window_s is not None:
        display = replace(display, packet_rate_window_s=float(args.packet_rate_window_s))
    if args.live_controls is not None:
        display = replace(display, live_controls=bool(args.live_controls))
    for attr, cli_name in (
        ("wave_points", "wave_points"),
        ("spectrum_frames", "spectrum_frames"),
        ("spectrogram_frames", "spectrogram_frames"),
        ("metrics_points", "metrics_points"),
        ("status_points", "status_points"),
        ("packet_summaries", "packet_summaries"),
        ("sequence_gaps", "sequence_gaps"),
        ("status_lines", "status_lines"),
        ("command_queue_size", "command_queue_size"),
    ):
        value = getattr(args, cli_name)
        if value is not None:
            display = replace(display, **{attr: int(value)})

    if args.command_host is not None:
        command = replace(command, host=str(args.command_host))
    if args.command_port is not None:
        command = replace(command, port=int(args.command_port))
    if args.command_bind_host is not None:
        command = replace(command, bind_host=str(args.command_bind_host))
    if args.command_bind_port is not None:
        command = replace(command, bind_port=int(args.command_bind_port))
    if args.command_timeout is not None:
        command = replace(command, timeout_s=float(args.command_timeout))
    if args.command_protocol_version is not None:
        command = replace(command, protocol_version=int(args.command_protocol_version))
    if args.command_retries is not None:
        command = replace(command, retries=int(args.command_retries))

    out = dataclasses.replace(cfg, network=network, command=command, capture=capture, display=display)
    out.validate()
    return out


def _config_to_jsonable(cfg: DashboardConfig) -> dict[str, object]:
    data = cfg.to_dict()
    data["schema"] = "trecap_phase2_pc_dashboard_config_v1"
    data["project"] = "T_RECAP_Phase2"
    return data


def _command_requested(args: argparse.Namespace) -> bool:
    return any(
        (
            args.ping,
            args.clear_metrics,
            args.set_thr2 is not None,
            args.set_source_mode is not None,
            args.set_packet_profile is not None,
            args.set_packet_enable is not None,
            args.set_wave_decim is not None,
            args.set_spec_shift is not None,
            args.set_spec_mode is not None,
            args.enable_telemetry,
            args.disable_telemetry,
            args.configure_ddr_ring,
            args.reset_transport,
            args.clear_counters,
            args.start_bram_replay,
            args.read_status_version,
        )
    )


def _make_command_client(cfg: DashboardConfig, args: argparse.Namespace) -> CommandClient:
    """Create the one command session shared by pre-run and live controls."""

    client_cls = DryRunCommandClient if args.dry_run_commands else CommandClient
    return client_cls(cfg.to_command_client_config())


def _send_requested_commands(
    cfg: DashboardConfig,
    args: argparse.Namespace,
    *,
    command_client: CommandClient | None = None,
) -> list[str]:
    if not _command_requested(args):
        return []
    owns_client = command_client is None
    client = command_client or _make_command_client(cfg, args)
    messages: list[str] = []
    try:
        client.open()
        for result in _iter_command_results(client, args):
            prefix = "dry-run " if result.dry_run else ""
            outcome = ""
            if result.result is not None:
                outcome = (
                    f" disposition={result.result.disposition_name}"
                    f" reason={result.result.reject_reason_name}"
                    f" status=0x{result.result.fpga_status:08x}"
                    f" version=0x{result.result.csr_version:08x}"
                )
            messages.append(
                f"{prefix}sent {result.command_name} seq={result.packet.seq} "
                f"bytes={result.bytes_sent} attempts={result.attempts} "
                f"to {result.destination[0]}:{result.destination[1]}{outcome}"
            )
    except CommandClientError:
        raise
    except OSError as exc:
        raise CommandClientError(f"failed to send command UDP packet: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    return messages


def _iter_command_results(client: CommandClient, args: argparse.Namespace) -> Iterable[object]:
    if args.ping:
        yield client.ping()
    # Lifecycle commands are intentionally ordered, independent of CLI option order.
    if args.reset_transport:
        yield client.reset_transport()
    if args.configure_ddr_ring:
        yield client.configure_ddr_ring()
    if args.disable_telemetry:
        yield client.set_telemetry_enable(False)
    if args.set_thr2 is not None:
        yield client.set_thr2(int(args.set_thr2))
    if args.set_source_mode is not None:
        yield client.set_source_mode(int(args.set_source_mode))
    if args.set_packet_profile is not None:
        # Normalize once here so invalid profile names fail before any later command send.
        packet_enable_profile(str(args.set_packet_profile))
        yield client.set_packet_profile(str(args.set_packet_profile))
    if args.set_packet_enable is not None:
        value = str(args.set_packet_enable).strip()
        if value.lower().startswith("0x") or value.isdigit():
            yield client.set_packet_enable(int(value, 0))
        else:
            yield client.set_packet_enable(value)
    if args.set_wave_decim is not None:
        yield client.set_wave_decim(int(args.set_wave_decim))
    if args.set_spec_shift is not None:
        yield client.set_spec_shift(int(args.set_spec_shift))
    if args.set_spec_mode is not None:
        yield client.set_spec_mode(int(args.set_spec_mode))
    if args.clear_metrics:
        yield client.clear_metrics()
    if args.clear_counters:
        yield client.clear_counters()
    if args.start_bram_replay:
        yield client.start_bram_replay()
    if args.enable_telemetry:
        yield client.set_telemetry_enable(True)
    if args.read_status_version:
        yield client.read_status_version()


def _run_app(
    cfg: DashboardConfig,
    *,
    command_client: CommandClient | None = None,
) -> DashboardRunSummary:
    app = TelemetryDashboardApp(
        cfg.to_dashboard_runtime_config(),
        command_client=command_client,
    )

    def request_stop(_signum: int, _frame: object) -> None:
        app.request_stop()

    old_int = signal.getsignal(signal.SIGINT)
    old_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        return app.run()
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    command_client: CommandClient | None = None
    try:
        cfg = _load_config(args)
        if args.print_config:
            print(json.dumps(_config_to_jsonable(cfg), indent=2, sort_keys=True))
            return 0
        if args.preflight_only:
            if not cfg.display.quiet:
                print("dashboard preflight OK")
            return 0
        if _command_requested(args) or cfg.display.live_controls:
            command_client = _make_command_client(cfg, args)
        for message in _send_requested_commands(
            cfg,
            args,
            command_client=command_client,
        ):
            if not cfg.display.quiet:
                print(message)
        if not cfg.display.live_controls and command_client is not None:
            command_client.close()
            command_client = None
        summary = _run_app(cfg, command_client=command_client)
        if not cfg.display.quiet:
            print(
                "dashboard summary: "
                f"packets={summary.packets_ingested} parse_errors={summary.parse_errors} "
                f"queue_drops={summary.receiver_queue_drops} "
                f"sequence_gaps={summary.sequence_gaps} "
                f"missing_sequences={summary.missing_sequences} "
                f"elapsed_s={summary.elapsed_seconds:.3f}"
            )
        return 0
    except KeyboardInterrupt:
        return 130
    except (DashboardConfigError, CommandClientError, RunDashboardError, OSError, ValueError) as exc:
        print(f"run_dashboard.py: error: {exc}", file=sys.stderr)
        return 2
    finally:
        if command_client is not None:
            command_client.close()


if __name__ == "__main__":
    raise SystemExit(main())
