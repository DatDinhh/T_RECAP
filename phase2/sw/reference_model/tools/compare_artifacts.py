#!/usr/bin/env python3
"""Compare two T-RECAP artifact files or artifact directory trees.

For memh files, comparison is based on the declared logical integer vector
and canonical memh serialization.  For CSV files, comparison is byte-exact
under the LF-only CSV contract.  For JSON files, comparison is semantic JSON
unless --json-byte-exact is requested.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _trecap_tool_common import ToolError, canonical_memh_hash, main_wrapper, read_json, read_memh, sha256_file
from hash_memh import infer_contract

_ALLOWED_SUFFIXES = {".memh", ".csv", ".json"}
_VOLATILE_KEYS = {
    "created_utc",
    "generated_utc",
    "timestamp",
    "host",
    "python_version",
    "package_created_utc",
    "packaged_utc",
}


def collect_paths(root: Path) -> dict[str, Path]:
    if root.is_file():
        return {root.name: root}
    if not root.exists():
        raise ToolError(f"missing path: {root}")
    return {
        p.relative_to(root).as_posix(): p
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix.lower() in _ALLOWED_SUFFIXES
    }


def strip_volatile(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_volatile(v) for k, v in obj.items() if k not in _VOLATILE_KEYS}
    if isinstance(obj, list):
        return [strip_volatile(v) for v in obj]
    return obj


def first_value_mismatch(left: list[int], right: list[int]) -> dict[str, int] | None:
    for idx, (lv, rv) in enumerate(zip(left, right)):
        if lv != rv:
            return {"index": idx, "left": lv, "right": rv}
    if len(left) != len(right):
        idx = min(len(left), len(right))
        return {
            "index": idx,
            "left": left[idx] if idx < len(left) else 0,
            "right": right[idx] if idx < len(right) else 0,
        }
    return None


def compare_memh(rel: str, left: Path, right: Path) -> dict[str, Any]:
    try:
        width, signed = infer_contract(left, kind=None, width=None, signed_flag=None)
    except ToolError:
        try:
            width, signed = infer_contract(right, kind=None, width=None, signed_flag=None)
        except ToolError:
            # Unknown memh type: compare bytes, but flag that no logical contract was known.
            equal = left.read_bytes() == right.read_bytes()
            return {
                "path": rel,
                "artifact_type": "memh",
                "status": "equal" if equal else "different",
                "comparison": "byte_exact_unknown_memh_contract",
                "left_sha256": sha256_file(left),
                "right_sha256": sha256_file(right),
            }
    left_values = read_memh(left, width, signed)
    right_values = read_memh(right, width, signed)
    left_hash = canonical_memh_hash(left_values, width, signed)
    right_hash = canonical_memh_hash(right_values, width, signed)
    equal = left_hash == right_hash
    entry: dict[str, Any] = {
        "path": rel,
        "artifact_type": "memh",
        "status": "equal" if equal else "different",
        "comparison": "logical_integer_vector_canonical_memh",
        "width_bits": width,
        "signed": signed,
        "left_rows": len(left_values),
        "right_rows": len(right_values),
        "left_canonical_sha256": left_hash,
        "right_canonical_sha256": right_hash,
    }
    if not equal:
        entry["first_mismatch"] = first_value_mismatch(left_values, right_values)
    return entry


def compare_csv(rel: str, left: Path, right: Path) -> dict[str, Any]:
    left_bytes = left.read_bytes()
    right_bytes = right.read_bytes()
    equal = left_bytes == right_bytes
    entry: dict[str, Any] = {
        "path": rel,
        "artifact_type": "csv",
        "status": "equal" if equal else "different",
        "comparison": "byte_exact_lf_csv",
        "left_sha256": sha256_file(left),
        "right_sha256": sha256_file(right),
        "left_rows_including_header": len(left_bytes.decode("utf-8").splitlines()),
        "right_rows_including_header": len(right_bytes.decode("utf-8").splitlines()),
    }
    if not equal:
        left_lines = left_bytes.decode("utf-8", errors="replace").splitlines()
        right_lines = right_bytes.decode("utf-8", errors="replace").splitlines()
        for idx, (ll, rr) in enumerate(zip(left_lines, right_lines), start=1):
            if ll != rr:
                entry["first_mismatch"] = {"line": idx, "left": ll, "right": rr}
                break
        else:
            entry["first_mismatch"] = {"line": min(len(left_lines), len(right_lines)) + 1}
    return entry


def compare_json(rel: str, left: Path, right: Path, ignore_volatile: bool, byte_exact: bool) -> dict[str, Any]:
    if byte_exact:
        equal = left.read_bytes() == right.read_bytes()
        return {
            "path": rel,
            "artifact_type": "json",
            "status": "equal" if equal else "different",
            "comparison": "byte_exact_json",
            "left_sha256": sha256_file(left),
            "right_sha256": sha256_file(right),
        }
    left_obj = read_json(left)
    right_obj = read_json(right)
    if ignore_volatile:
        left_obj = strip_volatile(left_obj)
        right_obj = strip_volatile(right_obj)
    equal = left_obj == right_obj
    left_canon = json.dumps(left_obj, sort_keys=True, separators=(",", ":"))
    right_canon = json.dumps(right_obj, sort_keys=True, separators=(",", ":"))
    return {
        "path": rel,
        "artifact_type": "json",
        "status": "equal" if equal else "different",
        "comparison": "semantic_json" + ("_ignore_volatile" if ignore_volatile else ""),
        "left_semantic_sha256": __import__("hashlib").sha256(left_canon.encode("utf-8")).hexdigest(),
        "right_semantic_sha256": __import__("hashlib").sha256(right_canon.encode("utf-8")).hexdigest(),
        "left_file_sha256": sha256_file(left),
        "right_file_sha256": sha256_file(right),
    }


def compare_file(rel: str, left: Path, right: Path, ignore_volatile: bool, json_byte_exact: bool) -> dict[str, Any]:
    suffix = left.suffix.lower()
    if suffix != right.suffix.lower():
        return {
            "path": rel,
            "status": "different",
            "reason": f"suffix mismatch: {left.suffix} vs {right.suffix}",
        }
    if suffix == ".memh":
        return compare_memh(rel, left, right)
    if suffix == ".csv":
        return compare_csv(rel, left, right)
    if suffix == ".json":
        return compare_json(rel, left, right, ignore_volatile, json_byte_exact)
    raise ToolError(f"unsupported artifact suffix for {left}")


def print_text(report: dict[str, Any]) -> None:
    print(f"left:       {report['left_root']}")
    print(f"right:      {report['right_root']}")
    print(f"compared:   {report['summary']['compared']}")
    print(f"equal:      {report['summary']['equal']}")
    print(f"different: {report['summary']['different']}")
    print(f"left_only:  {report['summary']['left_only']}")
    print(f"right_only: {report['summary']['right_only']}")
    for item in report["entries"]:
        if item["status"] != "equal":
            print(f"{item['status'].upper()}: {item.get('path', '<unknown>')}")
            if "reason" in item:
                print(f"  reason: {item['reason']}")
            if "first_mismatch" in item:
                print(f"  first_mismatch: {item['first_mismatch']}")


def run() -> int:
    parser = argparse.ArgumentParser(description="Compare two T-RECAP artifact trees or files")
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--ignore-volatile", action="store_true", help="ignore volatile JSON keys such as created_utc")
    parser.add_argument("--json-byte-exact", action="store_true", help="compare JSON bytes instead of semantic JSON")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--no-fail", action="store_true", help="always exit zero after reporting differences")
    args = parser.parse_args()

    left_paths = collect_paths(args.left)
    right_paths = collect_paths(args.right)
    entries: list[dict[str, Any]] = []
    all_rel = sorted(set(left_paths) | set(right_paths))
    for rel in all_rel:
        if rel not in left_paths:
            entries.append({"path": rel, "status": "right_only", "right_sha256": sha256_file(right_paths[rel])})
        elif rel not in right_paths:
            entries.append({"path": rel, "status": "left_only", "left_sha256": sha256_file(left_paths[rel])})
        else:
            entries.append(compare_file(rel, left_paths[rel], right_paths[rel], args.ignore_volatile, args.json_byte_exact))

    summary = {
        "compared": len([e for e in entries if e["status"] in {"equal", "different"}]),
        "equal": len([e for e in entries if e["status"] == "equal"]),
        "different": len([e for e in entries if e["status"] == "different"]),
        "left_only": len([e for e in entries if e["status"] == "left_only"]),
        "right_only": len([e for e in entries if e["status"] == "right_only"]),
    }
    report = {
        "schema": "trecap_artifact_comparison_v1",
        "left_root": args.left.as_posix(),
        "right_root": args.right.as_posix(),
        "summary": summary,
        "entries": entries,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text(report)
    failed = summary["different"] or summary["left_only"] or summary["right_only"]
    return 0 if args.no_fail or not failed else 1


if __name__ == "__main__":
    main_wrapper(run)
