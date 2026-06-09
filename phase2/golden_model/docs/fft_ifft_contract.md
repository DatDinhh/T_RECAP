# FFT/IFFT Contract

## Purpose

This document freezes the custom radix-2 FFT/IFFT behavior used by the Phase 2 golden model. The FFT is not interchangeable with a library FFT unless the library path is proven bit-identical under the same integer ordering, scaling, twiddle, width, and rounding rules.

## Baseline transform shape

| Transform | Baseline |
|---|---|
| FFT length | `L = 256` |
| Stages | `P = 8` |
| Algorithm | radix-2 decimation-in-time |
| Input order | bit-reversed copy into working array |
| Output order | natural order |
| Forward scaling | divide by two at each stage using `rnd2` |
| Inverse scaling | unscaled, no stage divide |
| Twiddles | frozen `memh` artifacts |
| Data fractional width | `F = 15` |

## Bit reversal

Let `bitrevP(k)` be the `P`-bit bit-reversal of index `k`.

Forward initialization:

```text
A[k] = u[bitrevP(k)] + j0
```

Inverse initialization:

```text
B[k] = Xb[bitrevP(k)]
```

The output array after all stages is in natural order.

## Twiddle artifacts

Forward twiddle tables:

```text
Wr[e] = qcoef(cos(2*pi*e/L), F)
Wi[e] = qcoef(-sin(2*pi*e/L), F)
Wfwd[e] = Wr[e] + j*Wi[e]
```

Inverse twiddle tables:

```text
Wfr[e] = qcoef(cos(2*pi*e/L), F)
Wfi[e] = qcoef(+sin(2*pi*e/L), F)
Winv[e] = Wfr[e] + j*Wfi[e]
```

The inverse table is a separate frozen artifact. RTL must not regenerate it implicitly.

Required coefficient files:

```text
artifacts/coefficients/twiddle_re.memh
artifacts/coefficients/twiddle_im.memh
artifacts/coefficients/twiddle_inv_re.memh
artifacts/coefficients/twiddle_inv_im.memh
```

Each table has exactly `L` lines. For the baseline, each line is signed 17-bit fixed-width hex, five lowercase digits.

## Forward FFT algorithm

For each stage `s = 1..P`:

```text
span = 2^s
half = 2^(s-1)

for base in 0, span, 2*span, ... L-span:
    for j in 0..half-1:
        e = j * L / span
        t = cmul(A[base + j + half], Wfwd[e])
        a = A[base + j]
        A[base + j]        = rnd2(a + t)
        A[base + j + half] = rnd2(a - t)
```

`rnd2` is applied component-wise to complex values.

All add/sub operations must be sign-extended before `rnd2`. No truncation before rounding is allowed.

## Inverse FFT algorithm

For each stage `s = 1..P`:

```text
span = 2^s
half = 2^(s-1)

for base in 0, span, 2*span, ... L-span:
    for j in 0..half-1:
        e = j * L / span
        t = cmul(B[base + j + half], Winv[e])
        a = B[base + j]
        B[base + j]        = a + t
        B[base + j + half] = a - t
```

The inverse transform is unscaled. There is no per-stage `rnd2` on the butterfly add/sub results. Rounding still occurs inside `cmul` because twiddle multiplication returns to `F` fractional bits.

## Complex multiply rule

Complex multiply uses the contract in `arithmetic_contract.md`:

```text
cmulr(b, w) = rnd_shr(br*wr - bi*wi, F)
cmuli(b, w) = rnd_shr(br*wi + bi*wr, F)
```

Do not truncate product terms before summing. Do not round each product separately.

## Normalized forward / unscaled inverse pair

The forward FFT divides by two at every one of the `P` stages. Since `L = 2^P`, the forward transform is normalized by `1/L`.

The inverse FFT is unscaled. This pair is intentional:

```text
FFTnorm -> mask/canonicalize -> IFFTunscaled
```

The WOLA path then applies the synthesis window and final output rounding.

## Hermitian canonicalization boundary

The forward FFT result is not used directly for thresholding. It first goes through Hermitian canonicalization.

For self-conjugate bins:

```text
Xcan[0]   = Re(X[0])   + j0
Xcan[L/2] = Re(X[L/2]) + j0
```

For `1 <= k <= L/2 - 1`:

```text
R = rnd2(Re(X[k]) + Re(X[L-k]))
I = rnd2(Im(X[k]) - Im(X[L-k]))
Xcan[k]   = R + j*I
Xcan[L-k] = R - j*I
```

All threshold decisions use `Xcan`, not raw `X`.

## Vendor FFT IP rule

The custom algorithm above is the baseline. If a vendor FFT IP is introduced later, it is not automatically equivalent. The following must be frozen before it can replace the custom algorithm:

- IP vendor, name, and version;
- input and output order;
- scaling schedule;
- rounding mode;
- overflow behavior;
- twiddle precision and convention;
- complex packing;
- latency;
- reset and first-frame behavior;
- DC/Nyquist behavior;
- bit-exact comparison against the custom artifacts or an explicitly new artifact contract.

A mathematically equivalent FFT is insufficient for bit-accurate signoff.

## Minimum self-tests

Required C++ unit tests:

| Test | Expected property |
|---|---|
| zero input | all FFT and IFFT outputs zero |
| impulse input | deterministic spectrum under normalized forward scaling |
| constant input | only DC should dominate before quantization effects |
| exact-bin tone | dominant expected bin and Hermitian pair consistency |
| conjugate symmetry | `Xb[L-k] = conj(Xb[k])` after masking |
| self-conjugate bins | imaginary part of DC/Nyquist is zero |
| twiddle endpoints | `+1`, `-1`, `+j`, `-j` encodings and multiplication behavior |
| forward/inverse smoke | `THR2=0` path meets frozen quality bounds, not exact identity |

## Debug artifacts

When a vector enables `bin_stats.csv`, the model should expose canonical bin-level fields after canonicalization and masking:

```text
frame_idx,bin_idx,real,imag,mag2,eligible,pre_mask,mask
```

This is the fastest way to debug FFT/IFFT or mask mismatch. If `y_out.memh` mismatches, compare `frame_stats.csv` first, then `bin_stats.csv` for the earliest mismatching frame/bin.

