# `bin_stats.csv` schema

This file is the CSV contract for the optional debug artifact `artifacts/golden/<vector_name>/bin_stats.csv`.
It is required only when the per-vector configuration declares `bin_stats_data_rows` or the vector manifest marks the vector as requiring bin statistics.

## Purpose

`bin_stats.csv` records one row for each unique bin of each signoff frame. It is mainly for near-threshold, small-regression, and mismatch-debug vectors. It exposes canonical real/imag values, magnitude-squared, eligibility, pre-protection mask, and final post-protection mask.

The file is optional, but when present and declared, it is a signoff artifact.

## Exact header

The first logical CSV line shall be exactly:

```csv
frame_idx,bin_idx,real,imag,mag2,eligible,pre_mask,mask
```

No extra columns are allowed in Revision J.

## Row count

If `bin_stats_data_rows` is present in `config.json.artifact_rows`, then `bin_stats.csv` shall exist and shall contain:

```text
1 header row + Nframes * (L/2 + 1) data rows
```

For the Revision J baseline with `L = 256`, this is:

```text
1 header row + Nframes * 129 data rows
```

If `bin_stats_data_rows` is absent, the file may be omitted. A checker shall not silently accept a present but undeclared `bin_stats.csv` in a frozen release unless the release policy explicitly permits extra debug artifacts.

## Field contract

| Column | Type | Required rule |
|---|---:|---|
| `frame_idx` | unsigned decimal integer | Zero-based STFT frame index. |
| `bin_idx` | unsigned decimal integer | Unique-bin index. Baseline range is `0` through `128`. |
| `real` | signed decimal integer | Canonicalized real part for the unique bin. |
| `imag` | signed decimal integer | Canonicalized imaginary part for the unique bin. Bins `0` and `L/2` shall have `imag = 0`. |
| `mag2` | unsigned decimal integer | Full-precision `real^2 + imag^2` in the magnitude-squared domain. |
| `eligible` | unsigned 0/1 | Suppression eligibility after protection policy is applied. |
| `pre_mask` | unsigned 0/1 | Raw threshold decision before protection forces. |
| `mask` | unsigned 0/1 | Final mask after protection rules. This is the value used for synthesis. |

All values are base-10 ASCII integers. No hexadecimal, floating-point, scientific notation, separators, blank cells, or `NaN` values are allowed.

## Ordering

Rows shall be sorted by increasing `frame_idx`, and within each frame by increasing `bin_idx`.

For each frame, the baseline bin sequence is exactly:

```text
0, 1, 2, ..., 128
```

A checker shall fail the file if any bin is missing, repeated, or out of order.

## Baseline invariants

For the Revision J baseline:

```text
0 <= bin_idx <= 128
eligible in {0, 1}
pre_mask in {0, 1}
mask in {0, 1}
mag2 = real*real + imag*imag
imag = 0 for bin_idx = 0
imag = 0 for bin_idx = 128
if PROTECT_DC = 1, then eligible = 0 and mask = 0 for bin_idx = 0
if PROTECT_NYQ = 1, then eligible = 0 and mask = 0 for bin_idx = 128
if eligible = 0 because of protection, mask shall be 0 even if pre_mask is 1
if THR2 = "0", then pre_mask = 0 for all bins and mask = 0 for all eligible bins
```

## CSV formatting

The canonical file shall use:

```text
UTF-8 compatible ASCII
comma delimiter
LF line endings
one final LF at end of file
no BOM
no comments
no quoted cells
no leading or trailing whitespace
```

A parser may accept CRLF for developer diagnostics, but the frozen artifact shall be normalized to LF before hashing.

## Validation checklist

```text
1. Read the first line and compare it byte-for-byte to the exact header.
2. Parse each remaining line as eight comma-separated integers with the signedness above.
3. Confirm the number of data rows equals config.artifact_rows.bin_stats_data_rows.
4. Confirm row order: frame_idx outer loop, bin_idx inner loop.
5. Recompute mag2 from real and imag and compare exactly.
6. Check protection and THR2=0 invariants.
7. Aggregate mask counts and weighted mag2 totals and compare against frame_stats.csv and metrics.json.
```
