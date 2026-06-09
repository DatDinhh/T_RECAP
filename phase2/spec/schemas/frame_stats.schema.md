# `frame_stats.csv` schema

This file is the CSV contract for `artifacts/golden/<vector_name>/frame_stats.csv`.
It is intentionally documented as Markdown rather than JSON Schema because the artifact is CSV, not JSON.

## Purpose

`frame_stats.csv` records one row per signoff STFT frame. The row values are the frame-level spectral-accounting counters emitted by the golden model after Hermitian canonicalization, threshold comparison, protection rules, and final masking.

The file is a signoff artifact. It is not a plotting convenience file.

## Exact header

The first logical CSV line shall be exactly:

```csv
frame_idx,unique_bins,unique_suppressed_bins,eligible_unique_bins,eligible_suppressed_bins,eligible_kept_mag2,eligible_total_mag2
```

No extra columns are allowed in Revision J. Column names are lowercase and use underscores.

## Row count

For a vector with `frames = Nframes`, the file shall contain:

```text
1 header row + Nframes data rows
```

The `Nframes` value is the same value recorded as:

```text
config.json.configuration.frames
config.json.artifact_rows.frame_stats_data_rows
metrics.json.configuration.frames
```

## Field contract

| Column | Type | Required rule |
|---|---:|---|
| `frame_idx` | unsigned decimal integer | Zero-based frame index. First row is `0`; final row is `Nframes - 1`. |
| `unique_bins` | unsigned decimal integer | Number of unique bins for the frame. Baseline `L = 256` gives `129`. |
| `unique_suppressed_bins` | unsigned decimal integer | Count of final post-protection `mask[k] = 1` over all unique bins. |
| `eligible_unique_bins` | unsigned decimal integer | Count of bins eligible for suppression after protection eligibility is applied. |
| `eligible_suppressed_bins` | unsigned decimal integer | Count of eligible bins whose final mask is `1`. |
| `eligible_kept_mag2` | unsigned decimal integer | Weighted sum of kept eligible `mag2` values for the frame. |
| `eligible_total_mag2` | unsigned decimal integer | Weighted sum of all eligible `mag2` values for the frame. |

All values are base-10 ASCII integers. No hexadecimal, floating-point, scientific notation, separators, signs, blank cells, or `NaN` values are allowed.

## Ordering

Rows shall be sorted strictly by increasing `frame_idx`.

```text
row 1 data frame_idx = 0
row 2 data frame_idx = 1
...
row Nframes data frame_idx = Nframes - 1
```

A checker shall fail the file if any frame index is missing, repeated, or out of order.

## Baseline invariants

For the Revision J baseline:

```text
unique_bins = L/2 + 1 = 129
eligible_unique_bins = 128 when PROTECT_DC = 1 and PROTECT_NYQ = 0
0 <= unique_suppressed_bins <= unique_bins
0 <= eligible_suppressed_bins <= eligible_unique_bins
eligible_kept_mag2 <= eligible_total_mag2
```

When `THR2 = "0"`, every eligible mask decision shall be zero, so `eligible_suppressed_bins` shall be zero for every frame.

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
2. Parse each remaining line as seven comma-separated unsigned decimal integers.
3. Confirm the number of data rows equals config.artifact_rows.frame_stats_data_rows.
4. Confirm frame_idx equals the data-row number starting at zero.
5. Confirm baseline invariants for unique-bin counts and suppression bounds.
6. Confirm aggregate sums across rows match the corresponding metrics.json totals.
```
