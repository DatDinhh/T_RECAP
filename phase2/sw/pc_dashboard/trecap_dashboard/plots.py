"""Plot and text rendering for the T-RECAP Phase 2 PC dashboard.

This module renders already-decoded telemetry. Spectrum history is display
data, not a PC-side FFT, and all command widgets only enqueue explicit actions
through a callback owned by dashboard.py.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .ring_buffers import DashboardSnapshot, MetricsPoint, SpectrumFrame, StatusPoint, WavePoint

DEFAULT_WAVE_POINTS = 1024
DEFAULT_METRICS_POINTS = 256
DEFAULT_SPECTROGRAM_FRAMES = 128
DEFAULT_STATUS_LINES = 34
CommandSubmitter = Callable[[str, int | str | bool | None], bool]


class PlotDependencyError(RuntimeError):
    """Raised when optional GUI dependencies are unavailable."""


def require_matplotlib() -> tuple[Any, Any]:
    """Import matplotlib lazily so parser/headless imports stay dependency-free."""

    try:
        import matplotlib.pyplot as plt  # type: ignore
        from matplotlib.figure import Figure  # type: ignore
    except Exception as exc:
        raise PlotDependencyError(
            "matplotlib is required for the graphical dashboard; install with "
            "pip install -e sw/pc_dashboard[gui] or run with --text-only"
        ) from exc
    return plt, Figure


@dataclass(frozen=True, slots=True)
class PlotConfig:
    """PC-only display configuration; no field is a wire or DSP constant."""

    title: str = "T-RECAP Phase 2 Telemetry"
    wave_points: int = DEFAULT_WAVE_POINTS
    metrics_points: int = DEFAULT_METRICS_POINTS
    spectrogram_frames: int = DEFAULT_SPECTROGRAM_FRAMES
    spectrum_bins: int = 129
    status_lines: int = DEFAULT_STATUS_LINES
    show_grid: bool = True
    show_suppression_overlay: bool = True

    def validate(self) -> None:
        for name in (
            "wave_points",
            "metrics_points",
            "spectrogram_frames",
            "spectrum_bins",
            "status_lines",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be >= 1")


@dataclass(frozen=True, slots=True)
class WaveSeries:
    sample_index: tuple[int, ...]
    xdel: tuple[int, ...]
    yout: tuple[int, ...]
    err: tuple[int, ...]

    @property
    def empty(self) -> bool:
        return not self.sample_index


@dataclass(frozen=True, slots=True)
class MetricsSeries:
    frame_idx: tuple[int, ...]
    kept_energy_ratio: tuple[float, ...]
    suppressed_bin_ratio: tuple[float, ...]
    max_abs_err: tuple[int, ...]

    @property
    def empty(self) -> bool:
        return not self.frame_idx


@dataclass(frozen=True, slots=True)
class SpectrogramMatrix:
    """Rectangular, latest-mode spectrum history for one heatmap."""

    frame_idx: tuple[int, ...]
    bin_indices: tuple[int, ...]
    values: tuple[tuple[float, ...], ...]
    suppression: tuple[tuple[float, ...], ...]
    packet_name: str
    spec_shift: int

    @property
    def empty(self) -> bool:
        return not self.frame_idx or not self.bin_indices


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    total_packets: int
    total_wave_points: int
    packet_rate_hz: float
    total_sequence_gaps: int
    total_missing_sequences: int
    total_duplicate_sequences: int
    total_reordered_sequences: int
    total_payload_truncated_packets: int
    packets_by_type: dict[str, int]
    latest_packet: str
    latest_status: StatusPoint | None
    latest_metrics: MetricsPoint | None
    latest_spectrum: SpectrumFrame | None

    def lines(self) -> tuple[str, ...]:
        rows = [
            "T-RECAP Phase 2 PC dashboard",
            f"wall time              : {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"packet rate            : {self.packet_rate_hz:.1f} packets/s",
            f"packets / wave points  : {self.total_packets} / {self.total_wave_points}",
            f"PC display seq gaps    : {self.total_sequence_gaps}",
            f"PC display missing seq : {self.total_missing_sequences}",
            f"duplicates / reordered : {self.total_duplicate_sequences} / {self.total_reordered_sequences}",
            f"wire payload truncated : {self.total_payload_truncated_packets}",
            f"latest packet          : {self.latest_packet}",
        ]
        if self.packets_by_type:
            rows.append(f"packet types           : {_format_counts(self.packets_by_type)}")
        if self.latest_status is None:
            rows.append("latest STATUS          : not received")
        else:
            rows.extend(_status_lines(self.latest_status))
        if self.latest_metrics is not None:
            rows.extend(_metrics_lines(self.latest_metrics))
        if self.latest_spectrum is not None:
            rows.extend(_spectrum_lines(self.latest_spectrum))
        return tuple(rows)

    def text(self, *, max_lines: int = DEFAULT_STATUS_LINES) -> str:
        return "\n".join(self.lines()[: int(max_lines)])


class DashboardPlotter:
    """Fixed-rate matplotlib renderer with nonblocking live-control widgets."""

    def __init__(self, config: PlotConfig | None = None) -> None:
        self.config = config or PlotConfig()
        self.config.validate()
        self._plt: Any | None = None
        self.figure: Any | None = None
        self.axes: dict[str, Any] = {}
        self.widgets: dict[str, Any] = {}
        self._widget_axes: list[Any] = []
        self.update_count = 0
        self._command_submitter: CommandSubmitter | None = None
        self._command_status = "live controls disabled"
        self._show_suppression_overlay = bool(self.config.show_suppression_overlay)

    def set_command_submitter(self, submitter: CommandSubmitter | None) -> None:
        self._command_submitter = submitter

    def set_command_status(self, status: str) -> None:
        self._command_status = str(status)

    def submit_control(
        self,
        action: str,
        value: int | str | bool | None = None,
    ) -> bool:
        if self._command_submitter is None:
            self.set_command_status("live controls unavailable")
            return False
        try:
            accepted = bool(self._command_submitter(action, value))
        except Exception as exc:
            self.set_command_status(f"{action} callback failed: {exc}")
            return False
        if not accepted:
            self.set_command_status(f"{action} not queued")
        return accepted

    def open(self) -> None:
        if self.figure is not None:
            return
        plt, _ = require_matplotlib()
        self._plt = plt
        self.figure = plt.figure(num=self.config.title, figsize=(16, 10))
        self.figure.subplots_adjust(
            left=0.055,
            right=0.985,
            top=0.93,
            bottom=0.205 if self._command_submitter is not None else 0.075,
            wspace=0.30,
            hspace=0.48,
        )
        grid = self.figure.add_gridspec(3, 3)
        self.axes = {
            "wave": self.figure.add_subplot(grid[0, 0:2]),
            "error": self.figure.add_subplot(grid[0, 2]),
            "spectrum": self.figure.add_subplot(grid[1, 0]),
            "spectrogram": self.figure.add_subplot(grid[1, 1:3]),
            "metrics": self.figure.add_subplot(grid[2, 0]),
            "status": self.figure.add_subplot(grid[2, 1:3]),
        }
        self.figure.suptitle(self.config.title)
        self.axes["status"].axis("off")
        self._initialize_axes()
        if self._command_submitter is not None:
            self._install_command_controls()

    def close(self) -> None:
        if self._plt is not None and self.figure is not None:
            self._plt.close(self.figure)
        self.figure = None
        self.axes = {}
        self.widgets = {}
        self._widget_axes = []

    def show(self) -> None:
        self.open()
        assert self._plt is not None
        self._plt.show()

    def pause(self, seconds: float) -> None:
        self.open()
        assert self._plt is not None
        self._plt.pause(float(seconds))

    def update(
        self,
        snapshot: DashboardSnapshot,
        *,
        receiver_stats: Any | None = None,
        queue_drop_count: int = 0,
    ) -> None:
        self.open()
        assert self.figure is not None
        plot_waveform(
            self.axes["wave"],
            snapshot.wave,
            max_points=self.config.wave_points,
            show_grid=self.config.show_grid,
            include_error=False,
        )
        plot_wave_error(
            self.axes["error"],
            snapshot.wave,
            max_points=self.config.wave_points,
            show_grid=self.config.show_grid,
        )
        plot_spectrum(
            self.axes["spectrum"],
            latest_spectrum(snapshot),
            show_grid=self.config.show_grid,
            show_suppression_overlay=self._show_suppression_overlay,
        )
        plot_spectrogram(
            self.axes["spectrogram"],
            snapshot.spectra,
            max_frames=self.config.spectrogram_frames,
            max_bins=self.config.spectrum_bins,
            show_suppression_overlay=self._show_suppression_overlay,
        )
        plot_metrics(
            self.axes["metrics"],
            snapshot.metrics,
            max_points=self.config.metrics_points,
            show_grid=self.config.show_grid,
        )
        plot_status_panel(
            self.axes["status"],
            snapshot,
            receiver_stats=receiver_stats,
            queue_drop_count=queue_drop_count,
            command_status=self._command_status,
            max_lines=self.config.status_lines,
        )
        self.update_count += 1
        self.figure.canvas.draw_idle()

    def _initialize_axes(self) -> None:
        for name in ("wave", "error", "spectrum", "spectrogram", "metrics"):
            if self.config.show_grid:
                self.axes[name].grid(True)
        self.axes["wave"].set_title("WAVE x[n-D] and y[n]")
        self.axes["error"].set_title("WAVE error e[n]")
        self.axes["spectrum"].set_title("Latest spectrum")
        self.axes["spectrogram"].set_title("Spectrum history")
        self.axes["metrics"].set_title("METRICS ratios")
        self.axes["status"].set_title("Live STATUS / health / command result")

    def _install_command_controls(self) -> None:
        assert self.figure is not None
        try:
            from matplotlib.widgets import Button, CheckButtons, TextBox  # type: ignore
        except Exception as exc:
            raise PlotDependencyError("matplotlib widgets are required for live controls") from exc

        buttons: tuple[tuple[str, str, int | str | bool | None], ...] = (
            ("Ping", "PING", None),
            ("Enable", "SET_TELEMETRY_ENABLE", True),
            ("Disable", "SET_TELEMETRY_ENABLE", False),
            ("Full", "SET_PACKET_ENABLE", "full-demo"),
            ("Status only", "SET_PACKET_ENABLE", "status-only"),
            ("Clear metrics", "CLEAR_METRICS", None),
            ("Clear ctrs", "CLEAR_COUNTERS", None),
            ("Read status", "READ_STATUS_VERSION", None),
            ("RESET", "RESET_TRANSPORT", None),
            ("Config DDR", "CONFIGURE_DDR_RING", None),
            ("BRAM replay", "START_BRAM_REPLAY", None),
        )
        left = 0.018
        right = 0.982
        gap = 0.004
        width = (right - left - gap * (len(buttons) - 1)) / len(buttons)
        for index, (label, action, value) in enumerate(buttons):
            ax = self.figure.add_axes([left + index * (width + gap), 0.025, width, 0.038])
            button = Button(ax, label)
            button.on_clicked(
                lambda _event, cmd=action, arg=value: self.submit_control(cmd, arg)
            )
            self.widgets[f"button_{action}_{index}"] = button
            self._widget_axes.append(ax)

        text_controls = (
            ("THR2", "SET_THR2", "0x0"),
            ("Source 0..3", "SET_SOURCE_MODE", "0"),
            ("Wave decim", "SET_WAVE_DECIM", "1"),
            ("Spec mode", "SET_SPEC_MODE", "1"),
            ("Spec shift", "SET_SPEC_SHIFT", "0"),
        )
        text_left = 0.12
        text_right = 0.97
        text_gap = 0.055
        text_width = (text_right - text_left - text_gap * (len(text_controls) - 1)) / len(
            text_controls
        )
        for index, (label, action, initial) in enumerate(text_controls):
            ax = self.figure.add_axes(
                [text_left + index * (text_width + text_gap), 0.105, text_width, 0.035]
            )
            box = TextBox(ax, f"{label}: ", initial=initial)
            box.on_submit(
                lambda text, cmd=action, field=label: self._submit_text_value(
                    cmd,
                    field,
                    text,
                )
            )
            self.widgets[f"text_{action}"] = box
            self._widget_axes.append(ax)

        overlay_ax = self.figure.add_axes([0.018, 0.095, 0.052, 0.055])
        overlay = CheckButtons(
            overlay_ax,
            ["Overlay"],
            [self._show_suppression_overlay],
        )
        overlay.on_clicked(self._toggle_suppression_overlay)
        self.widgets["check_suppression_overlay"] = overlay
        self._widget_axes.append(overlay_ax)

    def _submit_text_value(self, action: str, field: str, text: str) -> None:
        try:
            value = int(str(text).strip().replace("_", ""), 0)
        except ValueError:
            self.set_command_status(f"{field}: invalid integer")
            return
        self.submit_control(action, value)

    def _toggle_suppression_overlay(self, _label: str) -> None:
        self._show_suppression_overlay = not self._show_suppression_overlay
        if self.figure is not None:
            self.figure.canvas.draw_idle()


class HeadlessDashboardRenderer:
    """Text renderer for SSH and dependency-free host regression."""

    def __init__(self, config: PlotConfig | None = None) -> None:
        self.config = config or PlotConfig()
        self.config.validate()

    def render(
        self,
        snapshot: DashboardSnapshot,
        *,
        receiver_stats: Any | None = None,
        queue_drop_count: int = 0,
        command_status: str | None = None,
    ) -> str:
        return format_status_text(
            snapshot,
            receiver_stats=receiver_stats,
            queue_drop_count=queue_drop_count,
            command_status=command_status,
            max_lines=self.config.status_lines,
        )


def latest_status(snapshot: DashboardSnapshot) -> StatusPoint | None:
    return snapshot.status[-1] if snapshot.status else None


def latest_metrics(snapshot: DashboardSnapshot) -> MetricsPoint | None:
    return snapshot.metrics[-1] if snapshot.metrics else None


def latest_spectrum(snapshot: DashboardSnapshot) -> SpectrumFrame | None:
    return snapshot.spectra[-1] if snapshot.spectra else None


def summarize_snapshot(snapshot: DashboardSnapshot) -> SnapshotSummary:
    latest_packet = snapshot.packets[-1].packet_name if snapshot.packets else "none"
    return SnapshotSummary(
        total_packets=int(snapshot.total_packets),
        total_wave_points=int(snapshot.total_wave_points),
        packet_rate_hz=float(getattr(snapshot, "packet_rate_hz", 0.0)),
        total_sequence_gaps=int(snapshot.total_sequence_gaps),
        total_missing_sequences=int(snapshot.total_missing_sequences),
        total_duplicate_sequences=int(
            getattr(snapshot, "total_duplicate_sequences", 0)
        ),
        total_reordered_sequences=int(
            getattr(snapshot, "total_reordered_sequences", 0)
        ),
        total_payload_truncated_packets=int(
            getattr(snapshot, "total_payload_truncated_packets", 0)
        ),
        packets_by_type=dict(snapshot.packets_by_type),
        latest_packet=latest_packet,
        latest_status=latest_status(snapshot),
        latest_metrics=latest_metrics(snapshot),
        latest_spectrum=latest_spectrum(snapshot),
    )


def wave_series(points: Sequence[WavePoint], *, max_points: int | None = None) -> WaveSeries:
    data = _tail(points, max_points)
    return WaveSeries(
        sample_index=tuple(point.sample_index for point in data),
        xdel=tuple(point.xdel for point in data),
        yout=tuple(point.yout for point in data),
        err=tuple(point.err for point in data),
    )


def metrics_series(points: Sequence[MetricsPoint], *, max_points: int | None = None) -> MetricsSeries:
    data = _tail(points, max_points)
    return MetricsSeries(
        frame_idx=tuple(point.frame_idx for point in data),
        kept_energy_ratio=tuple(_nan_if_none(point.kept_energy_ratio) for point in data),
        suppressed_bin_ratio=tuple(
            _nan_if_none(point.suppressed_bin_ratio) for point in data
        ),
        max_abs_err=tuple(point.max_abs_err for point in data),
    )


def spectrogram_matrix(
    frames: Sequence[SpectrumFrame],
    *,
    max_frames: int = DEFAULT_SPECTROGRAM_FRAMES,
    max_bins: int = 129,
) -> SpectrogramMatrix:
    """Return the latest contiguous same-format spectrum epoch.

    A SPEC64/SPEC129 or shift transition starts a new display epoch. This keeps
    the heatmap rectangular without inventing resampling semantics.
    """

    if max_frames < 1 or max_bins < 1:
        raise ValueError("max_frames and max_bins must be >= 1")
    if not frames:
        return SpectrogramMatrix((), (), (), (), "none", 0)
    latest = frames[-1]
    selected: list[SpectrumFrame] = []
    for frame in reversed(frames):
        if (
            frame.packet_name != latest.packet_name
            or frame.bin_count != latest.bin_count
            or int(frame.spec_shift) != int(latest.spec_shift)
        ):
            break
        selected.append(frame)
        if len(selected) >= int(max_frames):
            break
    selected.reverse()
    width = min(int(max_bins), int(latest.bin_count))
    values: list[tuple[float, ...]] = []
    suppression: list[tuple[float, ...]] = []
    for frame in selected:
        values.append(tuple(float(max(0, int(value))) for value in frame.magnitudes[:width]))
        if frame.mask_bits is not None:
            suppression.append(
                tuple(1.0 if bool(value) else 0.0 for value in frame.mask_bits[:width])
            )
        elif frame.suppressed_count is not None and frame.eligible_count is not None:
            row: list[float] = []
            for suppressed, eligible in zip(
                frame.suppressed_count[:width],
                frame.eligible_count[:width],
            ):
                row.append(
                    math.nan
                    if int(eligible) == 0
                    else float(suppressed) / float(eligible)
                )
            suppression.append(tuple(row))
        else:
            suppression.append(tuple(math.nan for _ in range(width)))
    return SpectrogramMatrix(
        frame_idx=tuple(int(frame.frame_idx) for frame in selected),
        bin_indices=tuple(range(width)),
        values=tuple(values),
        suppression=tuple(suppression),
        packet_name=str(latest.packet_name),
        spec_shift=int(latest.spec_shift),
    )


def format_status_text(
    snapshot: DashboardSnapshot,
    *,
    receiver_stats: Any | None = None,
    queue_drop_count: int = 0,
    command_status: str | None = None,
    max_lines: int = DEFAULT_STATUS_LINES,
) -> str:
    summary = summarize_snapshot(snapshot)
    rows = [
        "T-RECAP Phase 2 PC dashboard",
        f"packet rate / packets : {summary.packet_rate_hz:.1f} packets/s / {summary.total_packets}",
        f"wave points           : {summary.total_wave_points}",
        (
            "PC gaps/missing       : "
            f"{summary.total_sequence_gaps} / {summary.total_missing_sequences}"
        ),
        (
            "PC duplicate/reorder  : "
            f"{summary.total_duplicate_sequences} / {summary.total_reordered_sequences}"
        ),
        f"wire payload truncated: {summary.total_payload_truncated_packets}",
        f"packet types          : {_format_counts(summary.packets_by_type) or 'none'}",
        (
            "malformed/truncated   : "
            + _malformed_truncated_state(
                summary.latest_status,
                snapshot,
                receiver_stats,
            )
        ),
    ]
    if summary.latest_status is None:
        rows.append("latest STATUS         : not received")
    else:
        rows.extend(_status_lines(summary.latest_status))
    if command_status is not None:
        rows.append(f"last command          : {command_status}")
    rows.extend(_receiver_lines(receiver_stats, queue_drop_count=queue_drop_count))
    if summary.latest_metrics is not None:
        rows.extend(_metrics_lines(summary.latest_metrics))
    if summary.latest_spectrum is not None:
        rows.extend(_spectrum_lines(summary.latest_spectrum))
    return "\n".join(rows[: int(max_lines)])


def plot_waveform(
    ax: Any,
    points: Sequence[WavePoint],
    *,
    max_points: int = DEFAULT_WAVE_POINTS,
    show_grid: bool = True,
    include_error: bool = True,
) -> None:
    data = wave_series(points, max_points=max_points)
    ax.clear()
    ax.set_title("WAVE x[n-D], y[n]" + (", error" if include_error else ""))
    ax.set_xlabel("sample index")
    ax.set_ylabel("int16 sample")
    if show_grid:
        ax.grid(True)
    if data.empty:
        _empty_axis(ax, "no WAVE packets")
        return
    ax.plot(data.sample_index, data.xdel, label="x[n-D]")
    ax.plot(data.sample_index, data.yout, label="y[n]")
    if include_error:
        ax.plot(data.sample_index, data.err, label="error")
    ax.legend(loc="best", fontsize="small")


def plot_wave_error(
    ax: Any,
    points: Sequence[WavePoint],
    *,
    max_points: int = DEFAULT_WAVE_POINTS,
    show_grid: bool = True,
) -> None:
    data = wave_series(points, max_points=max_points)
    ax.clear()
    ax.set_title("Error e[n] = x[n-D] - y[n]")
    ax.set_xlabel("sample index")
    ax.set_ylabel("int16 error")
    if show_grid:
        ax.grid(True)
    if data.empty:
        _empty_axis(ax, "no WAVE packets")
        return
    ax.plot(data.sample_index, data.err, color="tab:red", label="e[n]")
    ax.axhline(0, color="black", linewidth=0.6)
    ax.legend(loc="best", fontsize="small")


def _spectrum_suppression(frame: SpectrumFrame) -> tuple[float, ...]:
    if frame.mask_bits is not None:
        return tuple(1.0 if value else 0.0 for value in frame.mask_bits)
    if frame.suppressed_count is not None and frame.eligible_count is not None:
        return tuple(
            math.nan if int(eligible) == 0 else float(suppressed) / float(eligible)
            for suppressed, eligible in zip(frame.suppressed_count, frame.eligible_count)
        )
    return tuple(math.nan for _ in frame.magnitudes)


def plot_spectrum(
    ax: Any,
    spectrum: SpectrumFrame | None,
    *,
    show_grid: bool = True,
    show_suppression_overlay: bool = True,
) -> None:
    ax.clear()
    ax.set_title("Latest spectrum")
    ax.set_xlabel("bin / bucket")
    ax.set_ylabel("compressed magnitude")
    if show_grid:
        ax.grid(True)
    if spectrum is None:
        _empty_axis(ax, "no SPEC packets")
        return
    bins = tuple(range(len(spectrum.magnitudes)))
    ax.set_title(f"{spectrum.packet_name} frame={spectrum.frame_idx} shift={spectrum.spec_shift}")
    ax.plot(bins, spectrum.magnitudes, label="magnitude")
    suppression = _spectrum_suppression(spectrum)
    marked = (
        [
            index
            for index, value in enumerate(suppression)
            if math.isfinite(value) and value > 0.0
        ]
        if show_suppression_overlay
        else []
    )
    if marked:
        ax.scatter(
            marked,
            [spectrum.magnitudes[index] for index in marked],
            marker="x",
            color="tab:red",
            label="suppressed",
        )
    ax.legend(loc="best", fontsize="small")


def plot_spectrogram(
    ax: Any,
    frames: Sequence[SpectrumFrame],
    *,
    max_frames: int = DEFAULT_SPECTROGRAM_FRAMES,
    max_bins: int = 129,
    show_suppression_overlay: bool = True,
) -> None:
    matrix = spectrogram_matrix(frames, max_frames=max_frames, max_bins=max_bins)
    ax.clear()
    ax.set_title("Spectrum history")
    ax.set_xlabel("bin / bucket")
    ax.set_ylabel("frame index")
    if matrix.empty:
        _empty_axis(ax, "no SPEC history")
        return
    image = ax.imshow(
        matrix.values,
        aspect="auto",
        origin="lower",
        interpolation="nearest",
        cmap="viridis",
    )
    ax.set_title(
        f"{matrix.packet_name} spectrogram shift={matrix.spec_shift} "
        f"frames={len(matrix.frame_idx)}"
    )
    tick_count = min(6, len(matrix.frame_idx))
    if tick_count > 0:
        positions = sorted(
            {
                round(index * (len(matrix.frame_idx) - 1) / max(1, tick_count - 1))
                for index in range(tick_count)
            }
        )
        ax.set_yticks(positions, [str(matrix.frame_idx[index]) for index in positions])
    overlay_x: list[int] = []
    overlay_y: list[int] = []
    overlay_size: list[float] = []
    for row_index, row in enumerate(matrix.suppression):
        for bin_index, value in enumerate(row):
            if math.isfinite(value) and value > 0.0:
                overlay_x.append(bin_index)
                overlay_y.append(row_index)
                overlay_size.append(3.0 + 12.0 * min(1.0, value))
    if show_suppression_overlay and overlay_x:
        ax.scatter(
            overlay_x,
            overlay_y,
            s=overlay_size,
            marker=".",
            color="white",
            alpha=0.55,
            linewidths=0,
            label="suppression",
        )
    colorbar = getattr(ax.figure, "_trecap_spectrogram_colorbar", None)
    if colorbar is None:
        colorbar = ax.figure.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
        colorbar.set_label("compressed magnitude")
        setattr(ax.figure, "_trecap_spectrogram_colorbar", colorbar)
    else:
        colorbar.update_normal(image)


def plot_metrics(
    ax: Any,
    points: Sequence[MetricsPoint],
    *,
    max_points: int = DEFAULT_METRICS_POINTS,
    show_grid: bool = True,
) -> None:
    data = metrics_series(points, max_points=max_points)
    ax.clear()
    ax.set_title("METRICS ratios")
    ax.set_xlabel("frame index")
    ax.set_ylabel("ratio")
    ax.set_ylim(-0.02, 1.02)
    if show_grid:
        ax.grid(True)
    if data.empty:
        _empty_axis(ax, "no METRICS packets")
        return
    ax.plot(data.frame_idx, data.kept_energy_ratio, label="kept energy")
    ax.plot(data.frame_idx, data.suppressed_bin_ratio, label="suppressed bins")
    latest = points[-1]
    metrics_class = "aggregate" if latest.aggregate_metrics else "per-frame"
    trunc = " truncated" if latest.payload_truncated else ""
    ax.set_title(
        f"METRICS {metrics_class}{trunc}; latest max_abs_err={latest.max_abs_err}"
    )
    ax.legend(loc="best", fontsize="small")


def plot_status_panel(
    ax: Any,
    snapshot: DashboardSnapshot,
    *,
    receiver_stats: Any | None = None,
    queue_drop_count: int = 0,
    command_status: str | None = None,
    max_lines: int = DEFAULT_STATUS_LINES,
) -> None:
    ax.clear()
    ax.axis("off")
    ax.set_title("Live STATUS / receiver / commands")
    rows = format_status_text(
        snapshot,
        receiver_stats=receiver_stats,
        queue_drop_count=queue_drop_count,
        command_status=command_status,
        max_lines=max_lines,
    ).splitlines()
    column_size = len(rows) if len(rows) <= 18 else math.ceil(len(rows) / 2)
    columns = (rows[:column_size], rows[column_size:])
    for index, column in enumerate(columns):
        if not column:
            continue
        ax.text(
            0.0 if index == 0 else 0.5,
            1.0,
            "\n".join(column),
            transform=ax.transAxes,
            ha="left",
            va="top",
            family="monospace",
            fontsize=6.0,
            linespacing=1.0,
            clip_on=True,
        )


def _tail(items: Sequence[Any], max_items: int | None) -> tuple[Any, ...]:
    if max_items is None:
        return tuple(items)
    if max_items < 1:
        raise ValueError("max_items must be >= 1")
    if len(items) <= max_items:
        return tuple(items)
    return tuple(items[-max_items:])


def _empty_axis(ax: Any, message: str) -> None:
    ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center", va="center")


def _nan_if_none(value: float | None) -> float:
    return math.nan if value is None else float(value)


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def _status_lines(status: StatusPoint) -> list[str]:
    diagnostic = " diagnostic" if status.diagnostic else ""
    truncated = " truncated" if getattr(status, "payload_truncated", False) else ""
    return [
        f"latest STATUS         :{diagnostic}{truncated}",
        f"sample / frame count  : {status.sample_count} / {status.frame_count}",
        f"source / sample rate  : {status.source_mode} / "
        + (f"{status.sample_rate} Hz" if status.sample_rate else
           ("not reported (HPS diagnostic)" if status.diagnostic else
            "no periodic DSP stream (diagnostic)")),
        f"packet enable         : 0x{status.packet_enable:08x}",
        f"active THR2           : 0x{status.thr2:014x}",
        f"DDR dma drops         : {status.dma_drop_count}",
        f"packet FIFO drops     : {status.packet_fifo_drop_count}",
        f"UDP send errors       : {status.udp_send_error_count}",
        f"HPS malformed records : {status.malformed_record_count}",
        f"HPS oversized records : {status.oversized_record_count}",
        f"command rejects       : {status.command_reject_count}",
        f"HPS sequence gaps     : {status.sequence_gap_count}",
        f"overflow flags        : 0x{status.overflow_flags:08x}",
    ]


def _metrics_lines(metrics: MetricsPoint) -> list[str]:
    metrics_class = "aggregate" if metrics.aggregate_metrics else "per-frame"
    truncated = " truncated" if metrics.payload_truncated else ""
    return [
        f"metrics frame/class   : {metrics.frame_idx} / {metrics_class}{truncated}",
        f"kept energy ratio     : {_fmt_ratio(metrics.kept_energy_ratio)}",
        f"suppressed bin ratio  : {_fmt_ratio(metrics.suppressed_bin_ratio)}",
        f"max_abs_err           : {metrics.max_abs_err}",
    ]


def _spectrum_lines(spectrum: SpectrumFrame) -> list[str]:
    return [
        f"spectrum packet/frame : {spectrum.packet_name} / {spectrum.frame_idx}",
        f"spectrum bins/shift   : {spectrum.bin_count} / {spectrum.spec_shift}",
    ]


def _receiver_lines(stats: Any | None, *, queue_drop_count: int) -> list[str]:
    if stats is None:
        return [f"local UI queue drops  : {int(queue_drop_count)}"]
    mappings = (
        ("receiver datagrams", "datagrams_seen"),
        ("receiver accepted", "datagrams_accepted"),
        ("receiver parsed", "packets_parsed"),
        ("receiver parse errors", "parse_errors"),
        ("socket truncations", "datagrams_socket_truncated"),
        ("truncated/oversized", "datagrams_truncated_or_oversized"),
        ("wire payload trunc", "payload_truncated_packet_count"),
        ("receiver seq gaps", "sequence_gap_count"),
        ("receiver missing seq", "missing_sequence_count"),
        ("receiver duplicates", "duplicate_sequence_count"),
        ("receiver reordered", "reordered_sequence_count"),
    )
    rows = [
        f"{label:<23}: {getattr(stats, field)}"
        for label, field in mappings
        if hasattr(stats, field)
    ]
    rows.append(f"local UI queue drops  : {int(queue_drop_count)}")
    last_error = getattr(stats, "last_error", None)
    if last_error:
        kind = getattr(stats, "last_error_kind", "error")
        rows.append(f"last receiver {kind:<6}: {last_error}")
    return rows


def _malformed_truncated_state(
    status: StatusPoint | None,
    snapshot: DashboardSnapshot,
    receiver_stats: Any | None,
) -> str:
    counts = [
        int(getattr(snapshot, "total_payload_truncated_packets", 0)),
        int(getattr(receiver_stats, "parse_errors", 0) or 0),
        int(getattr(receiver_stats, "datagrams_socket_truncated", 0) or 0),
        int(getattr(receiver_stats, "datagrams_truncated_or_oversized", 0) or 0),
        int(getattr(receiver_stats, "payload_truncated_packet_count", 0) or 0),
    ]
    if status is not None:
        counts.extend(
            [
                int(status.malformed_record_count),
                int(status.oversized_record_count),
                int(bool(getattr(status, "payload_truncated", False))),
            ]
        )
    if any(counts):
        return "ACTIVE"
    return "CLEAR" if status is not None else "UNKNOWN (no STATUS)"


def _fmt_ratio(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.6f}"


DashboardPlotController = DashboardPlotter
make_wave_series = (
    lambda snapshot, max_points=DEFAULT_WAVE_POINTS: wave_series(
        snapshot.wave,
        max_points=max_points,
    )
)
make_metrics_series = (
    lambda snapshot, max_points=DEFAULT_METRICS_POINTS: metrics_series(
        snapshot.metrics,
        max_points=max_points,
    )
)
make_status_summary = summarize_snapshot


__all__ = [
    "CommandSubmitter",
    "DashboardPlotController",
    "DashboardPlotter",
    "HeadlessDashboardRenderer",
    "MetricsSeries",
    "PlotConfig",
    "PlotDependencyError",
    "SnapshotSummary",
    "SpectrogramMatrix",
    "WaveSeries",
    "format_status_text",
    "latest_metrics",
    "latest_spectrum",
    "latest_status",
    "make_metrics_series",
    "make_status_summary",
    "make_wave_series",
    "metrics_series",
    "plot_metrics",
    "plot_spectrogram",
    "plot_spectrum",
    "plot_status_panel",
    "plot_wave_error",
    "plot_waveform",
    "require_matplotlib",
    "spectrogram_matrix",
    "summarize_snapshot",
    "wave_series",
]
