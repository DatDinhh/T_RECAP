"""PC-side utilities for T-RECAP Phase 2 telemetry.

This package is intentionally limited to telemetry parsing, buffering, display,
and command-client helpers. It is not a mathematical reference model and it must
not implement FFT, IFFT, mask selection, WOLA reconstruction, or signoff logic.
"""

from __future__ import annotations

from .packet_parser import (
    MetricsPayload,
    PacketFlags,
    ParsedPacket,
    PacketParserError,
    Spec64Payload,
    Spec129Payload,
    StatusPayload,
    TelemetryHeader,
    TelemetryPacketParser,
    WavePayload,
    WaveSample,
    WrapPayload,
    iter_capture_datagrams,
    parse_datagram,
    parse_capture,
    parse_header,
    sequence_gaps,
)

from .command_client import (
    CommandClient,
    CommandClientConfig,
    CommandClientError,
    CommandPacket,
    CommandResult,
    CommandSendResult,
    DryRunCommandClient,
)
from .config import (
    CaptureConfig,
    CommandDefaults,
    DashboardConfig,
    DashboardConfigError,
    DisplayConfig,
    NetworkConfig,
    load_dashboard_config,
)

__all__ = [
    "CommandClient",
    "CommandClientConfig",
    "CommandClientError",
    "CommandPacket",
    "CommandResult",
    "CommandSendResult",
    "DryRunCommandClient",
    "CaptureConfig",
    "CommandDefaults",
    "DashboardConfig",
    "DashboardConfigError",
    "DisplayConfig",
    "NetworkConfig",
    "load_dashboard_config",
    "MetricsPayload",
    "PacketFlags",
    "ParsedPacket",
    "PacketParserError",
    "Spec64Payload",
    "Spec129Payload",
    "StatusPayload",
    "TelemetryHeader",
    "TelemetryPacketParser",
    "WavePayload",
    "WaveSample",
    "WrapPayload",
    "iter_capture_datagrams",
    "parse_capture",
    "parse_datagram",
    "parse_header",
    "sequence_gaps",
]

__version__ = "0.1.0"
