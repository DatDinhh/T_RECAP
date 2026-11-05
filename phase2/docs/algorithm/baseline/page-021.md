# Baseline PDF page 021

Historical Part I, core algorithm. Printed page 8. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=21).

[Previous](page-020.md) | [Index](../README.md) | [Next](page-022.md)

[Edit Markdown and LaTeX source](../source/baseline/page-021.md). Equations are rendered locally as SVG.

### 4.5 Protection rules and masked spectrum

Define

![Equation 4.15: &#92;epsilon&#91;k&#93;=&#92;begin{cases}0,&k=0&#92;text{ and }&#92;mathrm{PROTECT&#92;_DC}=1&#92;&#92;0,&k=L/2&#92;text{ and }&#92;mathrm{PROTECT&#92;_NYQ}=1&#92;&#92;1,&&#92;text{otherwise.}&#92;end{cases}&#92;tag{4.15}](../math/baseline-page-021-001.svg)

After threshold comparison, if `PROTECT_DC`= 1, force ![&#92;operatorname{mask}_m&#91;0&#93;=0](../math/baseline-page-021-002.svg). If `PROTECT_NYQ`= 1, force ![&#92;operatorname{mask}_m&#91;L/2&#93;=0](../math/baseline-page-021-003.svg). The preliminary value `pre_mask` is retained only for debug reporting and never controls synthesis. The masked spectrum is denoted ![&#92;mathrm{Xb}](../math/baseline-page-021-004.svg). For ![1&#92;le k&#92;le L/2-1](../math/baseline-page-021-005.svg),

![Equation 4.16: &#92;mathrm{Xb}_m&#91;k&#93;=&#92;begin{cases}0,&&#92;operatorname{mask}_m&#91;k&#93;=1&#92;&#92;X_m^{&#92;mathrm{can}}&#91;k&#93;,&&#92;operatorname{mask}_m&#91;k&#93;=0.&#92;end{cases}&#92;tag{4.16}](../math/baseline-page-021-006.svg)

![Equation 4.17: &#92;mathrm{Xb}_m&#91;L-k&#93;=&#92;begin{cases}0,&&#92;operatorname{mask}_m&#91;k&#93;=1&#92;&#92;X_m^{&#92;mathrm{can}}&#91;L-k&#93;,&&#92;operatorname{mask}_m&#91;k&#93;=0.&#92;end{cases}&#92;tag{4.17}](../math/baseline-page-021-007.svg)

For self-conjugate bins,

![Equation 4.18: &#92;mathrm{Xb}_m&#91;0&#93;=(1-&#92;operatorname{mask}_m&#91;0&#93;)X_m^{&#92;mathrm{can}}&#91;0&#93;.&#92;tag{4.18}](../math/baseline-page-021-008.svg)

![Equation 4.19: &#92;mathrm{Xb}_m&#91;L/2&#93;=(1-&#92;operatorname{mask}_m&#91;L/2&#93;)X_m^{&#92;mathrm{can}}&#91;L/2&#93;.&#92;tag{4.19}](../math/baseline-page-021-009.svg)

The result is conjugate symmetric by construction.

### 4.6 Unscaled IFFT, synthesis window, and WOLA

The intended inverse is unscaled:

![Equation 4.20: v_m&#91;i&#93;=&#92;sum_{k=0}^{L-1}&#92;mathrm{Xb}_m&#91;k&#93;e^{j2&#92;pi ki/L},&#92;qquad0&#92;le i<L.&#92;tag{4.20}](../math/baseline-page-021-010.svg)

For the custom baseline, Algorithm 5 is normative. The synthesized frame contribution is

![Equation 4.21: z_m&#91;i&#93;=&#92;operatorname{rnd&#92;_shr}(&#92;operatorname{Re}&#92;{v_m&#91;i&#93;&#92;}Q_w&#91;i&#93;,F).&#92;tag{4.21}](../math/baseline-page-021-011.svg)

Each frame adds into the output accumulator:

![Equation 4.22: A&#91;&#92;tau_m+G+i&#93;&#92;leftarrow A&#91;&#92;tau_m+G+i&#93;+z_m&#91;i&#93;.&#92;tag{4.22}](../math/baseline-page-021-012.svg)

The emitted sample and delayed error are

![Equation 4.23: y&#91;n&#93;=&#92;operatorname{sat}_N(&#92;operatorname{rnd&#92;_shr}(A&#91;n&#93;,F)).&#92;tag{4.23}](../math/baseline-page-021-013.svg)

![Equation 4.24: e&#91;n&#93;=x_z&#91;n-D&#93;-y&#91;n&#93;.&#92;tag{4.24}](../math/baseline-page-021-014.svg)
