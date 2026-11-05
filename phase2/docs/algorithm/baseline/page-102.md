# Baseline PDF page 102

Historical appendices and references. Printed page 89. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=102).

[Previous](page-101.md) | [Index](../README.md) | [Next](page-103.md)

[Edit Markdown and LaTeX source](../source/baseline/page-102.md). Equations are rendered locally as SVG.

## Appendices

## A Vendor FFT IP Contract Checklist

If a vendor FFT IP core replaces Algorithms 4 and 5, the following fields become mandatory in config.json and design documentation:

- IP vendor, IP name, and IP version.

- FFT length and transform direction support.

- input order and output order.

- scaling schedule or block-floating configuration.

- rounding mode.

- saturation, wrapping, or overflow behavior.

- twiddle precision and convention.

- complex input/output packing convention.

- latency from frame acceptance to output availability.

- DC/Nyquist handling if a real-input optimization is used.

- exact reset and first-frame behavior relevant to artifacts. A mathematically equivalent FFT is not sufficient for bit-accurate signoff if it does not reproduce the same integer outputs.

## B Phase 1 Mathematical Anchor

For each Phase 1 pair,

![Equation B.1: a&#91;k&#93;=x_0&#91;k&#93;+x_1&#91;k&#93;,&#92;qquad d&#91;k&#93;=x_0&#91;k&#93;-x_1&#91;k&#93;.&#92;tag{B.1}](../math/baseline-page-102-001.svg)

The suppression flag is 1,

![Equation B.2: s_k=&#92;begin{cases}1,&&#124;d&#91;k&#93;&#124;<T&#92;&#92;0,&&#124;d&#91;k&#93;&#124;&#92;ge T.&#92;end{cases}&#92;tag{B.2}](../math/baseline-page-102-002.svg)

The modified detail is d′ [k] = (1 - sk )d[k], and reconstruction is

![Equation B.3: y_0&#91;k&#93;=&#92;operatorname{sat}_N(&#92;operatorname{rnd2}(a&#91;k&#93;+d^{&#92;prime}&#91;k&#93;)).&#92;tag{B.3}](../math/baseline-page-102-003.svg)

![Equation B.4: y_1&#91;k&#93;=&#92;operatorname{sat}_N(&#92;operatorname{rnd2}(a&#91;k&#93;-d^{&#92;prime}&#91;k&#93;)).&#92;tag{B.4}](../math/baseline-page-102-004.svg)

If T = 0, the condition |d[k]| < 0 is never true, so d′ [k] = d[k] and Phase 1 reconstructs exactly. Phase 2 inherits the verification principle rather than the exact identity: every approximation must be explicit and reproducible.
