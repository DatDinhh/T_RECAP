# Hand-written C0 functional regression filelist.
# Run from the repository root.

+incdir+rtl/include
+incdir+rtl/include/generated

rtl/include/generated/trecap_core_pkg.sv
rtl/include/generated/trecap_packet_pkg.sv
rtl/include/generated/trecap_iface_pkg.sv
rtl/sources/trecap_bram_replay_source.sv
rtl/core/trecap_input_ring.sv
rtl/core/trecap_frame_scheduler.sv
sim/tb/tb_trecap_c0_flow_control.sv
