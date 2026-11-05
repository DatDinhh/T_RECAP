# Baseline PDF page 024

Historical Part I, core algorithm. Printed page 11. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=24).

[Previous](page-023.md) | [Index](../README.md) | [Next](page-025.md)

[Edit Markdown and LaTeX source](../source/baseline/page-024.md). Equations are rendered locally as SVG.

INV3. If THR2= 0, then every eligible mask decision is zero.

INV4. For ![1&#92;le k&#92;le L/2-1](../math/baseline-page-024-001.svg), ![&#92;mathrm{Xb}&#91;L-k&#93;=&#92;mathrm{Xb}&#91;k&#93;^*](../math/baseline-page-024-002.svg) by construction.

INV5. Bins 0 and L/2 are real-valued after canonicalization.

INV6. All precision-reducing shifts use `rnd_shr`(·) or rnd2(·).

INV7. The OLA accumulator shall not wrap internally on signoff vectors.

INV8. The signoff frame count equals ![&#92;lfloor(N_s+L-2)/H&#92;rfloor](../math/baseline-page-024-003.svg) under the Revision J active-window finite-stream policy.

## 6 Exact Custom FFT/IFFT Integer Algorithms

This section freezes the custom radix-2 baseline. If a vendor FFT IP is used, Appendix A replaces this section for bit-accurate purposes.

### 6.1 Bit reversal and twiddle tables

Let ![&#92;operatorname{bitrev}_P(k)](../math/baseline-page-024-004.svg) denote ![P](../math/baseline-page-024-005.svg)-bit bit reversal. Forward twiddles are

![Equation 6.1: W_r&#91;e&#93;=&#92;operatorname{qcoef}&#92;left(&#92;cos&#92;frac{2&#92;pi e}{L},F&#92;right).&#92;tag{6.1}](../math/baseline-page-024-006.svg)

![Equation 6.2: W_i&#91;e&#93;=&#92;operatorname{qcoef}&#92;left(-&#92;sin&#92;frac{2&#92;pi e}{L},F&#92;right).&#92;tag{6.2}](../math/baseline-page-024-007.svg)

Inverse twiddles are

![Equation 6.3: &#92;widetilde W_r&#91;e&#93;=&#92;operatorname{qcoef}&#92;left(&#92;cos&#92;frac{2&#92;pi e}{L},F&#92;right).&#92;tag{6.3}](../math/baseline-page-024-008.svg)

![Equation 6.4: &#92;widetilde W_i&#91;e&#93;=&#92;operatorname{qcoef}&#92;left(+&#92;sin&#92;frac{2&#92;pi e}{L},F&#92;right).&#92;tag{6.4}](../math/baseline-page-024-009.svg)

Define the complex twiddle table aliases

![Equation 6.5: W_{&#92;mathrm{fwd}}&#91;e&#93;=W_r&#91;e&#93;+jW_i&#91;e&#93;.&#92;tag{6.5}](../math/baseline-page-024-010.svg)

![Equation 6.6: W_{&#92;mathrm{inv}}&#91;e&#93;=&#92;widetilde W_r&#91;e&#93;+j&#92;widetilde W_i&#91;e&#93;.&#92;tag{6.6}](../math/baseline-page-024-011.svg)

Algorithms 4 and 5 shall use these aliases. The inverse twiddle table is a frozen artifact and shall not be regenerated implicitly inside RTL.

### Algorithm 4 Exact custom FFTnorm integer algorithm

```text
Require: real input vector u[0:L - 1] with F fractional bits; L = 2^P ; frozen forward twiddle table Wfwd[e]
Ensure: normalized complex spectrum X[0:L - 1] in natural order
1: for k = 0 to L - 1 do
2:    A[k] ← u[bitrevP (k)] + j0
3: end for
4: for s = 1 to P do
```
