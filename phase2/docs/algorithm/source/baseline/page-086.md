# Baseline PDF page 086

Historical Part III, repository architecture. Printed page 73. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=86).

[Previous](../../baseline/page-085.md) | [Index](../../README.md) | [Next](../../baseline/page-087.md)

## 39 RTL Module Inventory

### 39.1 Source modules

**Table 34. Input-source module inventory.**

| Module | Responsibility |
| --- | --- |
| `trecap_bram_replay_source.sv` | Feeds frozen `x_in.memh` samples and full-tail zero flush samples. Primary signoff source. |
| `trecap_audio_adapter.sv` | Maps audio codec samples into signed N = 12 core scale. LINE-IN is the first live-audio source. |
| `trecap_adc_adapter.sv` | Recenters unsigned ADC samples and optionally applies wrapper-level DC blocking. |
| `trecap_diagnostic_source.sv` | Produces deterministic hardware-generated debug streams such as ramp, impulse, and constant patterns. |
| `trecap_source_mux.sv` | Selects source mode. Source-mode changes shall reset source/core stream state or mark metric discontinuity. |


### 39.2 Core modules

**Table 35. Core RTL module inventory.**

| Module | Responsibility |
| --- | --- |
| `trecap_core_top.sv` | Core-only integration wrapper. Shall build without HPS, DDR, Ethernet, or dashboard code. |
| `trecap_input_ring.sv` | Circular buffer holding the most recent L = 256 input samples. |
| `trecap_frame_scheduler.sv` | Generates frame events every H = 128 sample ticks and tracks frame index. |
| `trecap_analysis_window.sv` | Multiplies frame samples by frozen quantized square-root Hann coefficients. |
| `window_rom.sv` | ROM wrapper for frozen `window_qw.memh`. No internal sine/cosine/window generation is allowed in RTL. |
| `trecap_hermitian_canonicalizer.sv` | Canonicalizes mirrored bins before threshold decisions. |
| `trecap_mag2_mask.sv` | Computes mag2, `pre_mask`, protection rules, final mask, and per-frame count inputs. |
| `trecap_spectrum_mask_builder.sv` | Builds conjugate-symmetric masked spectrum Xb. |
| `trecap_synthesis_wola.sv` | Applies synthesis window and overlap-add into the OLA ring. |
| `trecap_delay_error_metrics.sv` | Aligns x[n - D] with y[n], computes error, and accumulates live metrics. |
