# Baseline PDF page 085

Historical Part III, repository architecture. Printed page 72. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=85).

[Previous](page-084.md) | [Index](../README.md) | [Next](page-086.md)

- HPS software shall not contain signal-processing algorithms.

- Python packet parsers shall import generated constants from `sw/pc_dashboard/generated/`. Dashboard parsers shall not duplicate packet offsets manually.

## 38 RTL Layer Ownership

### 38.1 Layer partition

**Table 33. RTL layer ownership.**

| Layer | Directory | Ownership |
| --- | --- | --- |
| A | rtl/sources/ | Source adapters and source mux. Converts BRAM, audio, ADC, or diagnostic input into signed core sample ticks. |
| B | rtl/core/ + rtl/fft/ | STFT/WOLA algorithm path, including frame scheduler, FFT/IFFT, canonicalization, masking, WOLA, and metrics. |
| C | rtl/telemetry/ | Non-stalling observation and packet formatting. Produces formatted records but does not write DDR. |
| D | `rtl/hps_bridge/` | CSR bank, pointer control, DDR record builder, DDR ring writer, and HPS bridge top. |
| E | rtl/platform/de1soc/ + rtl/top/ | Board-specific integration, Platform Designer wrapper, clocks/resets, audio/ADC wrappers, and top-level port binding. |


### 38.2 Dataflow

```text
source_mux
  -> input_ring
  -> frame_scheduler
  -> analysis_window
  -> fft256
  -> hermitian_canonicalizer
  -> mag2_mask
  -> spectrum_mask_builder
  -> ifft256
  -> synthesis_wola
  -> delay_error_metrics
  -> y_out

core taps
  -> telemetry packetizers
  -> packet_fifo
  -> hps_bridge record builder
  -> ddr_ring_writer
  -> HPS DDR ring
```
