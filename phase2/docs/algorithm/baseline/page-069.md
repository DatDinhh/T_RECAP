# Baseline PDF page 069

Historical Part II, DDR and UDP telemetry. Printed page 56. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=69).

[Previous](page-068.md) | [Index](../README.md) | [Next](page-070.md)

[Edit Markdown and LaTeX source](../source/baseline/page-069.md). Equations are rendered locally as SVG.

**Table 26. Failure modes and required observability, continued.**

| Failure mode | Required behavior | Required counter/status |
| --- | --- | --- |
| Illegal command | Reject command and do not modify active state. | HPS reject counter plus `CSR_COMMAND_REJECT_COUNT`. |
| CDC violation detected | Raise sticky flag and optionally disable telemetry. | CDC error flag. |
| Oversized record | HPS drops record. FPGA scheduler should avoid generating it. | Oversized-record count. |


## 27 Acceptance Criteria

A Level-3 implementation passes this transport supplement only if all of the following are true:

AC1. FPGA core processing continues when Ethernet is disconnected or the PC dashboard is closed.

AC2. Telemetry backpressure never stalls the STFT/WOLA sample path, frame trigger, FFT/IFFT engine, WOLA output, or core metrics path.

AC3. When the telemetry packet FIFO is intentionally forced full, the STFT/WOLA core shall continue processing without backpressure. `PACKET_FIFO_DROP_COUNT` shall increment for dropped pre-writer telemetry events or packets, `OVERFLOW_FLAGS.packet_fifo_overflow` shall be set, and `STATUS.packet_fifo_drop_count` shall expose the low 32 bits of `PACKET_FIFO_DROP_COUNT` to the PC dashboard. `DMA_DROP_COUNT` shall not be required to increment for drops that occur before the DDR writer accepts the record.

AC4. The HPS can read the FPGA ID and VERSION registers and write a harmless control register through the CSR bridge.

AC5. All 64-bit ring pointers use the Revision G snapshot/commit protocol. No torn low/high pointer transfer is accepted.

AC6. Core sample and frame counters are read only through `CORE_COUNT_SNAPSHOT` and coherent snapshot registers.

AC7. Ring initialization disables telemetry, resets transport state, commits ring configuration, resets producer pointer W = 0, commits Rd = 0, and only then enables the writer.

AC8. The ring writer uses the correct wrap-space rule Lreq = Ttail + Lrec when a normal record would cross the end of the ring.

AC9. WRAP records do not consume PC-visible telemetry sequence numbers. Sequence gaps are reported only for normal forwarded records.

AC10. DDR records use the 32-byte header, 64-byte alignment, little-endian fields, no implicit padding, and exact payload layouts defined in this document.

AC11. HPS validates packet headers, payload lengths, reserved flags, known packet types, and ringboundary conditions before forwarding UDP datagrams.

AC12. Packet payload sizes satisfy Table 17, including WAVE.nsamp range 1 to 192 and WAVE.stride semantics, exact SPEC129, SPEC64, METRICS, `STATUS.payload_bytes`=72 in Revision G, and
