# Baseline PDF page 067

Historical Part II, DDR and UDP telemetry. Printed page 54. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=67).

[Previous](page-066.md) | [Index](../README.md) | [Next](page-068.md)

[Edit Markdown and LaTeX source](../source/baseline/page-067.md). Equations are rendered locally as SVG.

- status panel with active THR2, source mode, drop counters, overflow flags, packet rate, and sequence gaps. The dashboard-derived kept-energy ratio is `eligible_kept_mag2/eligible_total_mag2`. If `eligible_total_mag2` is zero, the dashboard shall display the ratio as N/A and shall omit that sample from rolling averages, trend lines, and threshold summaries. It shall not coerce the value to 0 or 1. The dashboard shall display both `dma_drop_count` and `packet_fifo_drop_count`. The first counter identifies DDR-writer/ring-space drops after packet acceptance by the DDR writer. The second counter identifies pre-writer packet-FIFO drops. These counters shall not be merged in the Revision G baseline.

### 24.2 Dashboard Update Rate

The PC GUI shall not redraw on every UDP datagram. The receiver shall parse UDP packets on a background thread or asynchronous receive loop and store data in ring buffers. The GUI thread shall consume the most recent buffered data at 20 to 30 Hz. Packet parsing shall not block UDP receive.

### 24.3 Packet Loss Handling

The PC dashboard shall track the seq field in each normal forwarded telemetry header. Missing sequence numbers shall be counted and displayed. Sequence-gap detection shall use modulo-![2^{32}](../math/baseline-page-067-001.svg) arithmetic:

![Equation 24.1: &#92;mathrm{expected&#92;_next}=(&#92;mathrm{previous&#92;_seq}+1)&#92;bmod2^{32}.&#92;tag{24.1}](../math/baseline-page-067-002.svg)

WRAP records are not forwarded and do not consume PC-visible sequence numbers. HPS-synthesized diagnostic STATUS packets with `status_diagnostic`=1 shall also be ignored for sequence-gap detection. Packet loss is acceptable for live visualization but shall be visible to the user.

## 25 Startup and Shutdown Sequence

### 25.1 Startup Sequence

The baseline startup sequence is:

1. Keep `CONTROL.telemetry_enable`=0 and `CONTROL.ring_writer_enable`=0.

2. Pulse `CONTROL.telemetry_soft_reset`.

3. Allocate or reserve the DDR ring region in HPS-visible memory.

4. Write `RING_BASE_LO`, `RING_BASE_HI`, and `RING_SIZE_BYTES`.

5. Pulse `RING_CONFIG_COMMIT` while telemetry is disabled.

6. Write `RING_RD_LO_SHADOW`=0 and `RING_RD_HI_SHADOW`=0.

7. Pulse `RING_RD_COMMIT`.
