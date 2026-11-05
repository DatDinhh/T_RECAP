# Baseline PDF page 031

Historical Part I, core algorithm. Printed page 18. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=31).

[Previous](../../baseline/page-030.md) | [Index](../../README.md) | [Next](../../baseline/page-032.md)

```json
      "y_out_sha256": "<sha256-hex>"
    },
    "suppression_totals": {
      "unique_bins": "4257",
      "unique_suppressed_bins": "0",
      "eligible_unique_bins": "4224",
      "eligible_suppressed_bins": "0"
    },
    "spectral_totals": {
      "eligible_kept_mag2": "123456789012345",
      "eligible_total_mag2": "123456789012345"
    },
    "time_domain_errors": {
      "sum_abs_err": "123",
      "sum_sq_err": "456",
      "max_abs_err": "3",
      "error_sample_count": "4608"
    }
}
```

`test_vectors.json`.

```json
{
    "schema": "trecap_phase2_test_vectors_v1",
    "generator_version": "phase2_generators_revision_j",
    "generator_source_sha256": "<sha256-hex>",
    "vectors": [
      {
        "name": "zero_Ns4096_thr0",
        "Ns": 4096,
        "generator": "constant",
        "parameters": { "value": 0 },
        "THR2": "0",
        "PROTECT_DC": 1,
        "PROTECT_NYQ": 0,
        "tail_policy": "full_tail",
        "rounding": "round_nearest_ties_away_from_zero",
        "x_in_sha256": "<sha256-hex>",
        "y_out_sha256": "<sha256-hex>"
      },
      {
        "name": "near_threshold_multitone_example",
        "Ns": 4096,
        "generator": "multitone_sine_sum",
        "parameters": {
          "tones": [
            {"amplitude": 512, "f_num": 16, "f_den": 256, "phase_rad": "0"},
            {"amplitude": 128, "f_num": 23, "f_den": 256, "phase_rad": "0.5"}
          ]
        },
        "THR2": "<decimal-string>",
        "PROTECT_DC": 1,
        "PROTECT_NYQ": 0,
        "tail_policy": "full_tail",
        "rounding": "round_nearest_ties_away_from_zero",
        "x_in_sha256": "<sha256-hex>",
        "y_out_sha256": "<sha256-hex>"
      }
    ]
}
```

`quality_bounds.json`. Revision J treats `quality_bounds.json` as a single global quality-bound manifest under `artifacts/manifests/quality_bounds.json`. The manifest is keyed by vector name. It is not a separate per-vector file.
