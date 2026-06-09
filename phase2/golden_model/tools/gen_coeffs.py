#!/usr/bin/env python3
"""Generate frozen coefficient memh files and coeff_manifest.json."""
from __future__ import annotations

import argparse
from pathlib import Path

from _trecap_tool_common import (
    F,
    GENERATOR_VERSION,
    HASH_RULE,
    L,
    MEMH_ENCODING,
    SPEC_REVISION,
    W_QW,
    W_TW,
    base_configuration,
    coefficient_hashes_from_tables,
    coefficient_tables,
    contract,
    generated_source_hash,
    main_wrapper,
    utc_now,
    widths,
    write_json,
    write_memh,
)


def build_manifest(out_dir: Path, source_hash: str) -> dict:
    tables = coefficient_tables()
    hashes = coefficient_hashes_from_tables(tables)
    coeffs = {
        "window_qw": {
            "file": "window_qw.memh",
            "rows": L,
            "width_bits": W_QW,
            "signed": False,
            "q_format": "Q0.15_unsigned_endpoint_one",
            "sha256": hashes["window_qw_sha256"],
            "canonical_sha256": hashes["window_qw_sha256"],
        },
        "twiddle_re": {
            "file": "twiddle_re.memh",
            "rows": L,
            "width_bits": W_TW,
            "signed": True,
            "q_format": "Q1.15_signed_endpoint_one",
            "sha256": hashes["twiddle_re_sha256"],
            "canonical_sha256": hashes["twiddle_re_sha256"],
        },
        "twiddle_im": {
            "file": "twiddle_im.memh",
            "rows": L,
            "width_bits": W_TW,
            "signed": True,
            "q_format": "Q1.15_signed_endpoint_one",
            "sha256": hashes["twiddle_im_sha256"],
            "canonical_sha256": hashes["twiddle_im_sha256"],
        },
        "twiddle_inv_re": {
            "file": "twiddle_inv_re.memh",
            "rows": L,
            "width_bits": W_TW,
            "signed": True,
            "q_format": "Q1.15_signed_endpoint_one",
            "sha256": hashes["twiddle_inv_re_sha256"],
            "canonical_sha256": hashes["twiddle_inv_re_sha256"],
        },
        "twiddle_inv_im": {
            "file": "twiddle_inv_im.memh",
            "rows": L,
            "width_bits": W_TW,
            "signed": True,
            "q_format": "Q1.15_signed_endpoint_one",
            "sha256": hashes["twiddle_inv_im_sha256"],
            "canonical_sha256": hashes["twiddle_inv_im_sha256"],
        },
    }
    return {
        "schema": "trecap_phase2_coeff_manifest_v1",
        "spec_revision": SPEC_REVISION,
        "generator_version": GENERATOR_VERSION,
        "generator_source_sha256": source_hash,
        "created_utc": utc_now(),
        "configuration": base_configuration("0"),
        "contract": {
            "qcoef_rule": "round_nearest_ties_away_from_zero",
            "memh_encoding": MEMH_ENCODING,
            "hash_rule": HASH_RULE,
        },
        "widths": widths(),
        "coefficients": coeffs,
        "hashes": hashes,
        "artifact_rows": {
            "window_qw": L,
            "twiddle_re": L,
            "twiddle_im": L,
            "twiddle_inv_re": L,
            "twiddle_inv_im": L,
        },
    }


def run() -> int:
    parser = argparse.ArgumentParser(description="Generate T-RECAP Phase 2 coefficient artifacts")
    parser.add_argument("--out", type=Path, default=Path("artifacts/coefficients"))
    args = parser.parse_args()

    tables = coefficient_tables()
    args.out.mkdir(parents=True, exist_ok=True)
    write_memh(args.out / "window_qw.memh", tables["window_qw"], W_QW, signed=False)
    write_memh(args.out / "twiddle_re.memh", tables["twiddle_re"], W_TW, signed=True)
    write_memh(args.out / "twiddle_im.memh", tables["twiddle_im"], W_TW, signed=True)
    write_memh(args.out / "twiddle_inv_re.memh", tables["twiddle_inv_re"], W_TW, signed=True)
    write_memh(args.out / "twiddle_inv_im.memh", tables["twiddle_inv_im"], W_TW, signed=True)

    source_hash = generated_source_hash([Path(__file__).resolve(), Path(__file__).resolve().with_name("_trecap_tool_common.py")])
    write_json(args.out / "coeff_manifest.json", build_manifest(args.out, source_hash))
    print(f"coeffs: wrote {args.out}")
    return 0


if __name__ == "__main__":
    main_wrapper(run)
