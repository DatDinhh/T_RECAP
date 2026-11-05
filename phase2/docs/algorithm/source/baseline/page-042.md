# Baseline PDF page 042

Historical Part II, DDR and UDP telemetry. Printed page 29. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=42).

[Previous](../../baseline/page-041.md) | [Index](../../README.md) | [Next](../../baseline/page-043.md)

**Table 8. Normative CSR map, continued.**

| Offset | Name | Access | Meaning |
| --- | --- | --- | --- |
| 0x02C | `SOURCE_MODE_SHADOW` | W | Shadow source mode: 0 BRAM replay, 1 ADC live, 2 audio wrapper, 3 diagnostic source. |
| 0x030 | `SOURCE_MODE_COMMIT` | W1P | Writing 1 requests an atomic source-mode update under the source-mode change rule. The baseline commit resets affected source-adapter and stream-alignment state at a safe boundary. |
| 0x034 | `RING_BASE_LO` | W | FPGA-visible DDR ring base address bits [31 : 0]. |
| 0x038 | `RING_BASE_HI` | W | FPGA-visible DDR ring base address bits [63 : 32], if used by the bridge. |
| 0x03C | `RING_SIZE_BYTES` | W | Ring size in bytes. Must be a power of two and a multiple of 64. |
| 0x040 | `RING_CONFIG_COMMIT` | W1P | Latches base/size into the writer when telemetry is disabled. |
| 0x044 | `RING_WR_SNAPSHOT` | W1P | HPS writes 1 to request an atomic snapshot of the FPGA-owned producer pointer. |
| 0x048 | `RING_WR_LO_SNAP` | R | Latched producer pointer bits [31 : 0]. |
| 0x04C | `RING_WR_HI_SNAP` | R | Latched producer pointer bits [63 : 32]. |
| 0x050 | `RING_RD_LO_SHADOW` | W | HPS-owned consumer pointer shadow bits [31 : 0]. |
| 0x054 | `RING_RD_HI_SHADOW` | W | HPS-owned consumer pointer shadow bits [63 : 32]. |
| 0x058 | `RING_RD_COMMIT` | W1P | Writing 1 makes the shadow consumer pointer visible to the FPGA writer through a CDC-safe commit. |
| 0x05C | `DMA_DROP_COUNT` | R | Number of telemetry records dropped by the FPGA writer. |
| 0x060 | `DMA_PACKET_COUNT` | R | Number of telemetry records committed to DDR. |
| 0x064 | `DMA_STATUS` | R | DDR writer status bits. Bit definitions are frozen in Table 12. |
| 0x068 | `CORE_COUNT_SNAPSHOT` | W1P | HPS writes 1 to latch coherent sample and frame counters into snapshot registers. |
| 0x06C | `FRAME_COUNT_SNAP_LO` | R | Latched STFT frame count bits [31 : 0]. |
| 0x070 | `FRAME_COUNT_SNAP_HI` | R | Latched STFT frame count bits [63 : 32]. |
| 0x074 | `SAMPLE_COUNT_SNAP_LO` | R | Latched core sample count bits [31 : 0]. |
| 0x078 | `SAMPLE_COUNT_SNAP_HI` | R | Latched core sample count bits [63 : 32]. |
| 0x07C | `OVERFLOW_FLAGS` | R | Sticky overflow/error/status flags. Bit definitions are frozen in Table 13. |
| 0x080 | `CLEAR_STICKY_FLAGS` | W1C | Write-one-to-clear mask using the same bit map as `OVERFLOW_FLAGS`. |
| 0x084 | `CSR_COMMAND_REJECT_COUNT` | R | Number of command or state-change requests rejected by FPGA/CSR safety logic after HPS validation. HPS-owned rejects are held in HPS software status counters. |
