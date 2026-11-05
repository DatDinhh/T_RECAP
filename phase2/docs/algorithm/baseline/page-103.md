# Baseline PDF page 103

Historical appendices and references. Printed page 90. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=103).

[Previous](page-102.md) | [Index](../README.md) | [Next](page-104.md)

[Edit Markdown and LaTeX source](../source/baseline/page-103.md). Equations are rendered locally as SVG.

## C Repository Recommended File Inventory

```text
rtl/include/
  generated/
    trecap_core_pkg.sv
    trecap_csr_pkg.sv
    trecap_packet_pkg.sv
    trecap_iface_pkg.sv
  trecap_math_pkg.sv
  trecap_build_pkg.sv

rtl/common/
  round_sat.sv
  reset_sync.sv
  sync_pulse.sv
  sync_bus_snapshot.sv
  skid_buffer.sv
  true_dual_port_ram.sv
  simple_dual_port_ram.sv
  sync_fifo.sv
  async_fifo.sv

rtl/sources/
  trecap_bram_replay_source.sv
  trecap_audio_adapter.sv
  trecap_adc_adapter.sv
  trecap_diagnostic_source.sv
  trecap_source_mux.sv

rtl/core/
  trecap_core_top.sv
  trecap_input_ring.sv
  trecap_frame_scheduler.sv
  trecap_analysis_window.sv
  window_rom.sv
  trecap_hermitian_canonicalizer.sv
  trecap_mag2_mask.sv
  trecap_spectrum_mask_builder.sv
  trecap_synthesis_wola.sv
  trecap_delay_error_metrics.sv

rtl/fft/
  trecap_fft256.sv
  trecap_ifft256.sv
  complex_mul_q.sv
  bit_reverse_addr.sv
  twiddle_rom.sv

rtl/telemetry/
  trecap_telemetry_top.sv
  trecap_packet_scheduler.sv
  trecap_wave_packetizer.sv
  trecap_spec_packetizer.sv
```
