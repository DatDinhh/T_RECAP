# Baseline PDF page 030

Historical Part I, core algorithm. Printed page 17. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=30).

[Previous](page-029.md) | [Index](../README.md) | [Next](page-031.md)

[Edit Markdown and LaTeX source](../source/baseline/page-030.md). Equations are rendered locally as SVG.

```json
      "threshold_mapping": "raw_thr2"
    },
    "widths": {
      "W_Qw": 16, "W_tw": 17, "W_u": 27,
      "W_fft": 28, "W_fft_pre": 29,
      "W_can_pre": 29, "W_can": 28,
      "W_mag2": 56, "W_ifft": 36,
      "W_z": 36, "W_ola": 37
    },
    "hashes": {
      "window_qw_sha256": "<sha256-hex>",
      "twiddle_re_sha256": "<sha256-hex>",
      "twiddle_im_sha256": "<sha256-hex>",
      "twiddle_inv_re_sha256": "<sha256-hex>",
      "twiddle_inv_im_sha256": "<sha256-hex>"
    },
    "stream_hashes": {
      "x_in_sha256": "<sha256-hex>",
      "y_out_sha256": "<sha256-hex>"
    },
    "artifact_rows": {
      "window_qw": 256,
      "twiddle_re": 256,
      "twiddle_im": 256,
      "twiddle_inv_re": 256,
      "twiddle_inv_im": 256,
      "x_in": 4096,
      "y_out": 4608,
      "frame_stats_data_rows": 33,
      "bin_stats_data_rows": 4257
    }
}
```

metrics.json.

```json
{
    "configuration": {
      "N": 12, "L": 256, "P": 8, "H": 128, "F": 15,
      "G": 128, "D": 384,
      "Ns": 4096, "Ny": 4608, "frames": 33,
      "THR2": "0",
      "PROTECT_DC": 1, "PROTECT_NYQ": 0
    },
    "contract": {
      "fft_mode": "custom_radix2_dit_bitrev_in_natural_out",
      "rounding_mode": "round_nearest_ties_away_from_zero",
      "tail_policy": "full_tail",
      "memh_encoding": "fixed_width_lowercase_hex_lf",
      "hash_rule": "logical_integer_vector_fixed_width_hex_lf"
    },
    "widths": {
      "W_Qw": 16, "W_tw": 17, "W_u": 27,
      "W_fft": 28, "W_fft_pre": 29,
      "W_can_pre": 29, "W_can": 28,
      "W_mag2": 56, "W_ifft": 36,
      "W_z": 36, "W_ola": 37
    },
    "hashes": {
      "window_qw_sha256": "<sha256-hex>",
      "twiddle_re_sha256": "<sha256-hex>",
      "twiddle_im_sha256": "<sha256-hex>",
      "twiddle_inv_re_sha256": "<sha256-hex>",
      "twiddle_inv_im_sha256": "<sha256-hex>"
    },
    "stream_hashes": {
      "x_in_sha256": "<sha256-hex>",
```
