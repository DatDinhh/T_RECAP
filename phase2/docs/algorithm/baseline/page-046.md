# Baseline PDF page 046

Historical Part II, DDR and UDP telemetry. Printed page 33. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=46).

[Previous](page-045.md) | [Index](../README.md) | [Next](page-047.md)

**Table 13. OVERFLOW_FLAGS and CLEAR_STICKY_FLAGS bit definitions.**

| Bit | Name | Meaning / clear behavior |
| --- | --- | --- |
| 0 | `arithmetic_overflow` | Core arithmetic overflow or unexpected internal range violation was observed. Write 1 to `CLEAR_STICKY_FLAGS`[0] to clear. |
| 1 | `ola_overflow` | OLA accumulator overflow or saturation-risk condition was observed. Write 1 to clear. |
| 2 | `ring_overflow` | Ring occupancy rule was violated or would have been violated without dropping. Write 1 to clear. |
| 3 | `packet_fifo_overflow` | Packet FIFO overflow/drop condition occurred. Write 1 to clear. |
| 4 | `malformed_packet` | Malformed DDR record or packet header was observed. Write 1 to clear. |
| 5 | `illegal_command` | FPGA/CSR-side illegal command or illegal CSR safety request was observed. Write 1 to clear. |
| 6 | `cdc_error` | CDC protocol violation or invalid snapshot/commit condition was detected. Write 1 to clear. |
| 7 | `threshold_range_error` | Requested THR2 was outside the legal 56-bit baseline range. Write 1 to clear. |
| 8 | `source_mode_error` | Illegal or unsafe source-mode transition was requested. Write 1 to clear. |
| 9 | `oversized_record` | Record exceeded the Revision G UDP size bound or packet-type maximum. Write 1 to clear. |
| 31:10 | reserved | Shall read as zero. Writing ones to reserved bits in `CLEAR_STICKY_FLAGS` has no effect. |


### 16.6 Atomic 64-bit Pointer Transfer

All 64-bit ring pointers exposed through 32-bit CSR halves shall use an atomic snapshot/commit protocol. For the FPGA-owned producer pointer W , the HPS shall read it as follows:

1. HPS writes `RING_WR_SNAPSHOT`=1.

2. The CSR bank latches the current 64-bit producer pointer into `RING_WR_LO_SNAP` and `RING_WR_HI_SNAP`.

3. HPS reads the latched low and high words. For the HPS-owned consumer pointer Rd , the HPS shall write it as follows:

1. HPS writes `RING_RD_LO_SHADOW`.

2. HPS writes `RING_RD_HI_SHADOW`.

3. HPS writes `RING_RD_COMMIT`=1.

4. The FPGA writer consumes the committed 64-bit value only after a CDC-safe synchronization or handshake.
