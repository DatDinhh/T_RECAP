# Baseline PDF page 016

Historical Part I, core algorithm. Printed page 3. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=16).

[Previous](page-015.md) | [Index](../README.md) | [Next](page-017.md)

[Edit Markdown and LaTeX source](../source/baseline/page-016.md). Equations are rendered locally as SVG.

At trigger time ![&#92;tau_m](../math/baseline-page-016-001.svg), the frame contains the most recent ![L](../math/baseline-page-016-002.svg) samples ending at ![&#92;tau_m-1](../math/baseline-page-016-003.svg):

![Equation 2.3: x_m&#91;i&#93;=x&#91;&#92;tau_m-L+i&#93;,&#92;qquad 0&#92;le i<L.&#92;tag{2.3}](../math/baseline-page-016-004.svg)

That frame contributes to output slots ![&#92;tau_m+G+i](../math/baseline-page-016-005.svg). Therefore sample ![x&#91;&#92;tau_m-L+i&#93;](../math/baseline-page-016-006.svg) contributes to ![y&#91;&#92;tau_m+G+i&#93;](../math/baseline-page-016-007.svg), which establishes the delay ![D=L+G](../math/baseline-page-016-008.svg).

### 2.3 Finite-stream signoff policy

For a finite input vector ![x&#91;0&#93;,&#92;ldots,x&#91;N_s-1&#93;](../math/baseline-page-016-009.svg), define zero extension:

![Equation 2.4: x_z&#91;n&#93;=&#92;begin{cases}x&#91;n&#93;,&0&#92;le n<N_s&#92;&#92;0,&&#92;text{otherwise.}&#92;end{cases}&#92;tag{2.4}](../math/baseline-page-016-010.svg)

Revision J signoff vectors require ![N_s>0](../math/baseline-page-016-011.svg). Empty input is not a signoff case. The default finite-stream policy is `full_tail`. Revision J defines the signoff frame set by active overlap after analysis-windowing, not only by raw finite-input overlap:

![Equation 2.5: &#92;mathcal{M}_{&#92;mathrm{active}}=&#92;{m&#92;in&#92;mathbb{N}_0:&#92;exists i&#92;in&#92;{0,&#92;ldots,L-1&#92;}&#92;text{ such that }Q_w&#91;i&#93;&#92;ne0&#92;text{ and }0&#92;le&#92;tau_m-L+i<N_s&#92;}.&#92;tag{2.5}](../math/baseline-page-016-012.svg)

This prevents a zero-window edge frame from contributing artificial all-zero frame statistics when the only remaining real input sample lies at an analysis-window index whose quantized coefficient is zero. For the periodic square-root Hann baseline, ![Q_w&#91;0&#93;=0](../math/baseline-page-016-013.svg) and ![Q_w&#91;i&#93;>0](../math/baseline-page-016-014.svg) for ![1&#92;le i<L](../math/baseline-page-016-015.svg), so the active-frame set reduces to

![Equation 2.6: &#92;mathcal{M}_{&#92;mathrm{active}}=&#92;{m&#92;in&#92;mathbb{N}_0:&#92;tau_m=(m+1)H&#92;le N_s+L-2&#92;}.&#92;tag{2.6}](../math/baseline-page-016-016.svg)

For ![N_s>0](../math/baseline-page-016-017.svg), the required closed-form frame-count invariant is therefore

![Equation 2.7: N_{&#92;mathrm{frames}}=&#92;left&#92;lfloor&#92;frac{N_s+L-2}{H}&#92;right&#92;rfloor.&#92;tag{2.7}](../math/baseline-page-016-018.svg)

Let

![Equation 2.8: &#92;tau_{&#92;mathrm{last}}=N_{&#92;mathrm{frames}}H.&#92;tag{2.8}](../math/baseline-page-016-019.svg)

The full-tail emitted length is

![Equation 2.9: N_y=&#92;tau_{&#92;mathrm{last}}+G+L.&#92;tag{2.9}](../math/baseline-page-016-020.svg)

For a future window table with a different zero pattern, the general definition of ![&#92;mathcal{M}_{&#92;mathrm{active}}](../math/baseline-page-016-021.svg) is normative and the closed-form shortcut above must be re-derived. Under `full_tail`, the driver shall continue asserting sample ticks after the ![N_s](../math/baseline-page-016-022.svg) real input samples. Every post-input tick uses ![x_{&#92;mathrm{in}}=0](../math/baseline-page-016-023.svg) from the zero-extended stream, and ticks continue until exactly ![N_y](../math/baseline-page-016-024.svg) output samples have been emitted. These post-input values are flush samples. They are not counted as original input samples. A board replay or RTL testbench that stops sample-enable immediately after ![N_s](../math/baseline-page-016-025.svg) real samples is not executing the Revision J finite-stream contract. An optional diagnostic policy `fixed_delay_truncate` may set

![Equation 2.10: N_y=N_s+D.&#92;tag{2.10}](../math/baseline-page-016-026.svg)

That policy intentionally truncates post-interval tail energy and is not the Revision J signoff default.
