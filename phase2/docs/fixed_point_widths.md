# Fixed-Point Widths

## Purpose

This document freezes the baseline storage and internal width schedule for the custom radix-2 Phase 2 golden model. Widths are part of the contract. They are not performance suggestions.

A mismatch in width can produce a one-bit difference after rounding, which then changes masks, WOLA output, metrics, and final hashes.

## Baseline symbols

| Symbol | Meaning | Baseline |
|---|---|---:|
| `N` | external signed sample width | 12 |
| `L` | FFT length | 256 |
| `P` | radix-2 stages, `log2(L)` | 8 |
| `H` | hop size | 128 |
| `F` | fractional width for coefficients/data | 15 |
| `G` | scheduling cushion | 128 |
| `D` | exact delay `L + G` | 384 |

## Minimum width schedule

| Quantity | Symbol | Signedness | Width rule | Baseline |
|---|---|---|---|---:|
| External sample | `W_x` | signed | `N` | 12 |
| Window coefficient | `W_Qw` | unsigned | `F + 1` | 16 |
| Twiddle coefficient | `W_tw` | signed | `F + 2` | 17 |
| Analysis-windowed input | `W_u` | signed | `N + F` | 27 |
| Forward FFT stored real/imag | `W_fft` | signed | `W_u + 1` | 28 |
| Forward pre-round add/sub | `W_fft_pre` | signed | `W_fft + 1` | 29 |
| Canonical pre-round add/sub | `W_can_pre` | signed | `W_fft + 1` | 29 |
| Canonical real/imag | `W_can` | signed | `W_fft` | 28 |
| Magnitude-squared and `THR2` | `W_mag2` | unsigned | `2 * W_can` | 56 |
| Unscaled IFFT stored real/imag | `W_ifft` | signed | `W_can + P` | 36 |
| Synthesis-windowed sample | `W_z` | signed | `W_ifft` | 36 |
| OLA accumulator entry | `W_ola` | signed | `W_z + 1` | 37 |
| Spectral aggregate sums | `W_Esum` | unsigned or big integer | run dependent | arbitrary precision recommended |
| Time-error sums | `W_err` | signed/unsigned or big integer | run dependent | arbitrary precision recommended |

## Why `W_Qw = F + 1`

The periodic square-root Hann window reaches `+1.0`. With `F = 15`, `+1.0` quantizes to:

```text
32768 = 2^15
```

This value requires 16 unsigned bits. It does not fit in signed 16-bit Q1.15 as a positive value. Therefore the window table is unsigned 16-bit, not signed 16-bit.

## Why `W_tw = F + 2`

Twiddles must represent both:

```text
+1.0 -> +32768
-1.0 -> -32768
```

A signed 17-bit representation is required to hold both endpoints cleanly. The canonical `memh` width for 17 bits is five hex digits.

Examples:

```text
+32768 -> 08000
-32768 -> 18000
-1     -> 1ffff
```

## Analysis product rule

Analysis windowing computes:

```text
u[i] = x[i] * Qw[i]
```

`x[i]` is signed `N` bits. `Qw[i]` is unsigned `F + 1` bits. The product must be formed with at least `W_x + W_Qw` product bits before storage.

The frozen coefficient range satisfies:

```text
0 <= Qw[i] <= 2^F
```

Therefore the exact product fits in signed `W_u = N + F` bits. Storing into `W_u` is a checked exact assignment, not truncation.

If a future coefficient table can exceed `2^F`, `W_u` must be re-derived.

## FFT width rule

The custom forward FFT uses per-stage divide-by-two rounding. Stored FFT values use `W_fft = W_u + 1` bits. Stage pre-round add/sub paths use `W_fft_pre = W_fft + 1` bits.

The model must make sign extension explicit before every add/sub. Silent truncation before `rnd2` is illegal.

## Canonicalization width rule

For mirrored bins:

```text
R = rnd2(Re(X[k]) + Re(X[L-k]))
I = rnd2(Im(X[k]) - Im(X[L-k]))
```

The add/sub before `rnd2` uses `W_can_pre = W_fft + 1`. The stored canonical value uses `W_can = W_fft`.

Self-conjugate bins `0` and `L/2` must have zero imaginary value after canonicalization.

## Magnitude-squared width rule

Canonical bin components are signed `W_can`.

```text
mag2[k] = real^2 + imag^2
```

Each square must be exact. The sum uses at least `2 * W_can = 56` unsigned bits in the baseline.

The threshold register `THR2` has the same `W_mag2` width.

## IFFT width rule

The inverse FFT is unscaled. It does not divide by two at each stage. Therefore its storage width grows by `P` stages:

```text
W_ifft = W_can + P = 28 + 8 = 36
```

All inverse FFT additions/subtractions must be sign-extended before storage. No hidden wrap is allowed.

## Synthesis and WOLA width rule

Synthesis computes:

```text
z[i] = rnd_shr(Re(v[i]) * Qw[i], F)
```

`z[i]` stores in signed `W_z = W_ifft = 36` bits.

The overlap-add accumulator stores two overlapping frame contributions in the baseline, so it uses:

```text
W_ola = W_z + 1 = 37
```

A signoff vector must not wrap the OLA accumulator. The C++ model should check this, not assume it.

## Metric accumulator policy

Golden-model metrics should use arbitrary-precision integers or checked big enough integer types.

Why: the run length can change. Aggregate spectral sums and sum-squared-error grow with vector length. Hard-coding a native 64-bit type is unsafe unless a proof is supplied for the maximum run.

Recommended implementation:

| Metric | Type policy |
|---|---|
| `unique_bins` | arbitrary precision or checked `uint64_t` for known suite |
| `eligible_unique_bins` | arbitrary precision or checked `uint64_t` for known suite |
| `eligible_kept_mag2` | arbitrary precision |
| `eligible_total_mag2` | arbitrary precision |
| `sum_abs_err` | arbitrary precision |
| `sum_sq_err` | arbitrary precision |
| `max_abs_err` | checked native integer is fine |
| `error_sample_count` | arbitrary precision or checked `uint64_t` |

JSON serialization rules are defined in `artifact_contract.md`.

## Native C++ type guidance

Do not use a type only because it compiles. Use a type because it is proven to cover the intermediate.

Suggested implementation style:

```text
int64_t          -> narrow signed values with a proven bound
uint64_t         -> narrow unsigned values with a proven bound
__int128         -> product terms where supported
boost::multiprecision::cpp_int -> aggregate metrics and general checker logic
```

The public API should expose logical values and widths. The implementation may use larger host types internally.

## Width metadata in artifacts

Every vector `config.json` and `metrics.json` must record the width schedule used to produce the artifact.

Required width keys:

```json
{
  "W_Qw": 16,
  "W_tw": 17,
  "W_u": 27,
  "W_fft": 28,
  "W_fft_pre": 29,
  "W_can_pre": 29,
  "W_can": 28,
  "W_mag2": 56,
  "W_ifft": 36,
  "W_z": 36,
  "W_ola": 37
}
```

The checker should reject missing keys and should reject values inconsistent with the active `core_config.json`.

## Change-control rule

A width change is a contract change. It requires:

1. spec/schema update;
2. C++ model update;
3. coefficient/vector/golden artifact regeneration;
4. quality-bound regeneration;
5. release-manifest update;
6. explanation of which old hashes changed and why.

Do not merge a width change as a local cleanup.

