#!/usr/bin/env python3
"""Create artifacts/manifests/quality_bounds.json from finalized golden metrics."""
from __future__ import annotations

import argparse
from pathlib import Path

from _trecap_tool_common import (
    GENERATOR_VERSION,
    GOLDEN_MODEL_VERSION,
    SPEC_REVISION,
    base_configuration,
    coefficient_hashes_from_artifacts,
    read_json,
    main_wrapper,
    utc_now,
    write_json,
)


def run() -> int:
    parser = argparse.ArgumentParser(description="Generate T-RECAP quality bounds from golden metrics")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/manifests/quality_bounds.json"))
    args = parser.parse_args()

    vectors = read_json(args.artifacts / "test_vectors" / "test_vectors.json").get("vectors", [])
    coeff_hashes = coefficient_hashes_from_artifacts(args.artifacts / "coefficients")
    bounds = {}
    for item in vectors:
        name = item["name"]
        metrics = read_json(args.artifacts / "golden" / name / "metrics.json")
        time = metrics["time_domain_errors"]
        bounds[name] = {
            "x_in_sha256": item["x_in_sha256"],
            "y_out_sha256": item["y_out_sha256"],
            "max_abs_err": time["max_abs_err"],
            "sum_sq_err": time["sum_sq_err"],
            "error_sample_count": time["error_sample_count"],
        }
    manifest = {
        "schema": "trecap_phase2_quality_bounds_v1",
        "spec_revision": SPEC_REVISION,
        "created_utc": utc_now(),
        "configuration": base_configuration("0"),
        "generator_version": GENERATOR_VERSION,
        "golden_model_version": GOLDEN_MODEL_VERSION,
        "hashes": coeff_hashes,
        "bounds": bounds,
    }
    write_json(args.out, manifest)
    print(f"quality_bounds: wrote {args.out}")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
