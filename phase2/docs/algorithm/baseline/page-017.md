# Baseline PDF page 017

Historical Part I, core algorithm. Printed page 4. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=17).

[Previous](page-016.md) | [Index](../README.md) | [Next](page-018.md)

[Edit Markdown and LaTeX source](../source/baseline/page-017.md). Equations are rendered locally as SVG.

## 3 Bit-Accurate Fixed-Point Contract

### 3.1 Sample range and saturation

An ![N](../math/baseline-page-017-001.svg)-bit signed two’s-complement sample belongs to

![Equation 3.1: &#92;mathcal{S}_N=&#91;-2^{N-1},2^{N-1}-1&#93;&#92;cap&#92;mathbb{Z}.&#92;tag{3.1}](../math/baseline-page-017-002.svg)

The output saturation operator is

![Equation 3.2: &#92;operatorname{sat}_N(z)=&#92;begin{cases}-2^{N-1},&z<-2^{N-1}&#92;&#92;z,&-2^{N-1}&#92;le z&#92;le2^{N-1}-1&#92;&#92;2^{N-1}-1,&z>2^{N-1}-1.&#92;end{cases}&#92;tag{3.2}](../math/baseline-page-017-003.svg)

Internal wraparound is not allowed in the visible core contract. Revision J guarantees bit-accurate behavior on the frozen signoff vector set. For arbitrary legal ![N](../math/baseline-page-017-004.svg)-bit input streams outside that set, an implementation shall either provision widths according to a separate worst-case proof or expose overflow flags that are checked by the verification environment. Such arbitrary streams are not part of Revision J signoff unless that additional proof or flag policy is supplied.

### 3.2 Arithmetic shift and rounded right shift

Let asr(z, k) denote sign-preserving arithmetic right shift by k bits. For k ≥ 0, it is equivalent to

![Equation 3.3: &#92;operatorname{asr}(z,k)=&#92;left&#92;lfloor&#92;frac{z}{2^k}&#92;right&#92;rfloor.&#92;tag{3.3}](../math/baseline-page-017-005.svg)

For example, asr(-3, 1) = -2. All quantizing right shifts use round-to-nearest with ties away from zero. For s ≥ 1,

![Equation 3.4: &#92;operatorname{rnd&#92;_shr}(v,s)=&#92;operatorname{sgn}(v)&#92;left&#92;lfloor&#92;frac{&#124;v&#124;+2^{s-1}}{2^s}&#92;right&#92;rfloor.&#92;tag{3.4}](../math/baseline-page-017-006.svg)

The sign function is frozen as

![Equation 3.5: &#92;operatorname{sgn}(z)=&#92;begin{cases}-1,&z<0&#92;&#92;0,&z=0&#92;&#92;+1,&z>0.&#92;end{cases}&#92;tag{3.5}](../math/baseline-page-017-007.svg)

The zero-shift case is defined as

![Equation 3.6: &#92;operatorname{rnd&#92;_shr}(v,0)=v.&#92;tag{3.6}](../math/baseline-page-017-008.svg)

For complex values, `rnd_shr` applies component-wise. Define rnd2(q) = `rnd_shr`(q, 1).

### 3.3 Coefficient quantization and storage widths

All shared coefficient tables use

![Equation 3.7: &#92;operatorname{qcoef}(c,F)=&#92;operatorname{sgn}(c)&#92;left&#92;lfloor &#124;c&#124;2^F+&#92;frac12&#92;right&#92;rfloor.&#92;tag{3.7}](../math/baseline-page-017-009.svg)

This is round-to-nearest with ties away from zero. Independent use of a language-default round() is not allowed unless it is proven bit-for-bit equivalent. The storage contract is mandatory:
