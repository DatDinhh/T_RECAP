# Artifact Contract

## Purpose

This document defines the file-level contract for all golden-model artifacts. Artifacts must be deterministic, schema-checkable, row-count-checkable, and hashable. A file that is easy for a human to read but hard for a checker to validate is not acceptable for signoff.

## Artifact directory layout

The golden repository uses this layout:

```text
artifacts/
├── coefficients/
│   ├── window_qw.memh
│   ├── twiddle_re.memh
│   ├── twiddle_im.memh
│   ├── twiddle_inv_re.memh
│   ├── twiddle_inv_im.memh
│   └── coeff_manifest.json
│
├── test_vectors/
│   ├── test_vectors.json
│   └── <vector_name>/
│       ├── x_in.memh
│       └── config.json
│
├── golden/
│   └── <vector_name>/
│       ├── y_out.memh
│       ├── frame_stats.csv
│       ├── metrics.json
│       └── bin_stats.csv          # conditional
│
└── manifests/
    ├── quality_bounds.json
    ├── artifact_index.json
    ├── stream_hashes.json
    └── frozen_release_manifest.json
```

`out/` and `runs/` are not frozen artifact directories. They are local build/run output.

## Required coefficient artifacts

| File | Contract |
|---|---|
| `window_qw.memh` | unsigned `W_Qw = F + 1`, exactly `L` lines |
| `twiddle_re.memh` | signed `W_tw`, exactly `L` lines |
| `twiddle_im.memh` | signed `W_tw`, exactly `L` lines |
| `twiddle_inv_re.memh` | signed `W_tw`, exactly `L` lines |
| `twiddle_inv_im.memh` | signed `W_tw`, exactly `L` lines |
| `coeff_manifest.json` | coefficient configuration, widths, source version, canonical hashes, row counts |

The baseline stores `L` twiddle entries even if RTL later compacts ROM internally. Internal ROM compaction must not change the external artifact contract.

## Required stream artifacts

For each vector:

| File | Contract |
|---|---|
| `x_in.memh` | input stream, signed `N`-bit two's-complement hex, exactly `Ns` lines |
| `config.json` | vector configuration, contract strings, widths, hashes, row counts |
| `y_out.memh` | reconstructed output stream, signed `N`-bit two's-complement hex, exactly `Ny` lines |
| `frame_stats.csv` | one header row plus exactly `Nframes` rows |
| `metrics.json` | aggregate counters under exact schema |
| `bin_stats.csv` | optional debug artifact; required only when manifest says it is required |

## Row-count rules

For each vector:

```text
window_qw rows        = L
twiddle_* rows        = L
x_in rows             = Ns
y_out rows            = Ny
frame_stats data rows = Nframes
bin_stats data rows   = Nframes * (L/2 + 1), when enabled
```

For baseline `L = 256`, each bin-stats frame has `129` rows.

The checker must verify actual row counts against `config.json.artifact_rows` and the global contract.

## `frame_stats.csv`

The header must be exactly:

```text
frame_idx,unique_bins,unique_suppressed_bins,eligible_unique_bins,eligible_suppressed_bins,eligible_kept_mag2,eligible_total_mag2
```

Rules:

- all values are decimal unsigned integers;
- `frame_idx` is zero-based;
- rows are emitted in increasing `frame_idx` order;
- there is exactly one logical header row;
- there are no comments or blank lines.

## `bin_stats.csv`

When present, the header must be exactly:

```text
frame_idx,bin_idx,real,imag,mag2,eligible,pre_mask,mask
```

Rules:

- `frame_idx` and `bin_idx` are unsigned decimal integers;
- `real` and `imag` are signed decimal integers;
- `mag2` is an unsigned decimal integer;
- `eligible`, `pre_mask`, and `mask` are `0` or `1`;
- rows are sorted first by `frame_idx`, then by `bin_idx` from `0` to `L/2`.

`bin_stats.csv` is intentionally conditional. For ordinary signoff vectors, it may be omitted to reduce artifact size. For near-threshold and debug vectors, it should be present.

## JSON integer rule

Any aggregate counter, `mag2`-derived field, or integer wider than 53 bits must be encoded as a decimal string.

Reason: many JSON consumers use IEEE-754 double precision for numbers. Integers above `2^53` cannot be represented exactly as JSON numbers in those environments.

Acceptable:

```json
{
  "eligible_total_mag2": "12345678901234567890"
}
```

Not acceptable for a wide field:

```json
{
  "eligible_total_mag2": 12345678901234567890
}
```

Small configuration integers such as `N`, `L`, `H`, `F`, and `D` may be JSON numbers.

## Required `config.json` blocks

Each vector `config.json` must include at least:

```json
{
  "configuration": {},
  "contract": {},
  "widths": {},
  "hashes": {},
  "stream_hashes": {},
  "artifact_rows": {}
}
```

Required `configuration` keys:

```text
N, L, P, H, F, G, D, Ns, Ny, frames, THR2, PROTECT_DC, PROTECT_NYQ
```

Required `contract` keys:

```text
fft_mode
rounding_mode
tail_policy
threshold_mapping
```

Required `widths` keys are listed in `fixed_point_widths.md`.

Required coefficient hash keys:

```text
window_qw_sha256
twiddle_re_sha256
twiddle_im_sha256
twiddle_inv_re_sha256
twiddle_inv_im_sha256
```

Required stream hash keys:

```text
x_in_sha256
y_out_sha256
```

`y_out_sha256` may be absent before golden output is generated. It must be present before release freeze.

## Required `metrics.json` blocks

Each vector `metrics.json` must include:

```json
{
  "configuration": {},
  "contract": {},
  "widths": {},
  "hashes": {},
  "stream_hashes": {},
  "suppression_totals": {},
  "spectral_totals": {},
  "time_domain_errors": {}
}
```

Required suppression totals:

```text
unique_bins
unique_suppressed_bins
eligible_unique_bins
eligible_suppressed_bins
```

Required spectral totals:

```text
eligible_kept_mag2
eligible_total_mag2
```

Required time-domain error fields:

```text
sum_abs_err
sum_sq_err
max_abs_err
error_sample_count
```

## `test_vectors.json`

`test_vectors.json` is the frozen vector manifest. A vector is not a signoff vector unless this file records:

- vector name;
- `Ns`;
- generator name;
- generator parameters;
- `THR2`;
- `PROTECT_DC` and `PROTECT_NYQ`;
- `tail_policy`;
- rounding mode;
- `x_in_sha256`;
- `y_out_sha256` after golden generation.

Frequency parameters must use exact rational fields `f_num` and `f_den`. Phase fields must use decimal strings such as `"0.5"`. Legacy strings such as `"23/256"` are not part of the baseline schema.

## `quality_bounds.json`

This is a single global manifest under:

```text
artifacts/manifests/quality_bounds.json
```

It is keyed by vector name and freezes no-suppression quality limits after the first complete golden-model release.

Do not create one quality-bound file per vector unless a later spec revision changes this rule.

## Artifact authority

After freeze:

```text
canonical file + canonical sha256 = authority
```

Generator equations and source code are not enough. A regenerated artifact is accepted only if the canonical hash matches.

## Checker responsibilities

`tools/artifact_check.py` should check:

1. all required files exist;
2. no required artifact is empty;
3. all `memh` files are canonical or can be normalized to canonical form;
4. canonical hashes match manifests;
5. line counts match `artifact_rows`;
6. CSV headers are exact;
7. CSV rows are sorted and count-correct;
8. JSON schemas validate;
9. wide integer fields are encoded as decimal strings;
10. `THR2` is in range;
11. `THR2=0` vectors have zero eligible masks;
12. conditional `bin_stats.csv` presence matches `artifact_rows`.

The checker should fail closed. Missing metadata is a failure, not a warning.

