# Baseline PDF page 049

Historical Part II, DDR and UDP telemetry. Printed page 36. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=49).

[Previous](page-048.md) | [Index](../README.md) | [Next](page-050.md)

[Edit Markdown and LaTeX source](../source/baseline/page-049.md). Equations are rendered locally as SVG.

1. HPS-written control values crossing into FPGA logic shall use synchronizers, handshakes, or commit mechanisms.

2. Multi-bit counters exposed to HPS shall be latched into snapshot registers before HPS reads low/high halves.

3. Rd crossing from the HPS CSR domain to the DDR writer domain shall use the `RING_RD_COMMIT` handshake, not independent bit synchronizers.

4. W crossing from the DDR writer domain to the HPS-visible CSR domain shall use the `RING_WR_SNAPSHOT` mechanism or an equivalent handshake scheme.

5. Telemetry taps shall never backpressure the STFT/WOLA core. If a tap event cannot be accepted, the tap event shall be dropped and counted.

## 17 DDR Ring Buffer Contract

### 17.1 Ring Size, Base Address, and Alignment

The DDR telemetry ring is a contiguous HPS-visible memory region. Let:

![Equation 17.1: B=&#92;text{FPGA-visible ring base address}.&#92;tag{17.1}](../math/baseline-page-049-001.svg)

![Equation 17.2: R=&#92;text{ring size in bytes}.&#92;tag{17.2}](../math/baseline-page-049-002.svg)

The ring size shall satisfy:

![Equation 17.3: R=2^q,&#92;quad q&#92;ge20,&#92;quad R&#92;equiv0&#92;pmod{64}.&#92;tag{17.3}](../math/baseline-page-049-003.svg)

The base address shall satisfy:

![Equation 17.4: B&#92;equiv0&#92;pmod{64}.&#92;tag{17.4}](../math/baseline-page-049-004.svg)

If the FPGA bus address decoder requires naturally aligned power-of-two regions, then the stronger condition B ≡ 0 (mod R) shall also hold. A recommended first implementation is R = 32 MiB.

### 17.2 Absolute Pointers

The ring uses 64-bit monotonic byte pointers rather than modulo-only pointers. Let W be the producer pointer and Rd be the consumer pointer. The physical byte offset is:

![Equation 17.5: &#92;operatorname{off}(p)=p&#92;mathbin{&#92;&}(R-1).&#92;tag{17.5}](../math/baseline-page-049-005.svg)

where R is a power of two. The number of used bytes is:

![Equation 17.6: U=W-R_d.&#92;tag{17.6}](../math/baseline-page-049-006.svg)

The ring state is valid only when:

![Equation 17.7: 0&#92;le U&#92;le R.&#92;tag{17.7}](../math/baseline-page-049-007.svg)
