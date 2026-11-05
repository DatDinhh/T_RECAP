# Baseline PDF page 020

Historical Part I, core algorithm. Printed page 7. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=20).

[Previous](../../baseline/page-019.md) | [Index](../../README.md) | [Next](../../baseline/page-021.md)

The quantized table is $Q_w[i]=\operatorname{qcoef}(w[i],F)$.

### 4.2 Analysis windowing and normalized FFT

For frame m,

$$
u_m[i]=x_z[\tau_m-L+i]Q_w[i],\qquad0\le i<L.\tag{4.4}
$$

The intended normalized forward transform is

$$
X_m[k]=\frac1L\sum_{i=0}^{L-1}u_m[i]e^{-j2\pi ki/L},\qquad0\le k<L.\tag{4.5}
$$

For the custom baseline, Algorithm 4 is normative.

### 4.3 Hermitian canonicalization

For self-conjugate bins,

$$
X_m^{\mathrm{can}}[0]=\operatorname{Re}\{X_m[0]\}+j0.\tag{4.6}
$$

$$
X_m^{\mathrm{can}}[L/2]=\operatorname{Re}\{X_m[L/2]\}+j0.\tag{4.7}
$$

For 1 ≤ k ≤ L/2 - 1,

$$
R_m[k]=\operatorname{rnd2}(\operatorname{Re}\{X_m[k]\}+\operatorname{Re}\{X_m[L-k]\}).\tag{4.8}
$$

$$
I_m[k]=\operatorname{rnd2}(\operatorname{Im}\{X_m[k]\}-\operatorname{Im}\{X_m[L-k]\}).\tag{4.9}
$$

$$
X_m^{\mathrm{can}}[k]=R_m[k]+jI_m[k].\tag{4.10}
$$

$$
X_m^{\mathrm{can}}[L-k]=R_m[k]-jI_m[k].\tag{4.11}
$$

All threshold decisions use $X^{\mathrm{can}}$, not the raw FFT output.

### 4.4 Magnitude-squared mask

For unique bins 0 ≤ k ≤ L/2,

$$
\operatorname{mag2}_m[k]=\operatorname{Re}\{X_m^{\mathrm{can}}[k]\}^2+\operatorname{Im}\{X_m^{\mathrm{can}}[k]\}^2.\tag{4.12}
$$

The preliminary mask bit before protection is

$$
\operatorname{pre\_mask}_m[k]=\begin{cases}1,&\operatorname{mag2}_m[k]<\mathrm{THR2}\\0,&\operatorname{mag2}_m[k]\ge\mathrm{THR2}.\end{cases}\tag{4.13}
$$

The final mask is initialized as $\operatorname{mask}_m[k]=\operatorname{pre\_mask}_m[k]$ and may then be modified only by the protection rules in Section 4.5. The comparison is unsigned, full precision, and performed in the magnitude-squared domain. The threshold register width is $W_{\mathrm{mag2}}$:

$$
0\le\mathrm{THR2}<2^{W_{\mathrm{mag2}}}.\tag{4.14}
$$

Out-of-range values are illegal for core signoff.
