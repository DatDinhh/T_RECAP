# Baseline PDF page 045

Historical Part II, DDR and UDP telemetry. Printed page 32. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=45).

[Previous](../../baseline/page-044.md) | [Index](../../README.md) | [Next](../../baseline/page-046.md)

**Table 11. STATUS bit definitions.**

| Bit | Name | Meaning |
| --- | --- | --- |
| 0 | `telemetry_enabled` | Active telemetry-enable state. |
| 1 | `ring_writer_enabled` | Active DDR ring-writer enable state. |
| 2 | `ring_configured` | Ring base and size have been committed and accepted. |
| 3 | `writer_busy` | DDR writer is actively writing or committing a record. |
| 4 | `core_alive` | Core/sample activity heartbeat toggled or asserted by the FPGA. |
| 5 | `malformed_config` | Current ring/control configuration is malformed or not accepted. |
| 6 | `ring_full` | Ring has insufficient free space for at least one scheduled telemetry record. |
| 7 | `packet_fifo_full` | Telemetry packet FIFO has reached full condition. |
| 8 | `thr2_commit_pending` | A THR2 commit is pending safe-frame application. |
| 9 | `source_commit_pending` | A source-mode commit is pending safe application. |
| 31:10 | reserved | Shall read as zero unless a later revision assigns the bit. |


**Table 12. DMA_STATUS bit definitions.**

| Bit | Name | Meaning |
| --- | --- | --- |
| 0 | `writer_idle` | DDR writer FSM is idle. |
| 1 | `writer_busy` | DDR writer FSM is processing a record or waiting for write completion. |
| 2 | `no_space` | Last attempted record did not fit under the free-space rule. |
| 3 | `malformed_config` | Base, size, or alignment configuration is invalid. |
| 4 | `ring_full` | Ring occupancy has reached the writer’s full threshold. |
| 5 | `packet_fifo_full` | Packet FIFO full condition is active or was recently observed. |
| 6 | `ddr_wait` | Writer is blocked by DDR/Avalon waitrequest or equivalent bus backpressure. |
| 7 | `drop_active` | A telemetry record is currently being dropped or was dropped in the current writer service interval. |
| 31:8 | reserved | Shall read as zero unless a later revision assigns the bit. |
