# Baseline PDF page 061

Historical Part II, DDR and UDP telemetry. Printed page 48. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=61).

[Previous](page-060.md) | [Index](../README.md) | [Next](page-062.md)

[Edit Markdown and LaTeX source](../source/baseline/page-061.md). Equations are rendered locally as SVG.

the DDR writer accepts a record.

## 20 HPS UDP Streamer Contract

### 20.1 HPS Responsibilities

The HPS software shall:

1. configure Ethernet and the PC destination address.

2. map the FPGA CSR window.

3. map the DDR ring buffer according to Section 17.6.

4. disable the telemetry writer and perform telemetry soft reset.

5. configure ring base/size, packet enables, decimation, and spectrum shift.

6. commit ring configuration, commit Rd = 0, and only then enable the FPGA telemetry writer.

7. atomically snapshot the producer pointer, read committed records, validate records, and forward valid records by UDP.

8. apply the Revision G malformed-record disable-and-reset policy.

9. commit the consumer pointer through `RING_RD_COMMIT`.

10. receive PC commands and translate accepted commands into CSR writes.

### 20.2 UDP Datagrams and Fragmentation Policy

Revision G does not support telemetry protocol fragmentation. The FPGA packet scheduler shall not generate records whose header plus payload exceeds:

![Equation 20.1: P_{&#92;mathrm{udp,max}}=1200&#92;text{ bytes}.&#92;tag{20.1}](../math/baseline-page-061-001.svg)

The HPS shall drop and count any oversized record instead of fragmenting it. This avoids IP fragmentation under a standard Ethernet MTU and keeps the PC parser deterministic. Each UDP datagram shall contain exactly one telemetry record header and its payload. Padding bytes used for DDR 64-byte alignment shall not be transmitted over UDP.

### 20.3 Nonblocking Send Rule

The HPS UDP socket shall be nonblocking or shall use a bounded send timeout. If sendto() fails, would block, or exceeds the bounded timeout, the HPS shall:

1. increment `udp_send_error_count`.

2. drop that UDP datagram.

3. advance the local DDR consumer pointer for the consumed record.

4. commit the new consumer pointer to FPGA.
