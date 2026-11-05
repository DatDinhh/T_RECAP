# Baseline PDF page 047

Historical Part II, DDR and UDP telemetry. Printed page 34. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=47).

[Previous](page-046.md) | [Index](../README.md) | [Next](page-048.md)

Independent low/high half updates are not a valid pointer transfer.

### 16.7 Core Counter Snapshot Rule

The HPS shall not read live multiword sample or frame counters by independently sampling low and high halves. To read coherent core counters, the HPS shall:

1. write `CORE_COUNT_SNAPSHOT`=1.

2. read `FRAME_COUNT_SNAP_LO` and `FRAME_COUNT_SNAP_HI`.

3. read `SAMPLE_COUNT_SNAP_LO` and `SAMPLE_COUNT_SNAP_HI`. The frame-count and sample-count snapshot registers shall remain stable until the next `CORE_COUNT_SNAPSHOT` request. Reading the snapshot registers shall not modify the counters.

### 16.8 Sticky-Flag Clear Rule

`CLEAR_STICKY_FLAGS` is a write-one-to-clear mask register. Writing a 1 to bit b clears sticky flag b. Writing a 0 to bit b leaves sticky flag b unchanged. CONTROL[3] is reserved in Revision G and shall not be used as a second clear mechanism. The bit positions for `CLEAR_STICKY_FLAGS` are identical to Table 13.

### 16.9 Command-Reject Counter Ownership

The CSR-visible `CSR_COMMAND_REJECT_COUNT` counts only rejects caused by FPGA/CSR safety logic after the HPS has accepted a command for CSR translation. HPS-owned rejects: wrong source IP, wrong UDP port, malformed command header, bad command magic, unsupported command type, or HPS-side range validation failure remain in HPS software counters. In patched STATUS packets, `command_reject_count` shall report the low 32 bits of:

`hps_command_reject_count` + `csr_command_reject_count`.

The HPS shall not write HPS-only command reject counts back into the FPGA CSR bank unless a later revision defines an explicit HPS-owned counter register. HPS-owned command rejects shall not set `OVERFLOW_FLAGS.illegal_command` or any other FPGA sticky flag. FPGA/CSR-side rejected requests may increment `CSR_COMMAND_REJECT_COUNT` and may set `OVERFLOW_FLAGS.illegal_command`.

### 16.10 Packet-FIFO Drop Accounting Rule

`PACKET_FIFO_DROP_COUNT` counts telemetry drops that occur before the DDR writer accepts a packet for ring-space scheduling. These drops can occur when a telemetry tap event or already formatted telemetry packet reaches a packet FIFO that is full, temporarily unable to accept the event, or evicts/sheds a lower-priority resident record under the priority-admission rule. `DMA_DROP_COUNT` counts telemetry records dropped by the FPGA DDR writer after the record has reached the writer scheduling/free-space stage, including drops caused by insufficient ring free space, oversized records, writer blocking, or the writer’s explicit priority/drop policy.
