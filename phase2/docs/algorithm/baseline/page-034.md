# Baseline PDF page 034

Historical Part I, core algorithm. Printed page 21. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=34).

[Previous](page-033.md) | [Index](../README.md) | [Next](page-035.md)

[Edit Markdown and LaTeX source](../source/baseline/page-034.md). Equations are rendered locally as SVG.

sine and exact-bin sine. For amplitude A, normalized frequency f , and phase ϕ, where f is measured in cycles per sample and ϕ is measured in radians,

![Equation 8.4: x&#91;n&#93;=&#92;operatorname{sat}_N&#92;left(&#92;operatorname{qcoef}(A&#92;sin(2&#92;pi fn+&#92;phi),0)&#92;right).&#92;tag{8.4}](../math/baseline-page-034-001.svg)

Exact-bin sine uses f = k/L for frozen integer bin k. For exact-bin sine, 0 ≤ k ≤ L/2. For k = 0 or k = L/2, cosine is preferred for nonzero deterministic content because sine at phase zero can generate an all-zero sequence.

cosine. For amplitude A, normalized frequency f in cycles per sample, and phase ϕ in radians,

![Equation 8.5: x&#91;n&#93;=&#92;operatorname{sat}_N&#92;left(&#92;operatorname{qcoef}(A&#92;cos(2&#92;pi fn+&#92;phi),0)&#92;right).&#92;tag{8.5}](../math/baseline-page-034-002.svg)

`multitone_sine_sum`. For Q tones with amplitudes Aq , normalized frequencies fq in cycles per sample, and phases ϕq in radians,

![Equation 8.6: s&#91;n&#93;=&#92;sum_{q=0}^{Q-1}A_q&#92;sin(2&#92;pi f_qn+&#92;phi_q).&#92;tag{8.6}](../math/baseline-page-034-003.svg)

![Equation 8.7: x&#91;n&#93;=&#92;operatorname{sat}_N(&#92;operatorname{qcoef}(s&#91;n&#93;,0)).&#92;tag{8.7}](../math/baseline-page-034-004.svg)

The sum is formed in real arithmetic first. The operator qcoef(·, 0) is applied once to the final sum. Per-tone integer rounding before summation is not allowed unless a separate generator name freezes that behavior.

`uniform_noise_xorshift32`. Let r be a nonzero 32-bit unsigned seed. For every sample, update with unsigned 32-bit wraparound:

![Equation 8.8: r&#92;leftarrow r&#92;oplus((r&#92;ll13)&#92;bmod2^{32}).&#92;tag{8.8}](../math/baseline-page-034-005.svg)

![Equation 8.9: r&#92;leftarrow r&#92;oplus(r&#92;gg17).&#92;tag{8.9}](../math/baseline-page-034-006.svg)

![Equation 8.10: r&#92;leftarrow r&#92;oplus((r&#92;ll5)&#92;bmod2^{32}).&#92;tag{8.10}](../math/baseline-page-034-007.svg)

For frozen noise bit width B,

![Equation 8.11: u&#91;n&#93;=r&#92;bmod2^B,&#92;qquad x&#91;n&#93;=&#92;operatorname{sat}_N(u&#91;n&#93;-2^{B-1}).&#92;tag{8.11}](../math/baseline-page-034-008.svg)

The frozen noise bit width shall satisfy 1 ≤ B ≤ 32. The value B = 0 is illegal, and B > 32 is illegal because the generator state is exactly 32 bits. If B > N , the vector intentionally exercises clipping through satN and shall declare that intent in `test_vectors.json`. A stochastic vector is not frozen unless it declares generator name, seed, B, Ns , threshold, protection flags, and tail policy.

### 8.3 Golden-model quality bounds

Bit-for-bit agreement between RTL and the golden model proves implementation equivalence. It does not prove that the golden model has the intended reconstruction quality. Therefore, the global `quality_bounds.json` manifest shall freeze no-suppression quality limits per vector after the first complete golden-model release. It shall include at least `max_abs_err`, `sum_sq_err`, and `error_sample_count`. Do not invent these numbers in the specification. Run the golden model first, then freeze them.
