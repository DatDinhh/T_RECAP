# Baseline PDF page 015

Historical Part I, core algorithm. Printed page 2. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=15).

[Previous](page-014.md) | [Index](../README.md) | [Next](page-016.md)

[Edit Markdown and LaTeX source](../source/baseline/page-015.md). Equations are rendered locally as SVG.

### 1.4 Core boundary

The core consumes a signed sample stream x[n] ∈ SN and produces a signed reconstructed stream y[n] ∈ SN . The following items are wrappers outside the mathematical core:

- ADC unsigned-to-signed conversion and optional DC blocking,

- audio-codec sample formatting,

- HPS software and control registers,

- transport packetization, including HPS DDR, Ethernet/UDP, UART/USB if used, and PC visualization,

- board switches, LEDs, seven-segment displays, and

- SystemVerilog module decomposition.

## 2 Parameters, Timing, and Finite-Stream Policy

### 2.1 Baseline parameters

Let L = ![2^{P}](../math/baseline-page-015-001.svg) be the FFT length and H = L/2 be the hop. Let G ≥ 0 be a scheduling cushion measured in sample periods. The exact causal delay is

![Equation 2.1: D=L+G.&#92;tag{2.1}](../math/baseline-page-015-002.svg)

**Table 2. Revision J baseline parameters.**

| Symbol | Meaning | Baseline |
| --- | --- | --- |
| ![N](../math/baseline-page-015-003.svg) | External signed input/output sample width | 12 |
| ![L](../math/baseline-page-015-004.svg) | FFT length | 256 |
| ![P](../math/baseline-page-015-005.svg) | Number of radix-2 stages, ![P=&#92;log_2L](../math/baseline-page-015-006.svg) | 8 |
| ![H](../math/baseline-page-015-007.svg) | Hop size | ![L/2=128](../math/baseline-page-015-008.svg) |
| ![F](../math/baseline-page-015-009.svg) | Fractional width for windows, twiddles, FFT data, and WOLA domain | 15 |
| ![G](../math/baseline-page-015-010.svg) | Scheduling cushion from frame trigger to first allowed WOLA contribution | ![H=128](../math/baseline-page-015-011.svg) |
| ![D](../math/baseline-page-015-012.svg) | Exact causal delay | ![L+G=384](../math/baseline-page-015-013.svg) samples |
| THR2 | Internal threshold register in the magnitude-squared domain | Programmable unsigned ![W_{&#92;mathrm{mag2}}](../math/baseline-page-015-014.svg)-bit integer |
| `PROTECT_DC` | Force DC bin to be kept | 1 |
| `PROTECT_NYQ` | Force Nyquist bin to be kept | 0 |


### 2.2 Frame timing

A frame trigger occurs whenever the accepted sample count reaches a positive multiple of H:

![Equation 2.2: &#92;tau_m=(m+1)H,&#92;qquad m&#92;in&#92;mathbb{N}_0.&#92;tag{2.2}](../math/baseline-page-015-015.svg)
