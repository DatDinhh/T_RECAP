# Baseline PDF page 018

Historical Part I, core algorithm. Printed page 5. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=18).

[Previous](../../baseline/page-017.md) | [Index](../../README.md) | [Next](../../baseline/page-019.md)

- Window coefficients $Q_w[i]$ are nonnegative and stored in unsigned $W_{Q_w}=F+1$ bits. For F = 15, the range is 0 to 32768.

- Custom FFT and IFFT twiddle coefficients are stored in signed $W_{\mathrm{tw}}=F+2$ bits. For F = 15, both -32768 and +32768 are representable. A signed 16-bit Q1.15 ROM is not the Revision J baseline because it cannot represent +1.0 exactly.

### 3.4 Fixed-point products and complex multiplication

If integer a has $F_a$ fractional bits and integer b has $F_b$ fractional bits, then ab has $F_a+F_b$ fractional bits. To return to F fractional bits,

$$
\operatorname{mul}_F(a,b,F_a,F_b)=\operatorname{rnd\_shr}(ab,F_a+F_b-F).\tag{3.8}
$$

provided $F_a+F_b\ge F$. For complex multiplication with $b=b_r+jb_i$ and $w=w_r+jw_i$, each component with F fractional bits,

$$
\operatorname{cmul}_r(b,w)=\operatorname{rnd\_shr}(b_rw_r-b_iw_i,F).\tag{3.9}
$$

$$
\operatorname{cmul}_i(b,w)=\operatorname{rnd\_shr}(b_rw_i+b_iw_r,F).\tag{3.10}
$$

No truncation may occur before the full-precision product sums are formed. For a complex multiply whose data operands have signed width $W_d$ and twiddle operands have signed width $W_{\mathrm{tw}}$, product terms shall use at least $W_d+W_{\mathrm{tw}}$ signed bits. Product sums and differences shall use at least $W_d+W_{\mathrm{tw}}+1$ signed bits before `rnd_shr`(·, F ). For analysis windowing, $x[i]Q_w[i]$ shall be formed exactly with at least $W_x+W_{Q_w}$ signed product bits before storage. For synthesis windowing, $\operatorname{Re}\{v[i]\}Q_w[i]$ shall be formed with at least $W_{\mathrm{ifft}}+W_{Q_w}$ signed product bits before `rnd_shr`(·, F ). For magnitude-squared, each square shall be formed exactly and the sum shall have at least $2W_{\mathrm{can}}$ unsigned bits. Internal storage overflow is an error condition. Internal values shall not silently wrap or saturate unless a later revision explicitly defines that behavior.
