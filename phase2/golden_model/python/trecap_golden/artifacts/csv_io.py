# SPDX-License-Identifier: MIT
"""CSV artifact readers, writers, and validators."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from trecap_golden.generated import trecap_config as cfg


class CsvArtifactError(ValueError):
    """Raised when a CSV artifact violates the frozen row/header contract."""


FRAME_STATS_HEADER: tuple[str, ...] = cfg.REQUIRED_FRAME_STATS_HEADER
BIN_STATS_HEADER: tuple[str, ...] = cfg.REQUIRED_BIN_STATS_HEADER

_UNSIGNED_FRAME_FIELDS = frozenset(FRAME_STATS_HEADER)
_UNSIGNED_BIN_FIELDS = frozenset({"frame_idx", "bin_idx", "mag2", "eligible", "pre_mask", "mask"})
_SIGNED_BIN_FIELDS = frozenset({"real", "imag"})
_BIT_FIELDS = frozenset({"eligible", "pre_mask", "mask"})


@dataclass(frozen=True, slots=True)
class CsvReadResult:
    """Parsed CSV rows and header metadata."""

    path: Path
    header: tuple[str, ...]
    rows: tuple[dict[str, int], ...]

    @property
    def data_rows(self) -> int:
        return len(self.rows)


def _read_lf_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise CsvArtifactError(f"missing CSV artifact: {path}") from exc
    if b"\r" in raw:
        raise CsvArtifactError(f"{path}: CRLF is not canonical for CSV artifacts")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CsvArtifactError(f"{path}: CSV must be UTF-8") from exc
    if text and not text.endswith("\n"):
        raise CsvArtifactError(f"{path}: CSV must end with LF")
    return text


def _parse_int(text: str, *, signed: bool, bit: bool, path: Path, line_no: int, field: str) -> int:
    if signed:
        ok = text.startswith("-") and text[1:].isdecimal() or text.isdecimal()
    else:
        ok = text.isdecimal()
    if not ok:
        kind = "signed decimal" if signed else "unsigned decimal"
        raise CsvArtifactError(f"{path}:{line_no}: field {field} is not {kind}: {text!r}")
    value = int(text)
    if bit and value not in {0, 1}:
        raise CsvArtifactError(f"{path}:{line_no}: field {field} must be 0 or 1, got {value}")
    return value


def read_csv_artifact(path: str | Path, header: Iterable[str], *, expected_rows: int | None = None) -> CsvReadResult:
    """Read a CSV artifact with exact header and optional data-row count."""

    p = Path(path)
    text = _read_lf_text(p)
    rows: list[dict[str, int]] = []
    expected_header = tuple(header)
    reader = csv.DictReader(text.splitlines())
    if tuple(reader.fieldnames or ()) != expected_header:
        raise CsvArtifactError(f"{p}: expected header {expected_header!r}, got {tuple(reader.fieldnames or ())!r}")
    for line_no, row in enumerate(reader, start=2):
        parsed: dict[str, int] = {}
        for field in expected_header:
            value_text = row.get(field)
            if value_text is None:
                raise CsvArtifactError(f"{p}:{line_no}: missing field {field}")
            parsed[field] = _parse_int(
                value_text,
                signed=field in _SIGNED_BIN_FIELDS,
                bit=field in _BIT_FIELDS,
                path=p,
                line_no=line_no,
                field=field,
            )
        rows.append(parsed)
    if expected_rows is not None and len(rows) != expected_rows:
        raise CsvArtifactError(f"{p}: expected {expected_rows} data rows, got {len(rows)}")
    return CsvReadResult(path=p, header=expected_header, rows=tuple(rows))


def data_row_count(path: str | Path, header: Iterable[str]) -> int:
    """Return data-row count after validating the header and LF policy."""

    return read_csv_artifact(path, header).data_rows


def read_frame_stats(path: str | Path, *, expected_rows: int | None = None) -> CsvReadResult:
    """Read and validate ``frame_stats.csv``."""

    result = read_csv_artifact(path, FRAME_STATS_HEADER, expected_rows=expected_rows)
    for expected_idx, row in enumerate(result.rows):
        if row["frame_idx"] != expected_idx:
            raise CsvArtifactError(f"{result.path}: frame_idx order mismatch at row {expected_idx}")
    return result


def read_bin_stats(path: str | Path, *, expected_rows: int | None = None) -> CsvReadResult:
    """Read and validate ``bin_stats.csv`` ordering and bit fields."""

    result = read_csv_artifact(path, BIN_STATS_HEADER, expected_rows=expected_rows)
    if not result.rows:
        return result
    previous = (-1, cfg.UNIQUE_BINS)
    for row in result.rows:
        pair = (row["frame_idx"], row["bin_idx"])
        if row["bin_idx"] < 0 or row["bin_idx"] >= cfg.UNIQUE_BINS:
            raise CsvArtifactError(f"{result.path}: bin_idx out of range: {row['bin_idx']}")
        if pair <= previous:
            raise CsvArtifactError(f"{result.path}: bin_stats rows are not in frame/bin order")
        previous = pair
    return result


def _write_rows(path: Path, header: tuple[str, ...], rows: Iterable[Mapping[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(header), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: int(row[field]) for field in header})


def write_frame_stats(path: str | Path, rows: Iterable[Mapping[str, int]]) -> None:
    """Write ``frame_stats.csv`` using the exact frozen header order."""

    _write_rows(Path(path), FRAME_STATS_HEADER, rows)


def write_bin_stats(path: str | Path, rows: Iterable[Mapping[str, int]]) -> None:
    """Write ``bin_stats.csv`` using the exact frozen header order."""

    _write_rows(Path(path), BIN_STATS_HEADER, rows)


def summarize_frame_stats(rows: Iterable[Mapping[str, int]]) -> dict[str, Any]:
    """Summarize frame statistics in the same terms used by ``metrics.json``."""

    materialized = tuple(dict(row) for row in rows)
    totals = {
        "unique_bins": sum(int(row["unique_bins"]) for row in materialized),
        "unique_suppressed_bins": sum(int(row["unique_suppressed_bins"]) for row in materialized),
        "eligible_unique_bins": sum(int(row["eligible_unique_bins"]) for row in materialized),
        "eligible_suppressed_bins": sum(int(row["eligible_suppressed_bins"]) for row in materialized),
        "eligible_kept_mag2": sum(int(row["eligible_kept_mag2"]) for row in materialized),
        "eligible_total_mag2": sum(int(row["eligible_total_mag2"]) for row in materialized),
    }
    eligible_unique = totals["eligible_unique_bins"]
    unique_bins = totals["unique_bins"]
    total_mag2 = totals["eligible_total_mag2"]
    return {
        "frames": len(materialized),
        "per_frame_unique_bins": sorted({int(row["unique_bins"]) for row in materialized}),
        "per_frame_eligible_unique_bins": sorted({int(row["eligible_unique_bins"]) for row in materialized}),
        "totals": {key: str(value) for key, value in totals.items()},
        "unique_suppression_ratio": None if unique_bins == 0 else totals["unique_suppressed_bins"] / unique_bins,
        "eligible_suppression_ratio": None if eligible_unique == 0 else totals["eligible_suppressed_bins"] / eligible_unique,
        "eligible_kept_mag2_ratio": None if total_mag2 == 0 else totals["eligible_kept_mag2"] / total_mag2,
    }


def cross_check_frame_stats_metrics(rows: Iterable[Mapping[str, int]], metrics: Mapping[str, Any]) -> list[str]:
    """Return mismatch descriptions between frame stats totals and metrics JSON."""

    summary = summarize_frame_stats(rows)
    expected = {**metrics.get("suppression_totals", {}), **metrics.get("spectral_totals", {})}
    mismatches: list[str] = []
    for key, value in summary["totals"].items():
        if key in expected and str(expected[key]) != value:
            mismatches.append(f"{key}: frame_stats={value} metrics={expected[key]}")
    return mismatches


__all__ = [
    "BIN_STATS_HEADER",
    "FRAME_STATS_HEADER",
    "CsvArtifactError",
    "CsvReadResult",
    "cross_check_frame_stats_metrics",
    "data_row_count",
    "read_bin_stats",
    "read_csv_artifact",
    "read_frame_stats",
    "summarize_frame_stats",
    "write_bin_stats",
    "write_frame_stats",
]
