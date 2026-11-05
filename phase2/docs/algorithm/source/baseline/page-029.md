# Baseline PDF page 029

Historical Part I, core algorithm. Printed page 16. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=29).

[Previous](../../baseline/page-028.md) | [Index](../../README.md) | [Next](../../baseline/page-030.md)

### 7.9 CSV field contracts

The required `frame_stats.csv` header is exactly one logical CSV line, wrapped below only for page layout:

```csv
frame_idx,unique_bins,unique_suppressed_bins,
eligible_unique_bins,eligible_suppressed_bins,
eligible_kept_mag2,eligible_total_mag2
```

For `frame_stats.csv`, all values are decimal unsigned integers. The field `frame_idx` is zero-based and equals m for trigger $\tau_m=(m+1)H$. Rows shall be emitted in increasing `frame_idx` order from 0 to $N_{\mathrm{frames}}-1$. When present, the required `bin_stats.csv` header is exactly:

```csv
frame_idx,bin_idx,real,imag,mag2,eligible,pre_mask,mask
```

For `bin_stats.csv`, `frame_idx` and `bin_idx` are unsigned decimal integers, real and imag are signed decimal integers, mag2 is an unsigned decimal integer, and eligible, `pre_mask`, and mask are unsigned 0/1 values. Rows shall be emitted in increasing `frame_idx` order and, within each frame, in increasing `bin_idx` order from 0 to L/2.

### 7.10 JSON integer rule and schemas

All aggregate counters, all fields derived from mag2, and every integer field wider than 53 bits shall be encoded as decimal strings. Small configuration integers may be JSON numbers. Checkers shall parse decimal-string signoff fields as arbitrary-precision integers. Generator parameters shall not rely on binary floating-point parsing for signoff. Normalized frequencies are represented by integer fields `f_num` and `f_den`, meaning f = `f_num/f_den` as an exact rational number. Phase fields are represented as `phase_rad` decimal strings and shall be parsed as exact decimal values before evaluation. Legacy frequency strings of the form "a/b" are not part of the Revision J schema. The JSON blocks below are illustrative schema examples, not ready-to-freeze artifact files. Placeholder strings such as `<sha256-hex>` and `<decimal-string>` shall be replaced before a file is accepted by a parser or committed as a frozen manifest. Literal ellipses are not legal values in Revision J artifact JSON.

config.json.

```json
{
    "configuration": {
      "N": 12, "L": 256, "P": 8, "H": 128, "F": 15,
      "G": 128, "D": 384, "Ns": 4096, "Ny": 4608,
      "frames": 33, "THR2": "0",
      "PROTECT_DC": 1, "PROTECT_NYQ": 0
    },
    "contract": {
      "fft_mode": "custom_radix2_dit_bitrev_in_natural_out",
      "rounding_mode": "round_nearest_ties_away_from_zero",
      "tail_policy": "full_tail",
```
