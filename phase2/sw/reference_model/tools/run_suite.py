#!/usr/bin/env python3
"""Run a reference suite into a separate output tree; preserve the input manifest."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from _trecap_tool_common import (
    ToolError, load_suite_vector_names, main_wrapper, read_json,
    require_vector_name, sha256_file, write_json,
)
from _runner_common import (
    PACKAGE_ROOT, default_reference_exe, ensure_separate_output,
    load_vector_config, run_command,
)


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, default=PACKAGE_ROOT / "artifacts/test_vectors")
    parser.add_argument("--out", type=Path, default=PACKAGE_ROOT / "runs/reference_outputs")
    parser.add_argument("--reference-exe", "--golden-exe", dest="reference_exe", type=Path)
    parser.add_argument("--coeff-dir", type=Path, default=PACKAGE_ROOT / "artifacts/coefficients")
    parser.add_argument("--suite", type=Path)
    args = parser.parse_args()
    manifest_path = args.vectors / "test_vectors.json"
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("vectors"), list):
        raise ToolError("input manifest requires a vectors array")
    by_name = {}
    for item in manifest["vectors"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ToolError("each input manifest vector requires a name")
        name = require_vector_name(item["name"])
        if name in by_name:
            raise ToolError(f"duplicate input manifest vector: {name}")
        by_name[name] = item
    names = load_suite_vector_names(args.suite) if args.suite else list(by_name)
    if not names or len(set(names)) != len(names):
        raise ToolError("suite selection must be nonempty with unique names")
    configs = {}
    for name in names:
        if name not in by_name:
            raise ToolError(f"suite references missing vector: {name}")
        config = load_vector_config(args.vectors / name)
        if config["vector_name"] != name:
            raise ToolError(f"manifest/config name mismatch: {name}")
        item = by_name[name]
        for key in ("THR2", "PROTECT_DC", "PROTECT_NYQ", "Ns"):
            if key in item and (type(item[key]) is not type(config["configuration"].get(key)) or
                                item[key] != config["configuration"].get(key)):
                raise ToolError(f"manifest/config {key} mismatch: {name}")
        for key, contract_key in (("tail_policy", "tail_policy"), ("rounding", "rounding_mode")):
            if key in item and item[key] != config["contract"][contract_key]:
                raise ToolError(f"manifest/config {key} mismatch: {name}")
        if "requires_bin_stats" in item and type(item["requires_bin_stats"]) is not bool:
            raise ToolError(f"requires_bin_stats must be boolean: {name}")
        configs[name] = config
    ensure_separate_output(args.out, args.vectors, args.coeff_dir)
    exe = args.reference_exe or default_reference_exe()
    completed = []
    for name in names:
        output = args.out / name
        command = run_command(exe, args.vectors / name, output, args.coeff_dir,
                              collect=by_name[name].get("requires_bin_stats", False))
        result = subprocess.run(command, check=False)
        if result.returncode:
            raise ToolError(f"reference run failed for {name}: exit {result.returncode}; previous outputs remain")
        completed.append({
            "name": name,
            "status": "reference_output",
            "source_config_sha256": sha256_file(args.vectors / name / "config.json"),
            "output_config_sha256": sha256_file(output / "config.json"),
            "metrics_sha256": sha256_file(output / "metrics.json"),
            "output_directory": name,
        })
    output_manifest = args.out / "run_manifest.json"
    write_json(output_manifest, {
        "schema": "trecap_reference_suite_run_v1",
        "status": "reference_outputs",
        "source_manifest_sha256": sha256_file(manifest_path),
        "vectors": completed,
    })
    print(f"reference suite: {len(completed)} vectors in {args.out}")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
