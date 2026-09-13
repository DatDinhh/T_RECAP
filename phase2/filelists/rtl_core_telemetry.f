# AUTO-GENERATED - DO NOT EDIT
# Generator: scripts/gen_filelists.py
# Generator version: r1.4.0
# Filelist: standalone normalized-source core plus non-stalling telemetry composition
# Expected source files are active entries by default; compile targets fail if missing.

+incdir+rtl/include
+incdir+rtl/include/generated
+incdir+rtl/interfaces

rtl/include/generated/trecap_core_pkg.sv
rtl/include/generated/trecap_csr_pkg.sv
rtl/include/generated/trecap_packet_pkg.sv
rtl/include/generated/trecap_iface_pkg.sv
rtl/include/trecap_math_pkg.sv
rtl/include/trecap_build_pkg.sv
rtl/common/round_sat.sv
rtl/common/reset_sync.sv
rtl/common/sync_pulse.sv
rtl/common/sync_bus_snapshot.sv
rtl/common/skid_buffer.sv
rtl/common/simple_dual_port_ram.sv
rtl/common/true_dual_port_ram.sv
rtl/common/sync_fifo.sv
rtl/common/async_fifo.sv
rtl/interfaces/trecap_sample_if.sv
rtl/interfaces/trecap_frame_if.sv
rtl/interfaces/trecap_core_tap_if.sv
rtl/interfaces/trecap_record_if.sv
rtl/interfaces/trecap_csr_if.sv
rtl/interfaces/trecap_avmm_if.sv
rtl/fft/complex_mul_q.sv
rtl/fft/bit_reverse_addr.sv
rtl/fft/twiddle_rom.sv
rtl/fft/trecap_fft_stage.sv
rtl/fft/trecap_fft256.sv
rtl/fft/trecap_ifft256.sv
rtl/core/trecap_input_ring.sv
rtl/core/trecap_frame_scheduler.sv
rtl/core/window_rom.sv
rtl/core/trecap_analysis_window.sv
rtl/core/trecap_hermitian_canonicalizer.sv
rtl/core/trecap_mag2_mask.sv
rtl/core/trecap_spectrum_mask_builder.sv
rtl/core/trecap_synthesis_wola.sv
rtl/core/trecap_delay_error_metrics.sv
rtl/core/trecap_core_top.sv
rtl/telemetry/trecap_packet_scheduler.sv
rtl/telemetry/trecap_wave_packetizer.sv
rtl/telemetry/trecap_spec_packetizer.sv
rtl/telemetry/trecap_metrics_packetizer.sv
rtl/telemetry/trecap_status_packetizer.sv
rtl/telemetry/trecap_priority_dropper.sv
rtl/telemetry/trecap_packet_fifo.sv
rtl/telemetry/trecap_telemetry_top.sv
rtl/top/trecap_core_telemetry_top.sv
