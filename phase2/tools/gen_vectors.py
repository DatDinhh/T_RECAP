#!/usr/bin/env python3
"""Generate frozen input-vector artifacts and draft vector manifests."""
from __future__ import annotations

import argparse
from pathlib import Path

from _trecap_tool_common import (
    GENERATOR_VERSION,
    N,
    ROUNDING_MODE,
    SPEC_REVISION,
    ZERO_SHA256,
    canonical_memh_hash,
    coefficient_hashes_from_artifacts,
    coefficient_hashes_from_tables,
    coefficient_tables,
    generated_source_hash,
    filter_specs_by_suite,
    generate_vector,
    load_vector_specs,
    main_wrapper,
    utc_now,
    vector_config_draft,
    vector_manifest_item,
    write_json,
    write_memh,
)


def run() -> int:
    parser = argparse.ArgumentParser(description="Generate T-RECAP Phase 2 input test vectors from single-vector or vector-bundle configs")
    parser.add_argument("--configs", type=Path, default=Path("configs/vectors"), help="Vector config file or directory of vector-config bundles")
    parser.add_argument("--out", type=Path, default=Path("artifacts/test_vectors"))
    parser.add_argument("--coefficients", type=Path, default=Path("artifacts/coefficients"))
    parser.add_argument(
        "--suite",
        type=Path,
        default=None,
        help="Optional suite config selecting a subset/order from configs/vectors",
    )
    args = parser.parse_args()

    specs = load_vector_specs(args.configs)
    if args.suite is not None:
        specs = filter_specs_by_suite(specs, args.suite)
    if args.coefficients.exists() and (args.coefficients / "window_qw.memh").exists():
        coeff_hashes = coefficient_hashes_from_artifacts(args.coefficients)
    else:
        coeff_hashes = coefficient_hashes_from_tables(coefficient_tables())

    args.out.mkdir(parents=True, exist_ok=True)
    vectors = []
    for spec in specs:
        samples = generate_vector(spec)
        x_hash = canonical_memh_hash(samples, N, signed=True)
        vdir = args.out / spec.name
        vdir.mkdir(parents=True, exist_ok=True)
        write_memh(vdir / "x_in.memh", samples, N, signed=True)
        write_json(vdir / "config.json", vector_config_draft(spec, x_hash, coeff_hashes))
        vectors.append(vector_manifest_item(spec, x_hash, ZERO_SHA256))
        print(f"vector: wrote {spec.name} Ns={spec.ns} x_in_sha256={x_hash}")

    repo_root = Path(__file__).resolve().parents[1]
    generator_sources = sorted((repo_root / "python" / "trecap_golden" / "generators").glob("*.py"))
    source_hash = generated_source_hash(
        [
            Path(__file__).resolve(),
            Path(__file__).resolve().with_name("_trecap_tool_common.py"),
            *generator_sources,
        ]
    )
    manifest = {
        "schema": "trecap_phase2_test_vectors_v1",
        "spec_revision": SPEC_REVISION,
        "generator_version": GENERATOR_VERSION,
        "generator_source_sha256": source_hash,
        "created_utc": utc_now(),
        "vectors": vectors,
    }
    write_json(args.out / "test_vectors.json", manifest)
    print(f"vectors: wrote manifest {args.out / 'test_vectors.json'}")
    print("vectors: y_out_sha256 fields are finalized by tools/run_suite.py after golden execution")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
