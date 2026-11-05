# Baseline PDF page 018

Historical Part I, core algorithm. Printed page 5. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=18).

[Previous](page-017.md) | [Index](../README.md) | [Next](page-019.md)

[Edit Markdown and LaTeX source](../source/baseline/page-018.md). Equations are rendered locally as SVG.

- Window coefficients ![Q_w&#91;i&#93;](../math/baseline-page-018-001.svg) are nonnegative and stored in unsigned ![W_{Q_w}=F+1](../math/baseline-page-018-002.svg) bits. For F = 15, the range is 0 to 32768.

- Custom FFT and IFFT twiddle coefficients are stored in signed ![W_{&#92;mathrm{tw}}=F+2](../math/baseline-page-018-003.svg) bits. For F = 15, both -32768 and +32768 are representable. A signed 16-bit Q1.15 ROM is not the Revision J baseline because it cannot represent +1.0 exactly.

### 3.4 Fixed-point products and complex multiplication

If integer a has ![F_a](../math/baseline-page-018-004.svg) fractional bits and integer b has ![F_b](../math/baseline-page-018-005.svg) fractional bits, then ab has ![F_a+F_b](../math/baseline-page-018-006.svg) fractional bits. To return to F fractional bits,

![Equation 3.8: &#92;operatorname{mul}_F(a,b,F_a,F_b)=&#92;operatorname{rnd&#92;_shr}(ab,F_a+F_b-F).&#92;tag{3.8}](../math/baseline-page-018-007.svg)

provided ![F_a+F_b&#92;ge F](../math/baseline-page-018-008.svg). For complex multiplication with ![b=b_r+jb_i](../math/baseline-page-018-009.svg) and ![w=w_r+jw_i](../math/baseline-page-018-010.svg), each component with F fractional bits,

![Equation 3.9: &#92;operatorname{cmul}_r(b,w)=&#92;operatorname{rnd&#92;_shr}(b_rw_r-b_iw_i,F).&#92;tag{3.9}](../math/baseline-page-018-011.svg)

![Equation 3.10: &#92;operatorname{cmul}_i(b,w)=&#92;operatorname{rnd&#92;_shr}(b_rw_i+b_iw_r,F).&#92;tag{3.10}](../math/baseline-page-018-012.svg)

No truncation may occur before the full-precision product sums are formed. For a complex multiply whose data operands have signed width ![W_d](../math/baseline-page-018-013.svg) and twiddle operands have signed width ![W_{&#92;mathrm{tw}}](../math/baseline-page-018-014.svg), product terms shall use at least ![W_d+W_{&#92;mathrm{tw}}](../math/baseline-page-018-015.svg) signed bits. Product sums and differences shall use at least ![W_d+W_{&#92;mathrm{tw}}+1](../math/baseline-page-018-016.svg) signed bits before `rnd_shr`(·, F ). For analysis windowing, ![x&#91;i&#93;Q_w&#91;i&#93;](../math/baseline-page-018-017.svg) shall be formed exactly with at least ![W_x+W_{Q_w}](../math/baseline-page-018-018.svg) signed product bits before storage. For synthesis windowing, ![&#92;operatorname{Re}&#92;{v&#91;i&#93;&#92;}Q_w&#91;i&#93;](../math/baseline-page-018-019.svg) shall be formed with at least ![W_{&#92;mathrm{ifft}}+W_{Q_w}](../math/baseline-page-018-020.svg) signed product bits before `rnd_shr`(·, F ). For magnitude-squared, each square shall be formed exactly and the sum shall have at least ![2W_{&#92;mathrm{can}}](../math/baseline-page-018-021.svg) unsigned bits. Internal storage overflow is an error condition. Internal values shall not silently wrap or saturate unless a later revision explicitly defines that behavior.
