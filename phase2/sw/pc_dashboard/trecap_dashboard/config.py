"""PC dashboard runtime configuration helpers for T-RECAP Phase 2.

File class: [1] hand-written PC-side config helper.

This module owns dashboard process configuration only. It does not define wire
packet constants, CSR offsets, command IDs, payload sizes, or signal-processing
algorithm behavior. Wire constants come from generated headers/modules.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .command_client import CommandClientConfig

DEFAULT_PC_HOST = "192.168.10.1"
DEFAULT_HPS_HOST = "192.168.10.2"
DEFAULT_TELEMETRY_PORT = 5005
DEFAULT_COMMAND_PORT = 5006
DEFAULT_LOCAL_COMMAND_PORT = 5007
DEFAULT_BIND_HOST = "0.0.0.0"
CONFIG_SCHEMA = "trecap_phase2_pc_dashboard_config_v1"
HPS_CONFIG_SCHEMA = "trecap_phase2_hps_runtime_config_v1"


class DashboardConfigError(ValueError):
    """Raised when a PC dashboard configuration is invalid."""


@dataclass(frozen=True, slots=True)
class CommandDefaults:
    """PC-side command endpoint for the HPS command server."""

    host: str = DEFAULT_HPS_HOST
    port: int = DEFAULT_COMMAND_PORT
    bind_host: str | None = None
    bind_port: int = DEFAULT_LOCAL_COMMAND_PORT
    timeout_s: float = 1.0
    sequence_start: int = 1
    protocol_version: int = 2
    retries: int = 2

    def validate(self) -> None:
        _validate_host(self.host, "command.host")
        _validate_port(self.port, "command.port")
        if self.bind_host is not None:
            _validate_host(self.bind_host, "command.bind_host", allow_wildcard=True)
        _validate_port(self.bind_port, "command.bind_port")
        if self.timeout_s < 0.0:
            raise DashboardConfigError("command.timeout_s must be >= 0")
        _validate_u32(self.sequence_start, "command.sequence_start")
        if self.protocol_version not in (1, 2):
            raise DashboardConfigError("command.protocol_version must be 1 or 2")
        if self.retries < 0:
            raise DashboardConfigError("command.retries must be >= 0")

    def to_command_client_config(self) -> CommandClientConfig:
        return CommandClientConfig(
            host=self.host,
            port=self.port,
            bind_host=self.bind_host,
            bind_port=self.bind_port,
            timeout_s=self.timeout_s,
            sequence_start=self.sequence_start,
            protocol_version=self.protocol_version,
            retries=self.retries,
        )


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    """PC-side telemetry UDP receive endpoint."""

    bind_host: str = DEFAULT_BIND_HOST
    bind_port: int = DEFAULT_TELEMETRY_PORT
    expected_source: str | None = DEFAULT_HPS_HOST
    enforce_udp_limit: bool = True
    allow_wrap: bool = False

    def validate(self) -> None:
        _validate_host(self.bind_host, "telemetry.bind_host", allow_wildcard=True)
        _validate_port(self.bind_port, "telemetry.bind_port")
        if self.expected_source is not None:
            _validate_host(self.expected_source.split(":", 1)[0], "telemetry.expected_source")


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    """Optional capture replay/write paths."""

    capture_write: Path | None = None
    capture_read: Path | None = None
    capture_append: bool = False

    def validate(self) -> None:
        if self.capture_write is not None and self.capture_read is not None:
            raise DashboardConfigError("capture_write and capture_read cannot both be set")


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    """Dashboard display, queue, and buffer behavior."""

    text_only: bool = False
    refresh_hz: float = 20.0
    text_refresh_hz: float = 2.0
    queue_size: int = 4096
    max_packets: int | None = None
    duration_s: float | None = None
    event_budget_per_refresh: int = 2048
    title: str = "T-RECAP Phase 2 Telemetry"
    quiet: bool = False
    wave_points: int = 8192
    spectrum_frames: int = 256
    spectrogram_frames: int = 128
    metrics_points: int = 1024
    status_points: int = 512
    packet_summaries: int = 2048
    sequence_gaps: int = 256
    packet_rate_window_s: float = 1.0
    status_lines: int = 34
    show_suppression_overlay: bool = True
    live_controls: bool = True
    command_queue_size: int = 16

    def validate(self) -> None:
        if self.refresh_hz <= 0.0:
            raise DashboardConfigError("display.refresh_hz must be > 0")
        if self.text_refresh_hz <= 0.0:
            raise DashboardConfigError("display.text_refresh_hz must be > 0")
        if self.queue_size < 1:
            raise DashboardConfigError("display.queue_size must be >= 1")
        if self.max_packets is not None and self.max_packets < 1:
            raise DashboardConfigError("display.max_packets must be >= 1")
        if self.duration_s is not None and self.duration_s <= 0.0:
            raise DashboardConfigError("display.duration_s must be > 0")
        if self.event_budget_per_refresh < 1:
            raise DashboardConfigError("display.event_budget_per_refresh must be >= 1")
        if self.packet_rate_window_s <= 0.0:
            raise DashboardConfigError("display.packet_rate_window_s must be > 0")
        if not isinstance(self.live_controls, bool):
            raise DashboardConfigError("display.live_controls must be boolean")
        if not isinstance(self.show_suppression_overlay, bool):
            raise DashboardConfigError(
                "display.show_suppression_overlay must be boolean"
            )
        for name in (
            "wave_points",
            "spectrum_frames",
            "spectrogram_frames",
            "metrics_points",
            "status_points",
            "packet_summaries",
            "sequence_gaps",
            "status_lines",
            "command_queue_size",
        ):
            if int(getattr(self, name)) < 1:
                raise DashboardConfigError(f"display.{name} must be >= 1")


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    """Complete PC dashboard runtime configuration."""

    network: NetworkConfig = NetworkConfig()
    command: CommandDefaults = CommandDefaults()
    capture: CaptureConfig = CaptureConfig()
    display: DisplayConfig = DisplayConfig()
    source_path: Path | None = None

    def validate(self) -> None:
        self.network.validate()
        self.command.validate()
        self.capture.validate()
        self.display.validate()

    def to_dashboard_runtime_config(self) -> object:
        from .dashboard import DashboardRuntimeConfig
        from .plots import PlotConfig
        try:
            from .ring_buffers import DashboardBufferConfig
        except ImportError:
            from .ring_buffers import DashboardRingBufferConfig as DashboardBufferConfig

        plot_kwargs = {
            "title": self.display.title,
            "wave_points": self.display.wave_points,
        }
        # Newer PlotConfig variants may accept these; older v36 accepts only the keys above.
        if "metrics_points" in getattr(PlotConfig, "__dataclass_fields__", {}):
            plot_kwargs["metrics_points"] = self.display.metrics_points
        if "spectrogram_frames" in getattr(PlotConfig, "__dataclass_fields__", {}):
            plot_kwargs["spectrogram_frames"] = self.display.spectrogram_frames
        if "status_lines" in getattr(PlotConfig, "__dataclass_fields__", {}):
            plot_kwargs["status_lines"] = self.display.status_lines
        if "show_suppression_overlay" in getattr(
            PlotConfig, "__dataclass_fields__", {}
        ):
            plot_kwargs["show_suppression_overlay"] = (
                self.display.show_suppression_overlay
            )
        if "spectrum_bins" in getattr(PlotConfig, "__dataclass_fields__", {}):
            plot_kwargs["spectrum_bins"] = 129

        return DashboardRuntimeConfig(
            bind_host=self.network.bind_host,
            bind_port=self.network.bind_port,
            expected_source=self.network.expected_source,
            capture_write=self.capture.capture_write,
            capture_read=self.capture.capture_read,
            capture_append=self.capture.capture_append,
            allow_wrap=self.network.allow_wrap,
            enforce_udp_limit=self.network.enforce_udp_limit,
            text_only=self.display.text_only,
            refresh_hz=self.display.refresh_hz,
            text_refresh_hz=self.display.text_refresh_hz,
            queue_size=self.display.queue_size,
            max_packets=self.display.max_packets,
            duration_s=self.display.duration_s,
            event_budget_per_refresh=self.display.event_budget_per_refresh,
            title=self.display.title,
            quiet=self.display.quiet,
            command_config=self.command.to_command_client_config(),
            live_controls=self.display.live_controls,
            command_queue_size=self.display.command_queue_size,
            buffer_config=DashboardBufferConfig(
                wave_points=self.display.wave_points,
                spectrum_frames=self.display.spectrum_frames,
                metrics_points=self.display.metrics_points,
                status_points=self.display.status_points,
                packet_summaries=self.display.packet_summaries,
                sequence_gaps=self.display.sequence_gaps,
                packet_rate_window_s=self.display.packet_rate_window_s,
            ),
            plot_config=PlotConfig(**plot_kwargs),
        )

    def to_command_client_config(self) -> CommandClientConfig:
        return self.command.to_command_client_config()

    def to_dict(self) -> dict[str, Any]:
        return _path_to_string(asdict(self))


PcDashboardConfig = DashboardConfig
TelemetryReceiverConfig = NetworkConfig
CommandEndpointConfig = CommandDefaults


def load_dashboard_config(path: str | Path | None = None) -> DashboardConfig:
    """Load dashboard config from JSON or fallback to safe direct-link defaults."""

    if path is None:
        found = _find_default_config()
        if found is None:
            cfg = DashboardConfig()
            cfg.validate()
            return cfg
        path_obj = found
    else:
        path_obj = Path(path)
    data = json.loads(path_obj.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise DashboardConfigError("dashboard config root must be a JSON object")
    cfg = _from_mapping(data, path_obj)
    cfg.validate()
    return cfg


def save_example_config(path: str | Path) -> None:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    cfg = DashboardConfig()
    payload = cfg.to_dict()
    payload["schema"] = CONFIG_SCHEMA
    payload["project"] = "T_RECAP_Phase2"
    path_obj.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _find_default_config() -> Path | None:
    root = Path(__file__).resolve().parents[3]
    for rel in (
        "sw/pc_dashboard/configs/dashboard_direct_link.json",
        "sw/hps/config/trecap_hps_config.json",
    ):
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def _from_mapping(data: Mapping[str, Any], path: Path) -> DashboardConfig:
    if data.get("schema") == HPS_CONFIG_SCHEMA or "hps_static_ip" in data:
        return _from_hps_mapping(data, path)
    network_data = _mapping(data.get("network") or data.get("telemetry"), "network")
    command_data = _mapping(data.get("command"), "command")
    capture_data = _mapping(data.get("capture"), "capture")
    display_data = _mapping(data.get("display"), "display")
    return DashboardConfig(
        network=NetworkConfig(
            bind_host=_str(network_data, "bind_host", DEFAULT_BIND_HOST) or DEFAULT_BIND_HOST,
            bind_port=_int(network_data, "bind_port", DEFAULT_TELEMETRY_PORT),
            expected_source=_optional_str(network_data.get("expected_source", DEFAULT_HPS_HOST)),
            enforce_udp_limit=_bool(network_data, "enforce_udp_limit", True),
            allow_wrap=_bool(network_data, "allow_wrap", False),
        ),
        command=CommandDefaults(
            host=_str(command_data, "host", DEFAULT_HPS_HOST) or DEFAULT_HPS_HOST,
            port=_int(command_data, "port", DEFAULT_COMMAND_PORT),
            bind_host=_optional_str(command_data.get("bind_host")),
            bind_port=_int(command_data, "bind_port", DEFAULT_LOCAL_COMMAND_PORT),
            timeout_s=_float(command_data, "timeout_s", 1.0),
            sequence_start=_int(command_data, "sequence_start", 1),
            protocol_version=_int(command_data, "protocol_version", 2),
            retries=_int(command_data, "retries", 2),
        ),
        capture=CaptureConfig(
            capture_write=_optional_path(capture_data.get("capture_write")),
            capture_read=_optional_path(capture_data.get("capture_read")),
            capture_append=_bool(capture_data, "capture_append", False),
        ),
        display=DisplayConfig(
            text_only=_bool(display_data, "text_only", False),
            refresh_hz=_float(display_data, "refresh_hz", 20.0),
            text_refresh_hz=_float(display_data, "text_refresh_hz", 2.0),
            queue_size=_int(display_data, "queue_size", 4096),
            max_packets=_optional_int(display_data.get("max_packets")),
            duration_s=_optional_float(display_data.get("duration_s")),
            event_budget_per_refresh=_int(display_data, "event_budget_per_refresh", 2048),
            title=_str(display_data, "title", "T-RECAP Phase 2 Telemetry") or "T-RECAP Phase 2 Telemetry",
            quiet=_bool(display_data, "quiet", False),
            wave_points=_int(display_data, "wave_points", 8192),
            spectrum_frames=_int(display_data, "spectrum_frames", 256),
            spectrogram_frames=_int(display_data, "spectrogram_frames", 128),
            metrics_points=_int(display_data, "metrics_points", 1024),
            status_points=_int(display_data, "status_points", 512),
            packet_summaries=_int(display_data, "packet_summaries", 2048),
            sequence_gaps=_int(display_data, "sequence_gaps", 256),
            packet_rate_window_s=_float(display_data, "packet_rate_window_s", 1.0),
            status_lines=_int(display_data, "status_lines", 34),
            show_suppression_overlay=_bool(
                display_data,
                "show_suppression_overlay",
                True,
            ),
            live_controls=_bool(display_data, "live_controls", True),
            command_queue_size=_int(display_data, "command_queue_size", 16),
        ),
        source_path=path,
    )


def _from_hps_mapping(data: Mapping[str, Any], path: Path) -> DashboardConfig:
    hps_host = _str(data, "hps_static_ip", DEFAULT_HPS_HOST) or DEFAULT_HPS_HOST
    return DashboardConfig(
        network=NetworkConfig(
            bind_host=DEFAULT_BIND_HOST,
            bind_port=_int(data, "telemetry_dst_port", DEFAULT_TELEMETRY_PORT),
            expected_source=hps_host,
        ),
        command=CommandDefaults(
            host=hps_host,
            port=_int(data, "command_listen_port", DEFAULT_COMMAND_PORT),
            bind_host=_str(data, "pc_static_ip", "192.168.10.1"),
        ),
        source_path=path,
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise DashboardConfigError(f"{name} must be a JSON object")
    return value


def _str(data: Mapping[str, Any], key: str, default: str | None) -> str | None:
    return _optional_str(data.get(key, default))


def _bool(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise DashboardConfigError(f"{key} must be boolean")
    return value


def _int(data: Mapping[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    return _parse_int(value, key)


def _float(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise DashboardConfigError(f"{key} must be numeric")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _parse_int(value, "optional integer")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise DashboardConfigError("optional float must be numeric")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DashboardConfigError("string field must be a string or null")
    text = value.strip()
    return text if text else None


def _optional_path(value: object) -> Path | None:
    text = _optional_str(value)
    return None if text is None else Path(text)


def _parse_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise DashboardConfigError(f"{name} must not be bool")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        return int(value.replace("_", ""), 0)
    raise DashboardConfigError(f"{name} must be integer or integer string")


def _validate_port(value: int, name: str, *, allow_zero: bool = False) -> None:
    low = 0 if allow_zero else 1
    if not (low <= int(value) <= 65535):
        raise DashboardConfigError(f"{name} must be in range {low}..65535")


def _validate_host(value: str, name: str, *, allow_wildcard: bool = False) -> None:
    text = str(value).strip()
    if not text:
        raise DashboardConfigError(f"{name} must not be empty")
    if any(ch.isspace() for ch in text):
        raise DashboardConfigError(f"{name} must not contain whitespace")
    if text in {"0.0.0.0", "::"} and not allow_wildcard:
        raise DashboardConfigError(f"{name} must not be wildcard")


def _validate_u32(value: int, name: str) -> None:
    if not (0 <= int(value) <= 0xFFFF_FFFF):
        raise DashboardConfigError(f"{name} must fit uint32")


def _path_to_string(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _path_to_string(v) for k, v in value.items() if k != "source_path"}
    if isinstance(value, list):
        return [_path_to_string(v) for v in value]
    return value


__all__ = [
    "CaptureConfig",
    "CommandDefaults",
    "DashboardConfig",
    "DashboardConfigError",
    "DisplayConfig",
    "NetworkConfig",
    "PcDashboardConfig",
    "TelemetryReceiverConfig",
    "load_dashboard_config",
    "save_example_config",
]
