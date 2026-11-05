# Baseline PDF page 020

Historical Part I, core algorithm. Printed page 7. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=20).

[Previous](page-019.md) | [Index](../README.md) | [Next](page-021.md)

[Edit Markdown and LaTeX source](../source/baseline/page-020.md). Equations are rendered locally as SVG.

The quantized table is ![Q_w&#91;i&#93;=&#92;operatorname{qcoef}(w&#91;i&#93;,F)](../math/baseline-page-020-001.svg).

### 4.2 Analysis windowing and normalized FFT

For frame m,

![Equation 4.4: u_m&#91;i&#93;=x_z&#91;&#92;tau_m-L+i&#93;Q_w&#91;i&#93;,&#92;qquad0&#92;le i<L.&#92;tag{4.4}](../math/baseline-page-020-002.svg)

The intended normalized forward transform is

![Equation 4.5: X_m&#91;k&#93;=&#92;frac1L&#92;sum_{i=0}^{L-1}u_m&#91;i&#93;e^{-j2&#92;pi ki/L},&#92;qquad0&#92;le k<L.&#92;tag{4.5}](../math/baseline-page-020-003.svg)

For the custom baseline, Algorithm 4 is normative.

### 4.3 Hermitian canonicalization

For self-conjugate bins,

![Equation 4.6: X_m^{&#92;mathrm{can}}&#91;0&#93;=&#92;operatorname{Re}&#92;{X_m&#91;0&#93;&#92;}+j0.&#92;tag{4.6}](../math/baseline-page-020-004.svg)

![Equation 4.7: X_m^{&#92;mathrm{can}}&#91;L/2&#93;=&#92;operatorname{Re}&#92;{X_m&#91;L/2&#93;&#92;}+j0.&#92;tag{4.7}](../math/baseline-page-020-005.svg)

For 1 ≤ k ≤ L/2 - 1,

![Equation 4.8: R_m&#91;k&#93;=&#92;operatorname{rnd2}(&#92;operatorname{Re}&#92;{X_m&#91;k&#93;&#92;}+&#92;operatorname{Re}&#92;{X_m&#91;L-k&#93;&#92;}).&#92;tag{4.8}](../math/baseline-page-020-006.svg)

![Equation 4.9: I_m&#91;k&#93;=&#92;operatorname{rnd2}(&#92;operatorname{Im}&#92;{X_m&#91;k&#93;&#92;}-&#92;operatorname{Im}&#92;{X_m&#91;L-k&#93;&#92;}).&#92;tag{4.9}](../math/baseline-page-020-007.svg)

![Equation 4.10: X_m^{&#92;mathrm{can}}&#91;k&#93;=R_m&#91;k&#93;+jI_m&#91;k&#93;.&#92;tag{4.10}](../math/baseline-page-020-008.svg)

![Equation 4.11: X_m^{&#92;mathrm{can}}&#91;L-k&#93;=R_m&#91;k&#93;-jI_m&#91;k&#93;.&#92;tag{4.11}](../math/baseline-page-020-009.svg)

All threshold decisions use ![X^{&#92;mathrm{can}}](../math/baseline-page-020-010.svg), not the raw FFT output.

### 4.4 Magnitude-squared mask

For unique bins 0 ≤ k ≤ L/2,

![Equation 4.12: &#92;operatorname{mag2}_m&#91;k&#93;=&#92;operatorname{Re}&#92;{X_m^{&#92;mathrm{can}}&#91;k&#93;&#92;}^2+&#92;operatorname{Im}&#92;{X_m^{&#92;mathrm{can}}&#91;k&#93;&#92;}^2.&#92;tag{4.12}](../math/baseline-page-020-011.svg)

The preliminary mask bit before protection is

![Equation 4.13: &#92;operatorname{pre&#92;_mask}_m&#91;k&#93;=&#92;begin{cases}1,&&#92;operatorname{mag2}_m&#91;k&#93;<&#92;mathrm{THR2}&#92;&#92;0,&&#92;operatorname{mag2}_m&#91;k&#93;&#92;ge&#92;mathrm{THR2}.&#92;end{cases}&#92;tag{4.13}](../math/baseline-page-020-012.svg)

The final mask is initialized as ![&#92;operatorname{mask}_m&#91;k&#93;=&#92;operatorname{pre&#92;_mask}_m&#91;k&#93;](../math/baseline-page-020-013.svg) and may then be modified only by the protection rules in Section 4.5. The comparison is unsigned, full precision, and performed in the magnitude-squared domain. The threshold register width is ![W_{&#92;mathrm{mag2}}](../math/baseline-page-020-014.svg):

![Equation 4.14: 0&#92;le&#92;mathrm{THR2}<2^{W_{&#92;mathrm{mag2}}}.&#92;tag{4.14}](../math/baseline-page-020-015.svg)

Out-of-range values are illegal for core signoff.
