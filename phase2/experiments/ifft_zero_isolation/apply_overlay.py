#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a fresh experimental source tree after verifying its frozen baseline.

The input repository is read only. Only files declared by the frozen baseline
manifest are copied; Git metadata, ignored builds, hardware images and local
measurement runs are not copied. No external tools or hardware are invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def relative_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Invalid portable manifest path: " + repr(name))
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("Unsafe manifest path: " + name)
    if any(part.lower() in (".git", "__pycache__") for part in path.parts):
        raise ValueError("Excluded metadata path: " + name)
    return path


def child(root, name):
    path = root.joinpath(*relative_name(name).parts)
    if not path.resolve().is_relative_to(root):
        raise ValueError("Manifest path resolves outside its root: " + name)
    return path


def validate_entries(entries):
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Empty or invalid file manifest")
    used = set()
    for name, info in entries.items():
        relative_name(name)
        if name.casefold() in used:
            raise ValueError("Case-insensitive path collision: " + name)
        used.add(name.casefold())
        if (not isinstance(info, dict) or
                not re.fullmatch(r"[0-9a-f]{64}", info.get("sha256", "")) or
                type(info.get("bytes")) is not int or info["bytes"] < 0):
            raise ValueError("Invalid file hash or byte count: " + name)


def checked_bytes(root, name, info):
    path = child(root, name)
    if not path.is_file():
        raise ValueError("Required source file is missing: " + name)
    data = path.read_bytes()
    if len(data) != info["bytes"] or digest(data) != info["sha256"]:
        raise ValueError("Source does not match the frozen manifest: " + name)
    return data


def verify_all(root, entries):
    for name, info in entries.items():
        checked_bytes(root, name, info)


def write_source(root, name, data):
    path = child(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True,
                        help="Existing baseline repository; read only")
    parser.add_argument("--output", type=Path, required=True,
                        help="Fresh destination outside the repository and package")
    args = parser.parse_args(argv)
    package = Path(__file__).resolve().parent
    repo = args.repo.resolve()
    output = args.output.resolve()
    if not repo.is_dir():
        parser.error("--repo must be an existing directory")
    if output.exists() or args.output.is_symlink():
        parser.error("--output must not exist; partial previous results are never reused")
    if output.is_relative_to(repo) or output.is_relative_to(package):
        parser.error("--output must be outside the input repository and package")

    manifest = read_json(package / "overlay_manifest.json")
    if manifest.get("schema") != "trecap-ifft-zero-overlay-1":
        raise ValueError("Unknown overlay manifest schema")
    baseline_bytes = (package / "baseline_source_manifest.json").read_bytes()
    if digest(baseline_bytes) != manifest["baseline_source_manifest_sha256"]:
        raise ValueError("Frozen baseline manifest hash mismatch")
    baseline = read_json(package / "baseline_source_manifest.json")
    if baseline.get("schema") != "trecap-frozen-baseline-1":
        raise ValueError("Unknown baseline manifest schema")
    base_files = baseline["files"]
    package_files = manifest["package_files"]
    overlay = manifest["overlay"]
    validate_entries(base_files)
    validate_entries(package_files)
    if not isinstance(overlay, dict) or len(overlay) != 8:
        raise ValueError("Expected the reviewed eight-file experimental overlay")
    # Verify all package content, including this script and published profile
    # evidence. The outer manifest itself is the reviewable integrity index.
    verify_all(package, package_files)
    verify_all(repo, base_files)

    overlay_data = {}
    final_files = dict(base_files)
    used = set()
    for name, info in overlay.items():
        relative_name(name)
        if name.casefold() in used:
            raise ValueError("Overlay target collision: " + name)
        used.add(name.casefold())
        expected_base = base_files.get(name, {}).get("sha256")
        if info["baseline_sha256"] != expected_base:
            raise ValueError("Overlay baseline ownership mismatch: " + name)
        source = "overlay/" + name
        if info["package_file"] != source or source not in package_files:
            raise ValueError("Overlay package source mismatch: " + name)
        record = package_files[source]
        if info["sha256"] != record["sha256"]:
            raise ValueError("Overlay content hash mismatch: " + name)
        # New experiment helpers may not silently replace a same-named file
        # supplied by a different checkout, even though it is not copied.
        if expected_base is None and child(repo, name).exists():
            raise ValueError("New overlay target already exists in input repository: " + name)
        overlay_data[name] = checked_bytes(package, source, record)
        final_files[name] = {"sha256": record["sha256"], "bytes": record["bytes"]}

    output.mkdir(parents=True, exist_ok=False)
    # A failure leaves a partial directory for inspection; rerunning requires a
    # different fresh destination. There is deliberately no recursive cleanup.
    for name, info in base_files.items():
        write_source(output, name, checked_bytes(repo, name, info))
    for name, data in overlay_data.items():
        write_source(output, name, data)
    verify_all(output, final_files)
    verify_all(repo, base_files)
    verify_all(package, package_files)
    receipt = {
        "schema": "trecap-ifft-zero-overlay-application-1",
        "status": "PASS",
        "scope": "Fresh declared source snapshot plus experimental overlay; input repository unmodified",
        "baseline_source_manifest_sha256": digest(baseline_bytes),
        "overlay_manifest_sha256": digest((package / "overlay_manifest.json").read_bytes()),
        "baseline_files_verified": len(base_files),
        "overlay_files": len(overlay),
        "final_files": final_files,
    }
    (output / "experiment_overlay_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "baseline_files_verified": len(base_files),
                      "overlay_files": len(overlay), "final_source_files": len(final_files)}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Overlay application failed: " + str(error), file=sys.stderr)
        sys.exit(1)
