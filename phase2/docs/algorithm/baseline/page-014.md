# Baseline PDF page 014

Historical Part I, core algorithm. Printed page 1. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=14).

[Previous](page-013.md) | [Index](../README.md) | [Next](page-015.md)

[Edit Markdown and LaTeX source](../source/baseline/page-014.md). Equations are rendered locally as SVG.

## Part I - Core Algorithm and Signoff Contract

## 1 Overview and Scope

### 1.1 Purpose

Part I of this integrated specification is the source-of-truth contract for the Phase 2 T-RECAP mathematical core. It is written for the software golden model, RTL-equivalent model, simulation scoreboards, BRAM replay signoff, and deterministic reconstruction/metric evaluation. It is not a SystemVerilog architecture document. It does not specify module names, pin assignments, packet formats, HPS software, or a PC dashboard. Those layers shall preserve the core behavior defined here.

### 1.2 Problem statement

The Phase 2 core problem is:

Define a causal fixed-point STFT/WOLA operator for a real-valued stream. The operator suppresses low-energy spectral bins under a frozen arithmetic contract and reconstructs a delayed time-domain output for bit-accurate verification.

### 1.3 Continuity from Phase 1

Phase 1 grouped the stream into non-overlapping pairs, applied a two-sample Haar transform, suppressed the detail term when |d[k]| < T , and reconstructed the pair. When T = 0, the condition |d[k]| < 0 is never true, so Phase 1 has exact lossless reconstruction. Phase 2 preserves the same selective-suppression idea but moves the transform domain from two-sample Haar pairs to overlapped STFT frames. The T = 0 identity property does not transfer exactly because Phase 2 contains quantized windows, twiddles, FFT/IFFT rounding, WOLA accumulation, and final output rounding. The Phase 2 no-suppression condition is therefore deterministic near-lossless, not exact lossless.

**Table 1. Mathematical continuity from Phase 1 to Phase 2.**

| Concept | Phase 1: Haar | Phase 2: STFT/WOLA |
| --- | --- | --- |
| Streaming unit | Pair ![(x&#91;2k&#93;,x&#91;2k+1&#93;)](../math/baseline-page-014-001.svg) | Overlapped frame ![x_m&#91;0:L-1&#93;](../math/baseline-page-014-002.svg) |
| Transform output | ![a&#91;k&#93;,d&#91;k&#93;](../math/baseline-page-014-003.svg) | ![X_m&#91;k&#93;](../math/baseline-page-014-004.svg) |
| Suppression variable | ![&#92;lvert d&#91;k&#93;&#92;rvert<T](../math/baseline-page-014-005.svg) | ![&#92;operatorname{mag2}&#91;k&#93;<&#92;mathrm{THR2}](../math/baseline-page-014-006.svg) |
| Mask action | ![d^{&#92;prime}&#91;k&#93;=(1-s_k)d&#91;k&#93;](../math/baseline-page-014-007.svg) | ![&#92;mathrm{Xb}&#91;k&#93;=(1-&#92;operatorname{mask}&#91;k&#93;)X^{&#92;mathrm{can}}&#91;k&#93;](../math/baseline-page-014-008.svg) |
| Reconstruction | Inverse Haar | IFFT + synthesis window + WOLA |
| Correctness anchor | Exact lossless at ![T=0](../math/baseline-page-014-009.svg) | Deterministic near-lossless at ![&#92;mathrm{THR2}=0](../math/baseline-page-014-010.svg) |
| Metrics | Suppressed pairs and time error | Suppressed eligible bins, kept spectral total, and time error |
