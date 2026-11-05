# Baseline PDF page 051

Historical Part II, DDR and UDP telemetry. Printed page 38. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=51).

[Previous](page-050.md) | [Index](../README.md) | [Next](page-052.md)

[Edit Markdown and LaTeX source](../source/baseline/page-051.md). Equations are rendered locally as SVG.

where Hbytes = 32 for the baseline packet header and Pbytes is the payload length. This equation applies to normal records only. A WRAP record uses the special effective length rule below. Records shall start on 64-byte-aligned offsets and shall not cross the physical end of the ring. If a normal record would cross the end of the ring and sufficient free space exists for the required wrap, the writer shall first commit a WRAP record. A WRAP record has:

- `packet_type` = 0x007F.

- `payload_bytes` = 0.

- effective DDR record length equal to R - o, not align64 (32 + `payload_bytes`).

- valid only when o = ̸ 0, R - o ≥ 64, and the physical tail contains the 32-byte header plus zero padding.

- all bytes after the 32-byte header through the physical end of the ring set to zero. After the WRAP record is committed, W ← W + (R - o), the next record starts at offset zero, and the normal packet may be written. The generic Lrec = align64 (32 + `payload_bytes`) rule shall not be used to advance across a WRAP record. WRAP records shall not consume a PC-visible telemetry sequence number. The seq field in a WRAP record is ignored and shall be zero or equal to the previous committed normal telemetry sequence. Revision G allocates and increments the global sequence counter only after a normal telemetry record is accepted and committed to DDR. Packet-FIFO drops and DDR-writer drops before commit do not consume sequence numbers. Those loss events are visible through `PACKET_FIFO_DROP_COUNT` and `DMA_DROP_COUNT`, not through PC sequence gaps. PC sequence-gap detection shall use modulo-![2^{32}](../math/baseline-page-051-001.svg) arithmetic: the expected next sequence is (`previous_seq` + 1) mod 232 . Thus `sequence_gap_count` refers to gaps in the committed/forwarded telemetry sequence, not pre-commit FPGA drops.

### 17.6 Memory Coherency Requirement

The DDR ring memory shall be mapped as non-cacheable, strongly ordered, or DMA-coherent from the HPS reader’s point of view. If a cached mapping is used, the implementation shall explicitly invalidate cache lines before reading each committed record. Reading stale cached ring data is a contract violation. The FPGA shall complete all DDR writes for a record before updating the producer pointer. The HPS shall treat the atomically-read producer pointer as the commit boundary. The HPS shall not read beyond the committed producer pointer.

## 18 DDR Packet Record Format

### 18.1 Common Header

All DDR telemetry records use the 32-byte header in Table 14. All fields are little-endian and packed with no implicit C padding. Numeric multi-byte fields shall be parsed as little-endian integers. The telemetry magic is a numeric constant. Receivers shall compare the parsed `uint32_t` value to 0x54524350. The raw byte sequence in memory for that numeric value is 50 43 52 54, so implementations shall not compare the byte stream to the ASCII string TRCP. The same header
