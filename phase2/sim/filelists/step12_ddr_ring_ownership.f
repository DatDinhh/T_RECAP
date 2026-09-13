# Step-12 HPS/FPGA DDR-ring ownership, boundary, reset, and AVMM-response regression.

+incdir+rtl/include
+incdir+rtl/include/generated
+incdir+rtl/interfaces

rtl/include/generated/trecap_core_pkg.sv
rtl/include/generated/trecap_csr_pkg.sv
rtl/include/generated/trecap_packet_pkg.sv
rtl/include/generated/trecap_iface_pkg.sv
rtl/include/trecap_math_pkg.sv
rtl/include/trecap_build_pkg.sv
rtl/hps_bridge/trecap_csr_shadow_commit.sv
rtl/hps_bridge/trecap_avmm_csr_adapter.sv
rtl/hps_bridge/trecap_csr_bank.sv
rtl/hps_bridge/trecap_ring_pointer_ctrl.sv
rtl/hps_bridge/trecap_ddr_record_builder.sv
rtl/hps_bridge/trecap_avmm_write_master.sv
rtl/hps_bridge/trecap_ddr_ring_writer.sv
rtl/hps_bridge/trecap_hps_bridge_top.sv
sim/tb/tb_trecap_step12_ddr_ring_ownership.sv
