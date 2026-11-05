# Baseline PDF page 104

Historical appendices and references. Printed page 91. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=104).

[Previous](../../baseline/page-103.md) | [Index](../../README.md) | [Next](../../baseline/page-105.md)

```text
   trecap_metrics_packetizer.sv
   trecap_status_packetizer.sv
   trecap_packet_fifo.sv

rtl/hps_bridge/
  trecap_csr_bank.sv
  trecap_csr_shadow_commit.sv
  trecap_ring_pointer_ctrl.sv
  trecap_ddr_record_builder.sv
  trecap_ddr_ring_writer.sv
  trecap_hps_bridge_top.sv

rtl/top/
  trecap_core_only_top.sv
  trecap_core_bram_replay_top.sv
  trecap_core_telemetry_top.sv
  trecap_de1soc_full_top.sv

rtl/platform/de1soc/
  de1_soc_trecap_top.sv
  clock_reset_ctrl.sv
  audio_codec_wrapper.sv
  adc_wrapper.sv
  platform_designer_wrapper.sv

filelists/
  rtl_core.f
  rtl_core_plus_fft.f
  rtl_telemetry.f
  rtl_hps_bridge.f
  rtl_de1soc_full.f
  quartus_de1soc.qsf.inc

config/profiles/
  baseline_core.json
  sim_core_only.json
  de1soc_bram_replay.json
  de1soc_linein_demo.json
  telemetry_status_only.json
  telemetry_full_demo.json
```

## D Repository Minimum Documentation Files

```text
docs/architecture/
  repo_architecture.md
  module_inventory.md
  interface_contracts.md
  module_api.md
  build_order.md
  generated_contracts.md
  generated_header_flow.md
```
