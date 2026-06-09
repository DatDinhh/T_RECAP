# STFT/WOLA Contract

## Purpose

This document describes the Phase 2 finite-stream STFT/WOLA selective-suppression operator at the level the golden model must implement. It is not RTL architecture and not telemetry transport.

The golden model consumes a finite signed sample vector `x[0:Ns-1]`, zero-extends it, processes overlapping frames, applies frequency-domain suppression, reconstructs with WOLA, and emits a delayed output vector `y[0:Ny-1]` plus metrics and statistics.

## Baseline parameters

```text
N = 12
L = 256
P = 8
H = 128
F = 15
G = 128
D = L + G = 384
PROTECT_DC = 1
PROTECT_NYQ = 0
```

`THR2` is an unsigned magnitude-squared threshold with width `W_mag2 = 56`.

## Input zero extension

For finite signoff input:

```text
xz[n] = x[n]   when 0 <= n < Ns
        0      otherwise
```

`Ns` must be greater than zero for signoff vectors. Empty input is not a signoff case.

## Frame trigger timing

A frame trigger occurs whenever accepted sample count reaches a positive multiple of hop size:

```text
tau_m = (m + 1) * H
```

At trigger time `tau_m`, the frame contains the most recent `L` samples ending at `tau_m - 1`:

```text
xm[i] = xz[tau_m - L + i], 0 <= i < L
```

The frame contributes to output slots:

```text
tau_m + G + i
```

This creates exact causal delay:

```text
D = L + G
```

## Full-tail finite-stream policy

The default signoff policy is `full_tail`.

The active frame set is defined by active overlap after analysis windowing. For the baseline periodic square-root Hann table, `Qw[0] = 0` and `Qw[i] > 0` for `1 <= i < L`, so the closed-form frame count is:

```text
Nframes = floor((Ns + L - 2) / H)
tau_last = Nframes * H
Ny = tau_last + G + L
```

The driver must continue issuing sample ticks after real input ends. These post-input ticks use `xin = 0` and continue until exactly `Ny` output samples have been emitted.

A testbench that stops `sample_en` immediately after `Ns` real samples is not executing the signoff finite-stream contract.

## Windowing

The analysis and synthesis windows are identical periodic square-root Hann windows.

```text
hp[i] = 1/2 - 1/2*cos(2*pi*i/L)
w[i] = sqrt(hp[i])
Qw[i] = qcoef(w[i], F)
```

The quantized `Qw` table is a frozen artifact after release:

```text
artifacts/coefficients/window_qw.memh
```

Analysis windowing:

```text
u[i] = xz[tau_m - L + i] * Qw[i]
```

There is no rounding at this multiplication step before storage into the checked analysis width.

## Forward transform

The forward transform is the custom normalized radix-2 FFT defined in `fft_ifft_contract.md`:

```text
X = FFTnorm(u)
```

It returns natural-order complex bins with `F` fractional bits.

## Hermitian canonicalization

Because the input stream is real, the model canonicalizes the raw FFT output before thresholding. This makes mirrored pairs exact conjugates under the integer contract.

Self-conjugate bins:

```text
Xcan[0]   = Re(X[0])   + j0
Xcan[L/2] = Re(X[L/2]) + j0
```

Mirrored bins:

```text
R = rnd2(Re(X[k]) + Re(X[L-k]))
I = rnd2(Im(X[k]) - Im(X[L-k]))
Xcan[k]   = R + j*I
Xcan[L-k] = R - j*I
```

## Magnitude-squared masking

Unique bins are:

```text
k = 0..L/2
```

For each unique bin:

```text
mag2[k] = Re(Xcan[k])^2 + Im(Xcan[k])^2
pre_mask[k] = 1 if mag2[k] < THR2 else 0
mask[k] = pre_mask[k]
```

Protection then modifies the final mask:

```text
if PROTECT_DC == 1:
    mask[0] = 0
if PROTECT_NYQ == 1:
    mask[L/2] = 0
```

The final mask controls synthesis. The preliminary mask is debug-only.

## Masked spectrum

For interior bins:

```text
if mask[k] == 1:
    Xb[k] = 0
    Xb[L-k] = 0
else:
    Xb[k] = Xcan[k]
    Xb[L-k] = Xcan[L-k]
```

For DC and Nyquist:

```text
Xb[0]   = 0 if mask[0]   else Xcan[0]
Xb[L/2] = 0 if mask[L/2] else Xcan[L/2]
```

`Xb` is conjugate symmetric by construction.

## Frame statistics

Per-frame statistics must be computed from the final mask and eligibility rules.

Unique-bin weight:

```text
wgt[k] = 1 for k = 0 or k = L/2
         2 for 1 <= k <= L/2 - 1
```

Eligibility:

```text
eligible[k] = 0 when k = 0   and PROTECT_DC  == 1
              0 when k = L/2 and PROTECT_NYQ == 1
              1 otherwise
```

Required frame fields:

```text
unique_bins
unique_suppressed_bins
eligible_unique_bins
eligible_suppressed_bins
eligible_kept_mag2
eligible_total_mag2
```

`eligible_suppressed_bins / eligible_unique_bins` is the preferred workload proxy. It excludes protected bins from the denominator.

## Inverse transform and synthesis

The inverse transform is the custom unscaled radix-2 IFFT:

```text
v = IFFTunscaled(Xb)
```

Synthesis windowing:

```text
z[i] = rnd_shr(Re(v[i]) * Qw[i], F)
```

WOLA accumulation:

```text
A[tau_m + G + i] += z[i]
```

The output sample is:

```text
y[n] = satN(rnd_shr(A[n], F))
```

The delay-aligned error is:

```text
e[n] = xz[n - D] - y[n]
```

## Ring-equivalent executable schedule

The golden model may implement direct arrays or ring buffers. The externally visible sequence must be equivalent to:

1. read one sample tick, real input until `Ns`, then zero flush;
2. write sample into input ring;
3. emit current WOLA output slot;
4. compute delay-aligned error against `xz[n-D]`;
5. clear consumed OLA slot;
6. trigger a frame on every multiple of `H` until `tau_last`;
7. process analysis, mask, synthesis, and WOLA addition;
8. stop after `Ny` emitted samples.

## Required invariants

The checker should assert these invariants for every run:

| ID | Invariant |
|---|---|
| INV1 | Every emitted `y[n]` is compared against `xz[n-D]`. |
| INV2 | Under `full_tail`, post-input samples after `Ns + D - 1` are scored against zero. |
| INV3 | If `THR2 = 0`, every eligible final mask decision is zero. |
| INV4 | For `1 <= k <= L/2 - 1`, `Xb[L-k] = conj(Xb[k])`. |
| INV5 | DC and Nyquist are real-valued after canonicalization. |
| INV6 | All precision-reducing shifts use `rnd_shr` or `rnd2`. |
| INV7 | The OLA accumulator does not wrap internally on signoff vectors. |
| INV8 | Frame count equals `floor((Ns + L - 2) / H)` for the baseline full-tail policy. |

## Debug strategy

When output mismatch occurs:

1. verify `config.json` and width schedule first;
2. verify coefficient hashes;
3. verify `x_in.memh` canonical hash;
4. compare `frame_stats.csv` row by row;
5. if available, compare `bin_stats.csv` for the first mismatching frame;
6. only then inspect `y_out.memh` sample mismatch.

A time-domain mismatch is often a symptom. The root cause is usually a rounding, canonicalization, mask, twiddle, or finite-tail error earlier in the pipeline.

