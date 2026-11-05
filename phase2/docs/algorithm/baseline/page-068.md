# Baseline PDF page 068

Historical Part II, DDR and UDP telemetry. Printed page 55. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=68).

[Previous](page-067.md) | [Index](../README.md) | [Next](page-069.md)

[Edit Markdown and LaTeX source](../source/baseline/page-068.md). Equations are rendered locally as SVG.

8. Verify that the FPGA producer pointer W is reset to zero using `RING_WR_SNAPSHOT`.

9. Configure THR2 shadow registers and pulse `THR2_COMMIT` if a non-default threshold is required.

10. Configure `WAVE_DECIM`, `SPEC_MODE`, and `SPEC_SHIFT`. Set `PACKET_ENABLE` initially to `STATUS_EN` only.

11. Enable `CONTROL.ring_writer_enable`.

12. Enable `CONTROL.telemetry_enable`.

13. Start or verify the HPS UDP streamer.

14. Start the PC dashboard and verify that valid STATUS packets are received.

15. After STATUS telemetry is verified, enable `WAVE_EN`, `SPEC_EN`, and `METRICS_EN` as needed for the demo.

16. Verify sequence numbers, packet sizes, timestamp semantics, and drop/error counters on the PC dashboard. STATUS-only bring-up reduces debug complexity. Waveform, spectrum, and metrics packets should be enabled only after the ring, UDP streamer, and PC parser are proven alive.

### 25.2 Shutdown Sequence

The HPS shall disable telemetry writer enable before releasing the DDR ring mapping. The FPGA core may continue processing samples while telemetry is disabled.

## 26 Failure Modes and Required Counters

**Table 26. Failure modes and required observability.**

| Failure mode | Required behavior | Required counter/status |
| --- | --- | --- |
| Ring full | Drop telemetry, continue core. | `DMA_DROP_COUNT`, ring-full flag. |
| Packet FIFO full | Drop the affected telemetry tap event or formatted telemetry packet. Do not backpressure the STFT/WOLA core. | `PACKET_FIFO_DROP_COUNT`. Packet-FIFO overflow sticky flag. `STATUS/DMA_STATUS` live-full indicators. |
| Malformed DDR record | HPS disables telemetry and requires soft reset plus ring reconfiguration. Byte-scanning resync is not in baseline. | Malformed-record count. |
| UDP send failure | HPS drops datagram and advances consumer pointer. | `udp_send_error_count`. |
