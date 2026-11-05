# Baseline PDF page 022

Historical Part I, core algorithm. Printed page 9. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=22).

[Previous](page-021.md) | [Index](../README.md) | [Next](page-023.md)

[Edit Markdown and LaTeX source](../source/baseline/page-022.md). Equations are rendered locally as SVG.

## 5 Normative Core Algorithm Tables

The algorithms in this section are normative mathematical procedures, not SystemVerilog module descriptions. To avoid notation ambiguity, the implementation-facing algorithm tables use ASCII identifiers: Xb for the masked spectrum, mag2 for the magnitude-squared array, `pre_mask` for the preliminary threshold result, and mask for the final post-protection unique-bin mask.

### Algorithm 1 Finite-stream Phase 2 core operator with full-tail scoring

```text
Require: finite input vector x[0:Ns - 1] with Ns > 0; frozen parameters (N, L, H, F, G, D); frozen coefficient tables; threshold
    register THR2
Ensure: output vector y[0:Ny - 1], delayed-error metrics, aggregate frame metrics
 1: Nframes ← ⌊(Ns + L - 2)/H⌋
 2: tau_last ← Nframes H
 3: Ny ← tau_last + G + L
 4: initialize xring[0:L - 1] ← 0, ola[0:D - 1] ← 0
 5: initialize wr ← 0, rd ← 0, sample_count ← 0, frame_count ← 0
 6: initialize all frame-statistic and time-error accumulators to zero
 7: for n = 0 to Ny - 1 do
 8:     xin ← x[n] if 0 ≤ n < Ns , else 0                                            ▷ zero flush sample after real input ends
 9:     xref ← x[n - D] if 0 ≤ n - D < Ns , else 0
10:      xring[wr] ← xin
11:      wr ← (wr + 1) mod L
12:      y[n] ← sat_N (rnd_shr(ola[rd], F ))
13:      e[n] ← xref - y[n]
14:      update sum_abs_err, sum_sq_err, max_abs_err, and error_sample_count
15:      ola[rd] ← 0
16:      rd ← (rd + 1) mod D
17:      sample_count ← sample_count + 1
18:      if sample_count mod H = 0 and sample_count ≤ tau_last then
19:          (Xb, mag2, pre_mask, mask, frame_stats) ← ProcessFrameAnalysisMask(xring, wr, THR2)
20:          ProcessFrameSynthesisWOLA(Xb, frame_stats, ola, rd, G)
21:          frame_count ← frame_count + 1
22:      end if
23: end for
24: assert frame_count = Nframes
25: return (y, Ny , frame_count, frame_stats, metrics)
```

### Algorithm 2 ProcessFrameAnalysisMask: frame construction, FFT, canonicalization, masking,

and frame statistics

```text
Require: input ring buffer xring[0:L - 1], write pointer wr, threshold register THR2
Ensure: masked spectrum Xb[0:L - 1], unique-bin mag2[0:L/2], pre-protection mask bits pre_mask[0:L/2], final mask bits
    mask[0:L/2], frame statistics
 1: for i = 0 to L - 1 do
 2:    xf [i] ← xring[(wr + i) mod L]                                                                    ▷ oldest to newest
 3:    u[i] ← xf [i]Qw[i]                                                           ▷ F fractional bits; no rounding here
 4: end for
 5: X ← FFTnorm (u)
 6: Xcan[0] ← Re{X[0]} + j0
 7: Xcan[L/2] ← Re{X[L/2]} + j0
 8: for k = 1 to L/2 - 1 do
 9:    R ← rnd2(Re{X[k]} + Re{X[L - k]})
10:     I ← rnd2(Im{X[k]} - Im{X[L - k]})
```
