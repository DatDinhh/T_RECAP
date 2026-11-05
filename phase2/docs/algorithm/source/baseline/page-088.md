# Baseline PDF page 088

Historical Part III, repository architecture. Printed page 75. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=88).

[Previous](../../baseline/page-087.md) | [Index](../../README.md) | [Next](../../baseline/page-089.md)

**Table 38. HPS bridge module inventory.**

| Module | Responsibility |
| --- | --- |
| `trecap_csr_bank.sv` | Implements normative HPS-visible CSR registers, W1P controls, W1C sticky flags, VERSION reporting, and CSR-side command rejects. |
| `trecap_csr_shadow_commit.sv` | Provides shadow/commit logic for multi-word controls such as 56-bit THR2 and 64-bit ring pointers. |
| `trecap_ring_pointer_ctrl.sv` | Maintains producer and consumer pointer snapshots, preventing torn 64-bit pointer transfer. |
| `trecap_ddr_record_builder.sv` | Builds 32-byte record headers and 64-byte-aligned record bodies from formatted telemetry records. |
| `trecap_ddr_ring_writer.sv` | Owns DDR write master, WRAP/free-space logic, producer pointer commit, and `DMA_DROP_COUNT`. This module belongs only in `rtl/hps_bridge/`. |
| `trecap_hps_bridge_top.sv` | Integrates CSR bank, pointer control, record builder, DDR writer, CDC boundaries, and Platform Designer ports. |


### 39.6 DE1-SoC platform modules

**Table 39. DE1-SoC platform module inventory.**

| Module | Responsibility |
| --- | --- |
| `de1_soc_trecap_top.sv` | Board-facing top module. Owns physical pins, board resets, and top-level integration. |
| `clock_reset_ctrl.sv` | Clock/reset conditioning and reset synchronization for fabric domains. |
| `audio_codec_wrapper.sv` | Audio codec interface and LINE-IN/LINE-OUT wrapper. |
| `adc_wrapper.sv` | ADC interface wrapper and sample tick generation if ADC mode is used. |
| `platform_designer_wrapper.sv` | Generated Platform Designer system wrapper boundary. |


### 39.7 Top-level build variants

The repository shall provide explicit top-level build variants instead of one monolithic board top.
