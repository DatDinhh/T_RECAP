#!/usr/bin/env python3
"""Compute the T-RECAP canonical SHA-256 of one or more memh files.

The hash is over the logical integer vector serialized as fixed-width
lowercase hex plus LF, not over arbitrary host file bytes.  This is the
artifact authority rule used by coefficient, x_in, and y_out manifests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _trecap_tool_common import (
    N,
    W_QW,
    W_TW,
    ToolError,
    canonical_file_hash,
    hex_digits,
    main_wrapper,
    read_memh,
    sha256_file,
)


_KIND_CONTRACTS: dict[str, tuple[int, bool]] = {
    "sample": (N, True),
    "stream": (N, True),
    "x_in": (N, True),
    "y_out": (N, True),
    "window": (W_QW, False),
    "window_qw": (W_QW, False),
    "twiddle": (W_TW, True),
    "twiddle_re": (W_TW, True),
    "twiddle_im": (W_TW, True),
    "twiddle_inv_re": (W_TW, True),
    "twiddle_inv_im": (W_TW, True),
}


def infer_contract(path: Path, kind: str | None, width: int | None, signed_flag: bool | None) -> tuple[int, bool]:
    """Infer or validate width/signedness for a memh file."""
    inferred: tuple[int, bool] | None = None
    if kind:
        if kind not in _KIND_CONTRACTS:
            raise ToolError(f"unknown memh kind {kind!r}")
        inferred = _KIND_CONTRACTS[kind]
    else:
        stem = path.stem
        name = path.name
        if stem in _KIND_CONTRACTS:
            inferred = _KIND_CONTRACTS[stem]
        elif name in {"x_in.memh", "y_out.memh"}:
            inferred = (N, True)
        elif name == "window_qw.memh":
            inferred = (W_QW, False)
        elif name.startswith("twiddle") and name.endswith(".memh"):
            inferred = (W_TW, True)

    if inferred is None:
        if width is None or signed_flag is None:
            raise ToolError(
                f"cannot infer memh contract for {path}; pass --width and either --signed or --unsigned"
            )
        inferred = (width, signed_flag)

    final_width = inferred[0] if width is None else width
    final_signed = inferred[1] if signed_flag is None else signed_flag
    if final_width <= 0 or final_width > 64:
        raise ToolError(f"unsupported width {final_width}; expected 1..64")
    return final_width, final_signed


def hash_one(path: Path, width: int, signed: bool, expect_rows: int | None, check: str | None) -> dict[str, Any]:
    values = read_memh(path, width, signed)
    if expect_rows is not None and len(values) != expect_rows:
        raise ToolError(f"{path}: expected {expect_rows} rows, got {len(values)}")
    canonical_hash = canonical_file_hash(path, width, signed)
    if check is not None and canonical_hash != check.lower():
        raise ToolError(f"{path}: hash mismatch: expected {check.lower()}, got {canonical_hash}")
    return {
        "path": path.as_posix(),
        "rows": len(values),
        "width_bits": width,
        "hex_digits": hex_digits(width),
        "signed": signed,
        "canonical_sha256": canonical_hash,
        "file_sha256": sha256_file(path),
        "content_contract": "fixed_width_lowercase_hex_lf",
    }


def run() -> int:
    parser = argparse.ArgumentParser(description="Hash canonical T-RECAP memh files")
    parser.add_argument("paths", nargs="+", type=Path, help="memh file(s) to hash")
    parser.add_argument("--kind", choices=sorted(_KIND_CONTRACTS), default=None)
    parser.add_argument("--width", type=int, default=None, help="declared memh width in bits")
    sign = parser.add_mutually_exclusive_group()
    sign.add_argument("--signed", dest="signed", action="store_true", default=None)
    sign.add_argument("--unsigned", dest="signed", action="store_false")
    parser.add_argument("--expect-rows", type=int, default=None)
    parser.add_argument("--check", default=None, help="expected canonical SHA-256 for a single file")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    if args.check and len(args.paths) != 1:
        raise ToolError("--check may only be used with one input file")

    results: list[dict[str, Any]] = []
    for path in args.paths:
        width, signed = infer_contract(path, args.kind, args.width, args.signed)
        results.append(hash_one(path, width, signed, args.expect_rows, args.check))

    if args.json:
        print(json.dumps({"schema": "trecap_memh_hash_report_v1", "files": results}, indent=2))
    else:
        for item in results:
            print(
                f"{item['canonical_sha256']}  {item['path']}  "
                f"rows={item['rows']} width={item['width_bits']} signed={str(item['signed']).lower()}"
            )
    return 0


if __name__ == "__main__":
    main_wrapper(run)
