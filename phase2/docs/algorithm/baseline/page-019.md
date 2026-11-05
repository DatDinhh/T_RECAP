# Baseline PDF page 019

Historical Part I, core algorithm. Printed page 6. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=19).

[Previous](page-018.md) | [Index](../README.md) | [Next](page-020.md)

### 3.5 Internal width schedule

**Table 3. Revision J minimum internal widths for the custom radix-2 baseline.**

| Quantity | Symbol | Width rule | Baseline |
| --- | --- | --- | --- |
| External sample | $W_x$ | signed $N$ | 12 |
| Window coefficient | $W_{Q_w}$ | unsigned $F+1$ | 16 |
| Twiddle coefficient | $W_{\mathrm{tw}}$ | signed $F+2$ | 17 |
| Analysis-windowed input | $W_u$ | signed $N+F$ | 27 |
| Forward FFT stored real/imag | $W_{\mathrm{fft}}$ | signed $W_u+1$ | 28 |
| Forward pre-round add/sub | $W_{\mathrm{fft,pre}}$ | signed $W_{\mathrm{fft}}+1$ | 29 |
| Canonical pre-round add/sub | $W_{\mathrm{can,pre}}$ | signed $W_{\mathrm{fft}}+1$ | 29 |
| Canonical real/imag | $W_{\mathrm{can}}$ | signed $W_{\mathrm{fft}}$ | 28 |
| Magnitude-squared and THR2 | $W_{\mathrm{mag2}}$ | unsigned $2W_{\mathrm{can}}$ | 56 |
| Unscaled IFFT stored real/imag | $W_{\mathrm{ifft}}$ | signed $W_{\mathrm{can}}+P$ | 36 |
| Synthesis-windowed sample | $W_z$ | signed $W_{\mathrm{ifft}}$ | 36 |
| OLA accumulator entry | $W_{\mathrm{ola}}$ | signed $W_z+1$ | 37 |
| Aggregate spectral sums | $W_{E\mathrm{sum}}$ | At least $W_{\mathrm{mag2}}+\lceil\log_2(2N_{\mathrm{frames}}L)\rceil$ or arbitrary precision | run dependent |
| Time-error sums | $W_{\mathrm{err}}$ | Large enough for all emitted samples or arbitrary precision | run dependent |


The golden model should use arbitrary-precision integers for metric accumulators. RTL shall either provision enough accumulator width for the selected run length or expose and check overflow flags. Although the analysis product xm [i]Qw [i] may be formed internally in at least Wx + WQw bits, the frozen baseline coefficient range 0 ≤ Qw [i] ≤ $2^{F}$ guarantees that the exact product fits in signed Wu = N + F bits. Storage into Wu is therefore a range-checked exact assignment. It is not truncation. If a future coefficient table permits values above $2^{F}$ , the Wu rule must be re-derived.

## 4 STFT/WOLA Core Mathematics

### 4.1 Periodic square-root Hann window

Define the periodic Hann sequence

$$
h_p[i]=\frac12-\frac12\cos\left(\frac{2\pi i}{L}\right),\qquad0\le i<L.\tag{4.1}
$$

The analysis and synthesis windows are identical:

$$
w_a[i]=w_s[i]=w[i]=\sqrt{h_p[i]}.\tag{4.2}
$$

For H = L/2, ideal complementarity is

$$
w_a[i]w_s[i]+w_a[i+H]w_s[i+H]=1,\qquad0\le i<H.\tag{4.3}
$$
