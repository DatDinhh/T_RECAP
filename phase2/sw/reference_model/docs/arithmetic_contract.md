# Arithmetic Contract

## Purpose

This document defines the integer behavior that the C++ golden model must implement exactly. The goal is to remove every ambiguity that normally causes mismatch between software, RTL, and artifact checkers.

The arithmetic contract is not optional. Any helper function that changes these rules changes the golden truth.

## Numeric domains

An `N`-bit signed two's-complement sample belongs to:

```text
SN = [-2^(N-1), 2^(N-1)-1]
```

For the current baseline:

```text
N = 12
SN = [-2048, 2047]
```

All input stream samples `x[n]` and final output stream samples `y[n]` are signed `N`-bit values.

Internal values use wider signed or unsigned integer domains defined in `fixed_point_widths.md`. Internal wraparound is not allowed in the visible golden-model contract.

## Saturation

The signed `N`-bit saturation operator is:

```text
satN(z) = -2^(N-1)       when z < -2^(N-1)
          z              when -2^(N-1) <= z <= 2^(N-1)-1
          2^(N-1)-1      when z > 2^(N-1)-1
```

For `N = 12`:

| Input `z` | `sat12(z)` |
|---:|---:|
| -3000 | -2048 |
| -2048 | -2048 |
| -1 | -1 |
| 0 | 0 |
| 2047 | 2047 |
| 3000 | 2047 |

Saturation is used at the final output conversion to `N` bits and in generator clipping. Do not use saturation to hide internal overflow unless a later spec revision explicitly defines that behavior.

## Arithmetic right shift

`asr(z, k)` is sign-preserving arithmetic right shift by `k` bits. For integer arithmetic it is equivalent to floor division by `2^k`.

```text
asr(z, k) = floor(z / 2^k)
```

Examples:

| Expression | Result |
|---|---:|
| `asr(7, 1)` | 3 |
| `asr(6, 1)` | 3 |
| `asr(-3, 1)` | -2 |
| `asr(-4, 1)` | -2 |
| `asr(-5, 2)` | -2 |

Do not use C++ division by powers of two for negative values unless the implementation explicitly matches this floor semantics. C++ signed integer division truncates toward zero, which is not the same as arithmetic shift for negative odd values.

## Rounded right shift

All precision-reducing right shifts use round-to-nearest with ties away from zero.

For `s >= 1`:

```text
rnd_shr(v, s) = sign(v) * floor((abs(v) + 2^(s-1)) / 2^s)
```

The zero-shift case is defined explicitly:

```text
rnd_shr(v, 0) = v
```

Component-wise use applies for complex values.

Examples for `s = 1`:

| `v` | `rnd_shr(v, 1)` |
|---:|---:|
| -5 | -3 |
| -4 | -2 |
| -3 | -2 |
| -2 | -1 |
| -1 | -1 |
| 0 | 0 |
| 1 | 1 |
| 2 | 1 |
| 3 | 2 |
| 4 | 2 |
| 5 | 3 |

`rnd2(q)` is shorthand for `rnd_shr(q, 1)`.

## Coefficient quantization

All shared coefficient tables use:

```text
qcoef(c, F) = sign(c) * floor(abs(c) * 2^F + 1/2)
```

This is round-to-nearest with ties away from zero.

Do not use a language-default `round()` unless it is proven bit-for-bit equivalent for every coefficient value. Many libraries use banker's rounding or have platform-specific behavior around exact halves.

Baseline storage:

| Table | Signedness | Width | Reason |
|---|---:|---:|---|
| `window_qw.memh` | unsigned | `W_Qw = F + 1 = 16` | represents `0` through `+1.0` as `32768` |
| twiddle tables | signed | `W_tw = F + 2 = 17` | must represent both `-32768` and `+32768` |

A signed 16-bit Q1.15 twiddle ROM is not the baseline because it cannot represent `+1.0` exactly.

## Fixed-point products

If integer `a` has `Fa` fractional bits and integer `b` has `Fb` fractional bits, then the exact product has `Fa + Fb` fractional bits.

To return to `F` fractional bits:

```text
mulF(a, b; Fa, Fb) = rnd_shr(a*b, Fa + Fb - F)
```

This assumes `Fa + Fb >= F`.

No truncation may occur before the full-precision product is formed.

## Complex multiplication

For data operand:

```text
b = br + j*bi
```

and twiddle:

```text
w = wr + j*wi
```

where all components have `F` fractional bits:

```text
cmulr(b, w) = rnd_shr(br*wr - bi*wi, F)
cmuli(b, w) = rnd_shr(br*wi + bi*wr, F)
```

Rules:

1. product terms must be formed at full precision;
2. sum/difference must be formed before rounding;
3. rounding happens once per output component;
4. no intermediate truncation is allowed.

## Magnitude-squared thresholding

Magnitude-squared uses canonicalized FFT bins, not raw FFT bins.

```text
mag2[k] = Re(Xcan[k])^2 + Im(Xcan[k])^2
```

The threshold decision is:

```text
pre_mask[k] = 1 if mag2[k] < THR2 else 0
```

This is a strict less-than comparison in the unsigned magnitude-squared domain.

Legal baseline threshold range:

```text
0 <= THR2 < 2^W_mag2
W_mag2 = 56
```

Out-of-range threshold values are illegal for signoff. A wrapper may clamp or reject them, but the core golden contract uses legal values only.

## Protection rules

The preliminary mask is modified only by protection flags:

```text
if PROTECT_DC  == 1: mask[0]   = 0
if PROTECT_NYQ == 1: mask[L/2] = 0
```

`pre_mask` remains useful for debug. Synthesis uses the final `mask`, not `pre_mask`.

## Error metrics

The time-domain error is delay-aligned:

```text
e[n] = xz[n - D] - y[n]
```

where `xz` is the zero-extended input stream and `D = L + G`.

Required integer metrics:

```text
sum_abs_err       = sum(abs(e[n])) over n = 0..Ny-1
sum_sq_err        = sum(e[n]^2) over n = 0..Ny-1
max_abs_err       = max(abs(e[n]))
error_sample_count = Ny
```

RMSE may be reported, but it is derived. The signoff authority is the integer numerator/denominator data above.

## Golden-model implementation requirements

C++ implementation must provide explicit helpers for:

- `sat_signed(width, value)`;
- `asr(value, shift)`;
- `rnd_shr(value, shift)`;
- `qcoef(value, F)`;
- signed and unsigned width range checks;
- two's-complement encode/decode for canonical `memh`;
- checked product-width calculations;
- arbitrary-precision or checked-wide accumulators for metrics.

Do not rely on accidental compiler behavior.

## Minimum unit tests

The C++ self-test layer should include at least these cases:

| Test | Required checks |
|---|---|
| saturation edges | `sat12(-2049)`, `sat12(-2048)`, `sat12(2047)`, `sat12(2048)` |
| `asr` negatives | `asr(-3,1) == -2`, `asr(-5,2) == -2` |
| `rnd_shr` ties | positive and negative odd values for shifts 1, 2, and 15 |
| zero shift | `rnd_shr(v,0) == v` |
| `qcoef` endpoints | `qcoef(1.0,15) == 32768`, `qcoef(-1.0,15) == -32768` |
| complex multiply | multiply by `+1`, `-1`, `+j`, `-j` twiddles |
| threshold boundary | `mag2 = THR2-1`, `mag2 = THR2`, `mag2 = THR2+1` |
| protection | DC and Nyquist forced-keep behavior |

## Review rule

Any pull request that modifies arithmetic helpers must regenerate self-test expected data and explain why every downstream artifact hash changed or did not change.

