# Baseline PDF page 017

Historical Part I, core algorithm. Printed page 4. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=17).

[Previous](../../baseline/page-016.md) | [Index](../../README.md) | [Next](../../baseline/page-018.md)

## 3 Bit-Accurate Fixed-Point Contract

### 3.1 Sample range and saturation

An $N$-bit signed two’s-complement sample belongs to

$$
\mathcal{S}_N=[-2^{N-1},2^{N-1}-1]\cap\mathbb{Z}.\tag{3.1}
$$

The output saturation operator is

$$
\operatorname{sat}_N(z)=\begin{cases}-2^{N-1},&z<-2^{N-1}\\z,&-2^{N-1}\le z\le2^{N-1}-1\\2^{N-1}-1,&z>2^{N-1}-1.\end{cases}\tag{3.2}
$$

Internal wraparound is not allowed in the visible core contract. Revision J guarantees bit-accurate behavior on the frozen signoff vector set. For arbitrary legal $N$-bit input streams outside that set, an implementation shall either provision widths according to a separate worst-case proof or expose overflow flags that are checked by the verification environment. Such arbitrary streams are not part of Revision J signoff unless that additional proof or flag policy is supplied.

### 3.2 Arithmetic shift and rounded right shift

Let asr(z, k) denote sign-preserving arithmetic right shift by k bits. For k ≥ 0, it is equivalent to

$$
\operatorname{asr}(z,k)=\left\lfloor\frac{z}{2^k}\right\rfloor.\tag{3.3}
$$

For example, asr(-3, 1) = -2. All quantizing right shifts use round-to-nearest with ties away from zero. For s ≥ 1,

$$
\operatorname{rnd\_shr}(v,s)=\operatorname{sgn}(v)\left\lfloor\frac{|v|+2^{s-1}}{2^s}\right\rfloor.\tag{3.4}
$$

The sign function is frozen as

$$
\operatorname{sgn}(z)=\begin{cases}-1,&z<0\\0,&z=0\\+1,&z>0.\end{cases}\tag{3.5}
$$

The zero-shift case is defined as

$$
\operatorname{rnd\_shr}(v,0)=v.\tag{3.6}
$$

For complex values, `rnd_shr` applies component-wise. Define rnd2(q) = `rnd_shr`(q, 1).

### 3.3 Coefficient quantization and storage widths

All shared coefficient tables use

$$
\operatorname{qcoef}(c,F)=\operatorname{sgn}(c)\left\lfloor |c|2^F+\frac12\right\rfloor.\tag{3.7}
$$

This is round-to-nearest with ties away from zero. Independent use of a language-default round() is not allowed unless it is proven bit-for-bit equivalent. The storage contract is mandatory:
