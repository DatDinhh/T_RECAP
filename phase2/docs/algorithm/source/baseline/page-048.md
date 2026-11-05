# Baseline PDF page 048

Historical Part II, DDR and UDP telemetry. Printed page 35. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=48).

[Previous](../../baseline/page-047.md) | [Index](../../README.md) | [Next](../../baseline/page-049.md)

`OVERFLOW_FLAGS.packet_fifo_overflow` is the sticky indicator that at least one packet-FIFO drop occurred. `PACKET_FIFO_DROP_COUNT` is the corresponding quantitative counter. Drops counted by `PACKET_FIFO_DROP_COUNT` are not required to increment `DMA_DROP_COUNT`, because the DDR writer has not yet accepted those packets.

### 16.11 Threshold Commit Rule

The HPS shall update the 56-bit THR2 value using `THR2_LO`, `THR2_HI`, and `THR2_COMMIT`. The upper unused bits of `THR2_HI` shall be zero. Valid values satisfy

$$
0\le\mathrm{THR2}<2^{56}.\tag{16.1}
$$

The FPGA shall copy the shadow value into the active threshold only at a frame boundary. This avoids tearing a 56-bit threshold while a frame is being analyzed.

$$
\mathrm{THR2}_{\mathrm{active}}[m+1]=\begin{cases}\mathrm{THR2}_{\mathrm{shadow}},&\text{if commit pending at frame boundary}\\\mathrm{THR2}_{\mathrm{active}}[m],&\text{otherwise.}\end{cases}\tag{16.2}
$$

### 16.12 Source-Mode Change Rule

A source-mode change can disturb delay alignment, input-ring contents, OLA contents, metrics continuity, and source-adapter state. Therefore, a source-mode update shall be atomic and shall not mix samples from different sources inside one active stream interval. The Revision G baseline source-mode commit sequence is:

1. disable the telemetry writer or otherwise mark the upcoming telemetry interval as discontinuous.

2. clear metrics or mark a metrics discontinuity before the new source contributes samples.

3. stop accepting old-source samples.

4. clear the affected source adapter state.

5. clear input-ring, OLA-ring, delay-alignment, and frame-scheduler state when those states depend on the previous source.

6. latch `SOURCE_MODE_SHADOW`.

7. activate the new source only at a sample boundary.

8. re-enable telemetry only after the active source and alignment state are coherent. An implementation-defined safe-frame-boundary commit is allowed only if it performs the same state-reset or discontinuity-marking obligations above. Commands that request an illegal source mode or unsafe source-mode transition shall be rejected and counted.

### 16.13 Clock-Domain Crossing Requirements

The implementation shall not rely on unsynchronized multi-bit sampling across clock domains. The following rules are normative:
