# Baseline PDF page 060

Historical Part II, DDR and UDP telemetry. Printed page 47. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=60).

[Previous](page-059.md) | [Index](../README.md) | [Next](page-061.md)

[Edit Markdown and LaTeX source](../source/baseline/page-060.md). Equations are rendered locally as SVG.

### 19.7 STATUS Payload

The STATUS packet is low-rate and shall be sent even when waveform or spectrum packets are disabled, unless `STATUS_EN`=0.

**Table 22. Baseline STATUS payload layout.**

| Offset | Field | Type | Meaning |
| --- | --- | --- | --- |
| 0 | `sample_count` | `uint64_t` | Current core sample count. Must equal header timestamp for FPGA-originated and HPS-patched STATUS packets. For diagnostic STATUS, it is the latest coherent core sample count known to HPS. |
| 8 | `frame_count` | `uint64_t` | Current STFT frame count. |
| 16 | `source_mode` | `uint32_t` | Active source mode. |
| 20 | `sample_rate` | `uint32_t` | Nominal live sample rate in samples per second. |
| 24 | `packet_enable` | `uint32_t` | Active packet-enable mask. |
| 28 | `dma_drop_count` | `uint32_t` | DDR-writer/ring-space drop counter low word. This is the low word of `DMA_DROP_COUNT`. |
| 32 | `udp_send_error_count` | `uint32_t` | HPS UDP send-failure counter low word. |
| 36 | `malformed_record_count` | `uint32_t` | HPS malformed-DDR-record counter low word. |
| 40 | `oversized_record_count` | `uint32_t` | HPS oversized-record counter low word. |
| 44 | `command_reject_count` | `uint32_t` | Combined HPS-owned and CSR-owned rejected-command counter low word. |
| 48 | `sequence_gap_count` | `uint32_t` | Committed/forwarded telemetry sequence gaps observed by HPS, excluding pre-commit FPGA drops. Otherwise zero. |
| 52 | `overflow_flags` | `uint32_t` | Sticky overflow/status flags. |
| 56 | `thr2_lo` | `uint32_t` | Active THR2[31:0]. |
| 60 | `thr2_hi` | `uint32_t` | Active THR2[55:32] in low bits. |
| 64 | `packet_fifo_drop_count` | `uint32_t` | Pre-writer packet-FIFO drop counter low word. This is the low word of `PACKET_FIFO_DROP_COUNT`. |
| 68 | reserved | `uint32_t` | Shall be zero. |


For Revision G, `STATUS.payload_bytes` shall equal 72. A STATUS record with any other payload size shall be rejected by the HPS/PC parser unless a later compatible revision explicitly defines a different STATUS layout. The two drop counters shall not be merged: `dma_drop_count` identifies DDR-writer, ring-space, oversized-record, or writer-policy drops after the DDR writer has accepted a record. `packet_fifo_drop_count` identifies pre-writer packet-FIFO or telemetry tap drops before
