# Baseline PDF page 043

Historical Part II, DDR and UDP telemetry. Printed page 30. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=43).

[Previous](../../baseline/page-042.md) | [Index](../../README.md) | [Next](../../baseline/page-044.md)

**Table 8. Normative CSR map, continued.**

| Offset | Name | Access | Meaning |
| --- | --- | --- | --- |
| 0x088 | `PACKET_FIFO_DROP_COUNT` | R | Number of telemetry tap events or formatted telemetry packets dropped before acceptance by the DDR ring writer because a telemetry packet FIFO was full or could not accept the event. This counter is distinct from `DMA_DROP_COUNT`. |


### 16.3 Version Compatibility Rule

HPS software shall check VERSION before enabling telemetry. The register packing is VERSION[31:16] = major and VERSION[15:0] = minor. Revision G shall report VERSION = 0x0001_0007. If the major version does not match the expected major version, the HPS shall reject the transport configuration and leave telemetry disabled. Minor-version mismatches may be accepted only if the HPS software explicitly supports the advertised minor version.

### 16.4 CSR Bit Definitions

Table 9 freezes whether each CONTROL bit is a persistent level or a write-one pulse. Writing zero to a W1P bit has no effect. Writing one to a W1P bit shall not modify persistent level bits.

**Table 9. CONTROL bit definitions.**

| Bit | Name | Type | Meaning |
| --- | --- | --- | --- |
| 0 | `telemetry_enable` | Level | 1 enables the telemetry writer. 0 disables the writer after the current record completes or is dropped. |
| 1 | `telemetry_soft_reset` | W1P | Resets the telemetry formatter, packet FIFOs, writer FSM, and transport counters. |
| 2 | `clear_metrics` | W1P | Requests a core metric clear at a safe frame/sample boundary. |
| 3 | reserved | - | Reserved in Revision G. Sticky flags are cleared directly by writing a one-mask to `CLEAR_STICKY_FLAGS`. |
| 4 | `ring_writer_enable` | Level | Enables DDR ring writes after the ring is configured. |
| 31:5 | reserved | - | Shall be written as zero and ignored on read. |
