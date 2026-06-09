#!/usr/bin/env python3
"""Inspect canonical T-RECAP memh files without changing them."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _trecap_tool_common import ToolError, canonical_file_hash, main_wrapper, read_memh, sha256_file
from hash_memh import infer_contract


def numeric_summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {
            "rows": 0,
            "min": None,
            "max": None,
            "sum": "0",
            "sum_abs": "0",
            "sum_sq": "0",
            "zero_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "max_abs": 0,
        }
    return {
        "rows": len(values),
        "min": min(values),
        "max": max(values),
        "sum": str(sum(values)),
        "sum_abs": str(sum(abs(v) for v in values)),
        "sum_sq": str(sum(v * v for v in values)),
        "zero_count": sum(1 for v in values if v == 0),
        "positive_count": sum(1 for v in values if v > 0),
        "negative_count": sum(1 for v in values if v < 0),
        "max_abs": max(abs(v) for v in values),
    }


def row_slice(values: list[int], start: int, count: int) -> list[dict[str, int]]:
    if start < 0:
        raise ToolError("--start must be non-negative")
    if count < 0:
        raise ToolError("--count must be non-negative")
    end = min(len(values), start + count)
    return [{"index": idx, "value": values[idx]} for idx in range(start, end)]


def inspect_one(path: Path, width: int, signed: bool, start: int, count: int) -> dict[str, Any]:
    values = read_memh(path, width, signed)
    summary = numeric_summary(values)
    summary.update(
        {
            "path": path.as_posix(),
            "width_bits": width,
            "signed": signed,
            "canonical_sha256": canonical_file_hash(path, width, signed),
            "file_sha256": sha256_file(path),
            "first_values": row_slice(values, 0, min(count, len(values))),
            "selected_values": row_slice(values, start, count),
            "last_values": row_slice(values, max(0, len(values) - count), count),
        }
    )
    return summary


def print_text(report: dict[str, Any]) -> None:
    print(f"path:              {report['path']}")
    print(f"rows:              {report['rows']}")
    print(f"width_bits:        {report['width_bits']}")
    print(f"signed:            {str(report['signed']).lower()}")
    print(f"min/max:           {report['min']} / {report['max']}")
    print(f"zero/pos/neg:      {report['zero_count']} / {report['positive_count']} / {report['negative_count']}")
    print(f"max_abs:           {report['max_abs']}")
    print(f"sum_abs:           {report['sum_abs']}")
    print(f"sum_sq:            {report['sum_sq']}")
    print(f"canonical_sha256:  {report['canonical_sha256']}")
    print(f"file_sha256:       {report['file_sha256']}")
    print("selected_values:")
    for item in report["selected_values"]:
        print(f"  [{item['index']}] {item['value']}")


def run() -> int:
    parser = argparse.ArgumentParser(description="Inspect a canonical T-RECAP memh file")
    parser.add_argument("path", type=Path)
    parser.add_argument("--kind", default=None)
    parser.add_argument("--width", type=int, default=None)
    sign = parser.add_mutually_exclusive_group()
    sign.add_argument("--signed", dest="signed", action="store_true", default=None)
    sign.add_argument("--unsigned", dest="signed", action="store_false")
    parser.add_argument("--start", type=int, default=0, help="first sample index to show")
    parser.add_argument("--count", type=int, default=8, help="number of selected samples to show")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    width, signed = infer_contract(args.path, args.kind, args.width, args.signed)
    report = inspect_one(args.path, width, signed, args.start, args.count)
    if args.json:
        print(json.dumps({"schema": "trecap_memh_inspection_v1", "file": report}, indent=2))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    main_wrapper(run)
