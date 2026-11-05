# Baseline PDF page 023

Historical Part I, core algorithm. Printed page 10. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=23).

[Previous](page-022.md) | [Index](../README.md) | [Next](page-024.md)

[Edit Markdown and LaTeX source](../source/baseline/page-023.md). Equations are rendered locally as SVG.

```text
11:     Xcan[k] <- R + jI
12:     Xcan[L - k] <- R - jI
13: end for
14: for k = 0 to L/2 do
15:     mag2[k] <- Re{Xcan[k]}^2 + Im{Xcan[k]}^2
16:     pre_mask[k] <- 1 if mag2[k] < THR2 else 0
17:     mask[k] <- pre_mask[k]
18: end for
19: if PROTECT_DC = 1 then
20:     mask[0] <- 0
21: end if
22: if PROTECT_NYQ = 1 then
23:     mask[L/2] <- 0
24: end if
25: for k = 0 to L/2 do
26:     eligible[k] <- epsilon[k]
27:     wgt[k] <- 1 if k in {0, L/2} else 2
28: end for
29: unique_bins_this_frame <- L/2 + 1
30: unique_suppressed_bins_this_frame <- sum(k=0..L/2, mask[k])
31: eligible_unique_bins_this_frame <- sum(k=0..L/2, eligible[k])
32: eligible_suppressed_bins_this_frame <- sum(k=0..L/2, eligible[k]*mask[k])
33: eligible_total_mag2_this_frame <- sum(k=0..L/2, eligible[k]*wgt[k]*mag2[k])
34: eligible_kept_mag2_this_frame <- sum(k=0..L/2, eligible[k]*(1-mask[k])*wgt[k]*mag2[k])
35: for k = 1 to L/2 - 1 do
36:     if mask[k] = 1 then
37:         Xb[k] <- 0, Xb[L - k] <- 0
38:     else
39:         Xb[k] <- Xcan[k], Xb[L - k] <- Xcan[L - k]
40:     end if
41: end for
42: Xb[0] <- 0 if mask[0] = 1 else Xcan[0]
43: Xb[L/2] <- 0 if mask[L/2] = 1 else Xcan[L/2]
44: return (Xb, mag2, pre_mask, mask, frame_stats)
```

### Algorithm 3 ProcessFrameSynthesisWOLA: IFFT, synthesis window, and WOLA accumulation

```text
Require: masked spectrum Xb[0:L - 1], frame statistics, OLA ring buffer ola[0:D - 1], read pointer rd, scheduling cushion G
Ensure: updated OLA ring buffer and aggregate spectral statistics
1: v ← IFFTunscaled (Xb)
2: for i = 0 to L - 1 do
3:    vr [i] ← Re{v[i]}
4:    z[i] ← rnd_shr(vr [i]Qw [i], F )
5:    pi ← (rd + G + i) mod D
6:    ola[pi ] ←ola[pi ] + z[i]
7: end for
8: update unique-bin and eligible-bin suppression totals using frame_stats
9: update eligible_kept_mag2 and eligible_total_mag2 aggregate sums using frame_stats
```

### 5.1 Required invariants

INV1. Every emitted sample y[n] is compared against xz [n - D].

INV2. Under `full_tail`, post-input samples after Ns + D - 1 are scored against zero.
