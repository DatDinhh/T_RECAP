# Baseline PDF page 021

Historical Part I, core algorithm. Printed page 8. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=21).

[Previous](../../baseline/page-020.md) | [Index](../../README.md) | [Next](../../baseline/page-022.md)

### 4.5 Protection rules and masked spectrum

Define

$$
\epsilon[k]=\begin{cases}0,&k=0\text{ and }\mathrm{PROTECT\_DC}=1\\0,&k=L/2\text{ and }\mathrm{PROTECT\_NYQ}=1\\1,&\text{otherwise.}\end{cases}\tag{4.15}
$$

After threshold comparison, if `PROTECT_DC`= 1, force $\operatorname{mask}_m[0]=0$. If `PROTECT_NYQ`= 1, force $\operatorname{mask}_m[L/2]=0$. The preliminary value `pre_mask` is retained only for debug reporting and never controls synthesis. The masked spectrum is denoted $\mathrm{Xb}$. For $1\le k\le L/2-1$,

$$
\mathrm{Xb}_m[k]=\begin{cases}0,&\operatorname{mask}_m[k]=1\\X_m^{\mathrm{can}}[k],&\operatorname{mask}_m[k]=0.\end{cases}\tag{4.16}
$$

$$
\mathrm{Xb}_m[L-k]=\begin{cases}0,&\operatorname{mask}_m[k]=1\\X_m^{\mathrm{can}}[L-k],&\operatorname{mask}_m[k]=0.\end{cases}\tag{4.17}
$$

For self-conjugate bins,

$$
\mathrm{Xb}_m[0]=(1-\operatorname{mask}_m[0])X_m^{\mathrm{can}}[0].\tag{4.18}
$$

$$
\mathrm{Xb}_m[L/2]=(1-\operatorname{mask}_m[L/2])X_m^{\mathrm{can}}[L/2].\tag{4.19}
$$

The result is conjugate symmetric by construction.

### 4.6 Unscaled IFFT, synthesis window, and WOLA

The intended inverse is unscaled:

$$
v_m[i]=\sum_{k=0}^{L-1}\mathrm{Xb}_m[k]e^{j2\pi ki/L},\qquad0\le i<L.\tag{4.20}
$$

For the custom baseline, Algorithm 5 is normative. The synthesized frame contribution is

$$
z_m[i]=\operatorname{rnd\_shr}(\operatorname{Re}\{v_m[i]\}Q_w[i],F).\tag{4.21}
$$

Each frame adds into the output accumulator:

$$
A[\tau_m+G+i]\leftarrow A[\tau_m+G+i]+z_m[i].\tag{4.22}
$$

The emitted sample and delayed error are

$$
y[n]=\operatorname{sat}_N(\operatorname{rnd\_shr}(A[n],F)).\tag{4.23}
$$

$$
e[n]=x_z[n-D]-y[n].\tag{4.24}
$$
