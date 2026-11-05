# Baseline PDF page 035

Historical Part I, core algorithm. Printed page 22. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=35).

[Previous](page-034.md) | [Index](../README.md) | [Next](page-036.md)

[Edit Markdown and LaTeX source](../source/baseline/page-035.md). Equations are rendered locally as SVG.

### 8.4 Acceptance criteria

A Phase 2 core implementation passes Revision J signoff only if all of the following hold:

AC1. The golden model generates all required artifacts for every vector in `test_vectors.json` using the generators in Section 8.2.

AC2. Coefficient artifacts and hashes match under the canonical memh and SHA-256 rules.

AC3. Stream artifacts `x_in.memh` and `y_out.memh` match the recorded canonical `x_in_sha256` and `y_out_sha256` hashes.

AC4. All required artifacts have the exact row counts specified in Section 7.7 and in config.json `artifact_rows`.

AC5. THR2 is an unsigned ![W_{&#92;mathrm{mag2}}](../math/baseline-page-035-001.svg)-bit integer and satisfies ![0&#92;le&#92;mathrm{THR2}<2^{W_{&#92;mathrm{mag2}}}](../math/baseline-page-035-002.svg).

AC6. For THR2= 0, every eligible mask decision is zero.

AC7. The output length follows the declared `tail_policy`. Revision J signoff uses `full_tail` with zero flush ticks until all ![N_y](../math/baseline-page-035-003.svg) outputs are emitted.

AC8. No-suppression golden-model quality fields satisfy `quality_bounds.json`.

AC9. RTL simulation matches `y_out.memh` sample-for-sample.

AC10. RTL simulation matches every row of `frame_stats.csv` exactly.

AC11. RTL simulation matches every mandatory field in metrics.json exactly.

AC12. For vectors that require `bin_stats.csv`, canonical real/imag, mag2, eligibility, `pre_mask`, and final mask fields match exactly.

AC13. BRAM replay on the FPGA board matches the mandatory artifacts before live input is used for demonstration.

AC14. Overflow or wrap flags, if present, remain deasserted on the frozen signoff vector set.

## 9 Live Source Abstraction and Threshold Mapping

The core begins after input adaptation. Every live source must map to ![x&#91;n&#93;&#92;in&#92;mathcal{S}_N](../math/baseline-page-035-004.svg). For a raw unsigned B-bit ADC source,

![Equation 9.1: u&#91;n&#93;=a_{&#92;mathrm{raw}}&#91;n&#93;-2^{B-1}.&#92;tag{9.1}](../math/baseline-page-035-005.svg)

![Equation 9.2: d_c&#91;-1&#93;=0.&#92;tag{9.2}](../math/baseline-page-035-006.svg)

![Equation 9.3: d_c&#91;n&#93;=d_c&#91;n-1&#93;+&#92;operatorname{asr}(u&#91;n&#93;-d_c&#91;n-1&#93;,S_{&#92;mathrm{DC}}).&#92;tag{9.3}](../math/baseline-page-035-007.svg)

![Equation 9.4: x&#91;n&#93;=&#92;operatorname{sat}_N(u&#91;n&#93;-d_c&#91;n&#93;).&#92;tag{9.4}](../math/baseline-page-035-008.svg)

For an audio-codec source with ![B_{&#92;mathrm{audio}}&#92;ge N](../math/baseline-page-035-009.svg),

![Equation 9.5: x&#91;n&#93;=&#92;operatorname{sat}_N(&#92;operatorname{rnd&#92;_shr}(a_{&#92;mathrm{audio}}&#91;n&#93;,B_{&#92;mathrm{audio}}-N)).&#92;tag{9.5}](../math/baseline-page-035-010.svg)

If ![B_{&#92;mathrm{audio}}<N](../math/baseline-page-035-011.svg), a separate left-shift or sign-extension rule shall be frozen before use.
