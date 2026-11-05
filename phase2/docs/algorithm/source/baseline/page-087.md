# Baseline PDF page 087

Historical Part III, repository architecture. Printed page 74. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=87).

[Previous](../../baseline/page-086.md) | [Index](../../README.md) | [Next](../../baseline/page-088.md)

### 39.3 FFT modules

**Table 36. FFT/IFFT module inventory.**

| Module | Responsibility |
| --- | --- |
| `trecap_fft256.sv` | Normalized 256-point forward FFT wrapper or custom implementation. |
| `trecap_ifft256.sv` | Unscaled 256-point inverse FFT wrapper or custom implementation. |
| `complex_mul_q.sv` | Fixed-point complex multiply helper using the frozen rounding contract. |
| `bit_reverse_addr.sv` | Bit-reversal addressing helper if required by the selected FFT schedule. |
| `twiddle_rom.sv` | ROM wrapper for forward and inverse twiddle artifacts. |


### 39.4 Telemetry modules

Telemetry modules format records. They do not own DDR writes.

**Table 37. Telemetry module inventory.**

| Module | Responsibility |
| --- | --- |
| `trecap_telemetry_top.sv` | Integrates packet scheduler, packetizers, and packet FIFO. Exposes formatted records to `rtl/hps_bridge/`. |
| `trecap_packet_scheduler.sv` | Selects packet type emission based on packet enables, source mode, event rate, and priority. |
| `trecap_wave_packetizer.sv` | Creates WAVE payloads containing interleaved xdelayed , yout , and error triples with stride semantics. |
| `trecap_spec_packetizer.sv` | Creates SPEC64 or SPEC129 payloads using compressed magnitude and mask information. |
| `trecap_metrics_packetizer.sv` | Creates METRICS payloads from per-frame or aggregate counters. |
| `trecap_status_packetizer.sv` | Creates FPGA-originated STATUS skeleton records. HPS may patch only the outgoing UDP copy. |
| `trecap_packet_fifo.sv` | Buffers formatted records before HPS-bridge acceptance. Full FIFO drops records and increments `PACKET_FIFO_DROP_COUNT`. |


### 39.5 HPS bridge modules
