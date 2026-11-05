# Baseline PDF page 033

Historical Part I, core algorithm. Printed page 20. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=33).

[Previous](page-032.md) | [Index](../README.md) | [Next](page-034.md)

**Table 6. Required mathematical signoff vector classes.**

| Test class | Purpose | Required |
| --- | --- | --- |
| Zero input | Confirms zero-extension, windowing, FFT/IFFT, WOLA, and output rounding do not create nonzero samples. | Yes |
| No suppression, THR2 = 0 | Confirms all eligible masks are zero and establishes near-lossless baseline error. | Yes |
| Impulse and step | Exercises startup, flush, delay D, and WOLA alignment. | Yes |
| Exact-bin tone sweep | Verifies dominant-bin placement and expected window-shaped spectral spread. | Yes |
| Off-bin tone sweep | Exercises leakage behavior under the periodic square-root Hann window. | Yes |
| Near-threshold multitone | Verifies full-precision unsigned threshold decisions and Hermitian-pair consistency. | Yes |
| Noise-only stream | Characterizes suppression ratio, kept-energy ratio, and error under low-value content. | Yes |
| High-amplitude headroom | Confirms no internal wraparound on the frozen width schedule. | Yes |
| Short finite stream | Forces startup, flush, and full-tail scoring. | Yes |
| Rectangular-window diagnostic | Debug-only exact one-bin sinusoid test. Not part of the normal core. | Optional |


### 8.2 Frozen generator algorithms

Generator names in `test_vectors.json` refer to the exact integer generators below. All generated samples are finally clipped by satN . Frequency parameters in JSON use `f_num` and `f_den`. The mathematical symbol f below denotes the exact rational value `f_num/f_den`. Phase parameters use `phase_rad` decimal strings. The equations define construction before freezing. After freezing, `x_in.memh` and `x_in_sha256` are the signoff source of truth. For sine, cosine, and multitone generators, the frozen generator implementation shall be identified by `generator_version` and `generator_source_sha256`. A regenerated vector is accepted only when its canonical `x_in_sha256` matches the frozen manifest. Differences caused by host math libraries, π constants, floating-point precision, or decimal parsing are not acceptable implementation variations after a vector has been frozen.

constant. For integer value c,

$$
x[n]=\operatorname{sat}_N(c).\tag{8.1}
$$

impulse. For index n0 and amplitude A,

$$
x[n]=\begin{cases}\operatorname{sat}_N(A),&n=n_0\\0,&n\ne n_0.\end{cases}\tag{8.2}
$$

step. For index n0 and amplitude A,

$$
x[n]=\begin{cases}0,&n<n_0\\\operatorname{sat}_N(A),&n\ge n_0.\end{cases}\tag{8.3}
$$
