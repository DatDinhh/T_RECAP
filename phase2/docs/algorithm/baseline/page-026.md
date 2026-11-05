# Baseline PDF page 026

Historical Part I, core algorithm. Printed page 13. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=26).

[Previous](page-025.md) | [Index](../README.md) | [Next](page-027.md)

[Edit Markdown and LaTeX source](../source/baseline/page-026.md). Equations are rendered locally as SVG.

Let ![&#92;mathcal{E}=&#92;{k&#92;in&#92;{0,&#92;ldots,L/2&#92;}:&#92;epsilon&#91;k&#93;=1&#92;}](../math/baseline-page-026-001.svg). For one frame,

![Equation 7.2: U_{&#92;mathrm{uniq}}=L/2+1,&#92;qquad S_{&#92;mathrm{uniq}}=&#92;sum_{k=0}^{L/2}&#92;operatorname{mask}&#91;k&#93;.&#92;tag{7.2}](../math/baseline-page-026-002.svg)

![Equation 7.3: U_{&#92;mathrm{elig}}=&#124;&#92;mathcal E&#124;,&#92;qquad S_{&#92;mathrm{elig}}=&#92;sum_{k&#92;in&#92;mathcal E}&#92;operatorname{mask}&#91;k&#93;.&#92;tag{7.3}](../math/baseline-page-026-003.svg)

![Equation 7.4: E_{&#92;mathrm{elig,total}}=&#92;sum_{k&#92;in&#92;mathcal E}&#92;omega&#91;k&#93;&#92;operatorname{mag2}&#91;k&#93;,&#92;qquad E_{&#92;mathrm{elig,kept}}=&#92;sum_{k&#92;in&#92;mathcal E}(1-&#92;operatorname{mask}&#91;k&#93;)&#92;omega&#91;k&#93;&#92;operatorname{mag2}&#91;k&#93;.&#92;tag{7.4}](../math/baseline-page-026-004.svg)

These are normalized spectral magnitude-squared totals for deterministic accounting. They are not direct physical energy measurements unless Parseval scaling is applied. The name `unique_suppressed_bins` means the final post-protection mask count over all unique bins. Under the current post-protection mask semantics, protected bins are forced to mask=0, so `unique_suppressed_bins` and `eligible_suppressed_bins` are equal whenever those protection rules are applied. The useful distinction is in the denominators: `unique_bins` includes protected bins, while `eligible_unique_bins` excludes them. The preferred workload proxy is therefore `eligible_suppressed_bins/eligible_unique_bins`. If a debug flow needs to know which protected bins would have been suppressed before protection, it shall use the optional bin-level `pre_mask` field rather than changing the frame-statistics counters.

### 7.2 Time-domain quality metrics

For ![0&#92;le n<N_y](../math/baseline-page-026-005.svg),

![Equation 7.5: e&#91;n&#93;=x_z&#91;n-D&#93;-y&#91;n&#93;.&#92;tag{7.5}](../math/baseline-page-026-006.svg)

Required integer metrics are

![Equation 7.6: &#92;mathrm{sum&#92;_abs&#92;_err}=&#92;sum_{n=0}^{N_y-1}&#124;e&#91;n&#93;&#124;.&#92;tag{7.6}](../math/baseline-page-026-007.svg)

![Equation 7.7: &#92;mathrm{sum&#92;_sq&#92;_err}=&#92;sum_{n=0}^{N_y-1}e&#91;n&#93;^2.&#92;tag{7.7}](../math/baseline-page-026-008.svg)

![Equation 7.8: &#92;mathrm{max&#92;_abs&#92;_err}=&#92;max_{0&#92;le n<N_y}&#124;e&#91;n&#93;&#124;.&#92;tag{7.8}](../math/baseline-page-026-009.svg)

![Equation 7.9: &#92;mathrm{error&#92;_sample&#92;_count}=N_y.&#92;tag{7.9}](../math/baseline-page-026-010.svg)

RMSE may be reported as a derived floating field, but the integer numerator and denominator are the signoff quantities.

### 7.3 Canonical memory-file encoding

All memh files contain exactly one value per line, lowercase hexadecimal digits only, no 0x prefix, no leading or trailing spaces, no blank lines, and exactly one LF line ending after each value in the canonical form. For an unsigned ![W](../math/baseline-page-026-011.svg)-bit memh file, each line shall contain exactly ![&#92;lceil W/4&#92;rceil](../math/baseline-page-026-012.svg) hexadecimal digits. The value shall satisfy ![0&#92;le&#92;mathrm{value}<2^W](../math/baseline-page-026-013.svg). Readers shall mask to W bits and shall not sign-extend unsigned files.
