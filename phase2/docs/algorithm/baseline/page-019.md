# Baseline PDF page 019

Historical Part I, core algorithm. Printed page 6. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=19).

[Previous](page-018.md) | [Index](../README.md) | [Next](page-020.md)

[Edit Markdown and LaTeX source](../source/baseline/page-019.md). Equations are rendered locally as SVG.

### 3.5 Internal width schedule

**Table 3. Revision J minimum internal widths for the custom radix-2 baseline.**

| Quantity | Symbol | Width rule | Baseline |
| --- | --- | --- | --- |
| External sample | ![W_x](../math/baseline-page-019-001.svg) | signed ![N](../math/baseline-page-019-002.svg) | 12 |
| Window coefficient | ![W_{Q_w}](../math/baseline-page-019-003.svg) | unsigned ![F+1](../math/baseline-page-019-004.svg) | 16 |
| Twiddle coefficient | ![W_{&#92;mathrm{tw}}](../math/baseline-page-019-005.svg) | signed ![F+2](../math/baseline-page-019-006.svg) | 17 |
| Analysis-windowed input | ![W_u](../math/baseline-page-019-007.svg) | signed ![N+F](../math/baseline-page-019-008.svg) | 27 |
| Forward FFT stored real/imag | ![W_{&#92;mathrm{fft}}](../math/baseline-page-019-009.svg) | signed ![W_u+1](../math/baseline-page-019-010.svg) | 28 |
| Forward pre-round add/sub | ![W_{&#92;mathrm{fft,pre}}](../math/baseline-page-019-011.svg) | signed ![W_{&#92;mathrm{fft}}+1](../math/baseline-page-019-012.svg) | 29 |
| Canonical pre-round add/sub | ![W_{&#92;mathrm{can,pre}}](../math/baseline-page-019-013.svg) | signed ![W_{&#92;mathrm{fft}}+1](../math/baseline-page-019-014.svg) | 29 |
| Canonical real/imag | ![W_{&#92;mathrm{can}}](../math/baseline-page-019-015.svg) | signed ![W_{&#92;mathrm{fft}}](../math/baseline-page-019-016.svg) | 28 |
| Magnitude-squared and THR2 | ![W_{&#92;mathrm{mag2}}](../math/baseline-page-019-017.svg) | unsigned ![2W_{&#92;mathrm{can}}](../math/baseline-page-019-018.svg) | 56 |
| Unscaled IFFT stored real/imag | ![W_{&#92;mathrm{ifft}}](../math/baseline-page-019-019.svg) | signed ![W_{&#92;mathrm{can}}+P](../math/baseline-page-019-020.svg) | 36 |
| Synthesis-windowed sample | ![W_z](../math/baseline-page-019-021.svg) | signed ![W_{&#92;mathrm{ifft}}](../math/baseline-page-019-022.svg) | 36 |
| OLA accumulator entry | ![W_{&#92;mathrm{ola}}](../math/baseline-page-019-023.svg) | signed ![W_z+1](../math/baseline-page-019-024.svg) | 37 |
| Aggregate spectral sums | ![W_{E&#92;mathrm{sum}}](../math/baseline-page-019-025.svg) | At least ![W_{&#92;mathrm{mag2}}+&#92;lceil&#92;log_2(2N_{&#92;mathrm{frames}}L)&#92;rceil](../math/baseline-page-019-026.svg) or arbitrary precision | run dependent |
| Time-error sums | ![W_{&#92;mathrm{err}}](../math/baseline-page-019-027.svg) | Large enough for all emitted samples or arbitrary precision | run dependent |


The golden model should use arbitrary-precision integers for metric accumulators. RTL shall either provision enough accumulator width for the selected run length or expose and check overflow flags. Although the analysis product ![x_m&#91;i&#93;Q_w&#91;i&#93;](../math/baseline-page-019-028.svg) may be formed internally in at least ![W_x+W_{Q_w}](../math/baseline-page-019-029.svg) bits, the frozen baseline coefficient range ![0&#92;le Q_w&#91;i&#93;&#92;le2^F](../math/baseline-page-019-030.svg) guarantees that the exact product fits in signed ![W_u=N+F](../math/baseline-page-019-031.svg) bits. Storage into ![W_u](../math/baseline-page-019-032.svg) is therefore a range-checked exact assignment. It is not truncation. If a future coefficient table permits values above ![2^{F}](../math/baseline-page-019-033.svg), the ![W_u](../math/baseline-page-019-034.svg) rule must be re-derived.

## 4 STFT/WOLA Core Mathematics

### 4.1 Periodic square-root Hann window

Define the periodic Hann sequence

![Equation 4.1: h_p&#91;i&#93;=&#92;frac12-&#92;frac12&#92;cos&#92;left(&#92;frac{2&#92;pi i}{L}&#92;right),&#92;qquad0&#92;le i<L.&#92;tag{4.1}](../math/baseline-page-019-035.svg)

The analysis and synthesis windows are identical:

![Equation 4.2: w_a&#91;i&#93;=w_s&#91;i&#93;=w&#91;i&#93;=&#92;sqrt{h_p&#91;i&#93;}.&#92;tag{4.2}](../math/baseline-page-019-036.svg)

For H = L/2, ideal complementarity is

![Equation 4.3: w_a&#91;i&#93;w_s&#91;i&#93;+w_a&#91;i+H&#93;w_s&#91;i+H&#93;=1,&#92;qquad0&#92;le i<H.&#92;tag{4.3}](../math/baseline-page-019-037.svg)
