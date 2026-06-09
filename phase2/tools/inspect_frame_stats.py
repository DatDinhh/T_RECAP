#!/usr/bin/env python3
"""Inspect and cross-check T-RECAP frame_stats.csv artifacts."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from _trecap_tool_common import FRAME_STATS_HEADER, ToolError, csv_row_count, main_wrapper, read_json, sha256_file


_DECIMAL_FIELDS = set(FRAME_STATS_HEADER)


def read_frame_stats(path: Path) -> list[dict[str, int]]:
    # csv_row_count validates LF and exact header.
    csv_row_count(path, FRAME_STATS_HEADER)
    rows: list[dict[str, int]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FRAME_STATS_HEADER:
            raise ToolError(f"frame_stats.csv header mismatch: {reader.fieldnames!r}")
        for line_no, row in enumerate(reader, start=2):
            parsed: dict[str, int] = {}
            for field in _DECIMAL_FIELDS:
                text = row.get(field, "")
                if text == "" or not text.isdecimal():
                    raise ToolError(f"{path}:{line_no}: field {field} is not unsigned decimal: {text!r}")
                parsed[field] = int(text)
            rows.append(parsed)
    for expected_idx, row in enumerate(rows):
        if row["frame_idx"] != expected_idx:
            raise ToolError(f"frame_idx order mismatch at row {expected_idx}: got {row['frame_idx']}")
    return rows


def summarize(rows: list[dict[str, int]]) -> dict[str, Any]:
    totals = {
        "unique_bins": sum(r["unique_bins"] for r in rows),
        "unique_suppressed_bins": sum(r["unique_suppressed_bins"] for r in rows),
        "eligible_unique_bins": sum(r["eligible_unique_bins"] for r in rows),
        "eligible_suppressed_bins": sum(r["eligible_suppressed_bins"] for r in rows),
        "eligible_kept_mag2": sum(r["eligible_kept_mag2"] for r in rows),
        "eligible_total_mag2": sum(r["eligible_total_mag2"] for r in rows),
    }
    eligible_unique = totals["eligible_unique_bins"]
    unique_bins = totals["unique_bins"]
    total_mag2 = totals["eligible_total_mag2"]
    return {
        "frames": len(rows),
        "per_frame_unique_bins": sorted({r["unique_bins"] for r in rows}),
        "per_frame_eligible_unique_bins": sorted({r["eligible_unique_bins"] for r in rows}),
        "totals": {k: str(v) for k, v in totals.items()},
        "unique_suppression_ratio": None if unique_bins == 0 else totals["unique_suppressed_bins"] / unique_bins,
        "eligible_suppression_ratio": None if eligible_unique == 0 else totals["eligible_suppressed_bins"] / eligible_unique,
        "eligible_kept_mag2_ratio": None if total_mag2 == 0 else totals["eligible_kept_mag2"] / total_mag2,
        "first_row": rows[0] if rows else None,
        "last_row": rows[-1] if rows else None,
    }


def cross_check_metrics(summary: dict[str, Any], metrics_path: Path) -> list[str]:
    metrics = read_json(metrics_path)
    mismatches: list[str] = []
    metric_supp = metrics.get("suppression_totals", {})
    metric_spec = metrics.get("spectral_totals", {})
    expected = {**metric_supp, **metric_spec}
    totals = summary["totals"]
    for key in [
        "unique_bins",
        "unique_suppressed_bins",
        "eligible_unique_bins",
        "eligible_suppressed_bins",
        "eligible_kept_mag2",
        "eligible_total_mag2",
    ]:
        if key in expected and str(expected[key]) != totals[key]:
            mismatches.append(f"{key}: frame_stats={totals[key]} metrics={expected[key]}")
    return mismatches


def print_text(path: Path, report: dict[str, Any]) -> None:
    print(f"path:                         {path.as_posix()}")
    print(f"sha256:                       {report['sha256']}")
    print(f"frames:                       {report['summary']['frames']}")
    print(f"per_frame_unique_bins:        {report['summary']['per_frame_unique_bins']}")
    print(f"per_frame_eligible_bins:      {report['summary']['per_frame_eligible_unique_bins']}")
    print(f"unique_suppression_ratio:     {report['summary']['unique_suppression_ratio']}")
    print(f"eligible_suppression_ratio:   {report['summary']['eligible_suppression_ratio']}")
    print(f"eligible_kept_mag2_ratio:     {report['summary']['eligible_kept_mag2_ratio']}")
    print("totals:")
    for key, value in report["summary"]["totals"].items():
        print(f"  {key}: {value}")
    if report.get("metrics_cross_check"):
        status = "PASS" if not report["metrics_cross_check"]["mismatches"] else "FAIL"
        print(f"metrics_cross_check:          {status}")
        for mismatch in report["metrics_cross_check"]["mismatches"]:
            print(f"  {mismatch}")


def run() -> int:
    parser = argparse.ArgumentParser(description="Inspect frame_stats.csv and optional metrics.json")
    parser.add_argument("frame_stats", type=Path)
    parser.add_argument("--metrics", type=Path, default=None, help="optional metrics.json to cross-check")
    parser.add_argument("--expect-frames", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows = read_frame_stats(args.frame_stats)
    if args.expect_frames is not None and len(rows) != args.expect_frames:
        raise ToolError(f"expected {args.expect_frames} frame rows, got {len(rows)}")
    summary = summarize(rows)
    report: dict[str, Any] = {
        "schema": "trecap_frame_stats_inspection_v1",
        "path": args.frame_stats.as_posix(),
        "sha256": sha256_file(args.frame_stats),
        "summary": summary,
    }
    if args.metrics:
        mismatches = cross_check_metrics(summary, args.metrics)
        report["metrics_cross_check"] = {"path": args.metrics.as_posix(), "mismatches": mismatches}
        if mismatches:
            if args.json:
                print(json.dumps(report, indent=2))
            raise ToolError("frame_stats.csv does not match metrics.json")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text(args.frame_stats, report)
    return 0


if __name__ == "__main__":
    main_wrapper(run)
