// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/hps_bridge/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Top-level HPS bridge integration for CSR control/status and DDR telemetry writes.
// Contract: Integrates the HPS-visible CSR bank with the DDR ring writer boundary.  It does not
//           compute FFT/IFFT/WOLA/masks/error, does not own Ethernet/UDP sockets, and does not
//           feed backpressure into the STFT/WOLA mathematical core.

`default_nettype none

// T-RECAP HPS bridge top.
//
// This block is the FPGA-side bridge boundary used by DE1-SoC Platform Designer integration:
//   - HPS-to-FPGA lightweight Avalon-MM CSR access enters through csr_avs_*.
//   - Formatted records from rtl/telemetry/ enter through record_*.
//   - DDR writes leave through an Avalon-MM-style write master boundary avm_*.
//
// The first implementation baseline is a single synchronous fabric/bridge clock.  The module API
// preserves explicit safe-boundary and snapshot/commit hooks so a later split-clock integration can
// insert CDC wrappers at this boundary without moving DDR-writer ownership into rtl/telemetry/.
module trecap_hps_bridge_top
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned CSR_AVMM_ADDR_W     = 21,
    parameter int unsigned CSR_ADDR_W          = 12,
    parameter int unsigned CSR_BURSTCOUNT_W    = 1,
    parameter int unsigned RECORD_DATA_W       = 32,
    parameter int unsigned RECORD_KEEP_W       = (RECORD_DATA_W + 7) / 8,
    parameter int unsigned AVMM_ADDR_W         = 64,
    parameter int unsigned AVMM_DATA_W         = 64,
    parameter int unsigned AVMM_BYTEEN_W       = (AVMM_DATA_W + 7) / 8,
    parameter int unsigned AVMM_BURSTCOUNT_W   = 1,
    parameter int unsigned GUARD_BYTES         = TCSR_RING_GUARD_BYTES_MIN,
    parameter logic [31:0] RING_SIZE_MIN_BYTES = 32'h0010_0000
) (
    input  logic                         clk,
    input  logic                         rst_n,
    // Synchronous integration-owned transport epoch clear. The CSR soft-reset command is ORed
    // with this input so source/core and telemetry/DDR can share one explicit clear epoch.
    input  logic                         external_transport_clear_i,

    // HPS lightweight-aperture Avalon-MM CSR agent. csr_avs_address_i is a BYTE address relative
    // to the complete 2 MiB aperture; the adapter must retain all bits until the 4 KiB decode.
    input  logic [CSR_AVMM_ADDR_W-1:0]   csr_avs_address_i,
    input  logic                         csr_avs_read_i,
    input  logic                         csr_avs_write_i,
    input  logic [31:0]                  csr_avs_writedata_i,
    input  logic [3:0]                   csr_avs_byteenable_i,
    input  logic [CSR_BURSTCOUNT_W-1:0]  csr_avs_burstcount_i,
    output logic                         csr_avs_waitrequest_o,
    output logic [31:0]                  csr_avs_readdata_o,
    output logic                         csr_avs_readdatavalid_o,
    output logic                         csr_avs_writeresponsevalid_o,
    output logic [1:0]                   csr_avs_response_o,

    // Safe-boundary inputs from the core/source integration layer.  They must be synchronous to clk
    // in this single-clock baseline.  Later split-clock builds shall synchronize them before entry.
    input  logic                         frame_boundary_i,
    input  logic                         source_safe_boundary_i,
    input  trecap_source_mode_e          actual_source_mode_i,
    input  logic                         source_transition_busy_i,
    input  logic                         transport_epoch_idle_i,

    input  logic                         replay_start_ready_i,
    input  logic                         replay_request_busy_i,
    input  logic                         replay_start_accept_pulse_i,
    input  logic                         replay_start_reject_pulse_i,
    input  logic                         replay_active_i,
    input  logic                         replay_path_busy_i,
    input  logic                         replay_path_done_i,
    input  logic                         replay_e2e_busy_i,
    input  logic                         replay_e2e_done_i,
    input  logic                         replay_error_i,
    input  logic                         replay_rearm_required_i,

    // Coherent live observations used by CSR snapshots and STATUS telemetry context.
    input  logic                         core_alive_i,
    input  logic [63:0]                  core_frame_count_i,
    input  logic [63:0]                  core_sample_count_i,

    // Formatted telemetry record stream from rtl/telemetry/.  Metadata shall remain stable for all
    // beats of one record.  This top never returns a ready signal to the mathematical core.
    input  logic                         record_valid_i,
    output logic                         record_ready_o,
    input  trecap_record_meta_t          record_meta_i,
    input  logic [RECORD_DATA_W-1:0]     record_payload_data_i,
    input  logic [RECORD_KEEP_W-1:0]     record_payload_keep_i,
    input  logic                         record_payload_last_i,

    // Pre-writer telemetry status from rtl/telemetry/trecap_packet_fifo.sv.
    input  logic [31:0]                  packet_fifo_drop_count_i,
    input  logic                         packet_fifo_drop_pulse_i,
    input  logic                         packet_fifo_full_i,
    input  logic                         packet_fifo_overflow_i,

    // Additional sticky/error sources already synchronized to clk.  These are ORed into the CSR
    // sticky OVERFLOW_FLAGS set path and are cleared by the owner through clear_sticky_flags_w1c_o.
    input  logic [31:0]                  external_overflow_flags_set_i,
    input  logic                         external_csr_reject_pulse_i,

    // Avalon-MM write-master boundary toward the Platform Designer HPS-visible DDR path.
    output logic [AVMM_ADDR_W-1:0]       avm_address_o,
    output logic                         avm_write_o,
    output logic [AVMM_DATA_W-1:0]       avm_writedata_o,
    output logic [AVMM_BYTEEN_W-1:0]     avm_byteenable_o,
    output logic [AVMM_BURSTCOUNT_W-1:0] avm_burstcount_o,
    input  logic                         avm_waitrequest_i,
    input  logic                         avm_writeresponsevalid_i,
    input  logic [1:0]                   avm_response_i,

    // Active controls exported to the core/telemetry/source integration layer.
    output trecap_hps_bridge_ctrl_t      ctrl_o,
    output trecap_ring_config_t          ring_config_o,
    output logic                         telemetry_soft_reset_pulse_o,
    output logic                         clear_metrics_pulse_o,
    output logic                         counter_clear_pulse_o,
    output logic                         replay_start_pulse_o,
    output logic                         replay_rearm_pulse_o,
    output logic                         thr2_apply_pulse_o,
    output logic                         source_mode_apply_pulse_o,
    output logic [31:0]                  clear_sticky_flags_w1c_o,

    // Snapshot/commit/debug pulses visible to the platform top and bring-up scripts.
    output logic                         ring_config_commit_pulse_o,
    output logic                         ring_wr_snapshot_req_pulse_o,
    output logic                         ring_rd_commit_req_pulse_o,
    output logic                         core_count_snapshot_pulse_o,
    output logic                         ring_rd_accept_pulse_o,
    output logic                         ring_rd_reject_pulse_o,
    output logic                         writer_ring_wr_snapshot_valid_o,
    output logic                         writer_ring_wr_snapshot_pulse_o,

    // CSR-visible status mirrors and counters.
    output logic [31:0]                  status_o,
    output logic [31:0]                  dma_status_o,
    output logic [31:0]                  overflow_flags_o,
    output logic [31:0]                  csr_command_reject_count_o,
    output logic [31:0]                  dma_drop_count_o,
    output logic [31:0]                  dma_packet_count_o,

    // DDR ring observability.
    output logic [63:0]                  producer_ptr_o,
    output logic [63:0]                  consumer_ptr_o,
    output logic [31:0]                  sequence_o,
    output logic [63:0]                  used_bytes_o,
    output logic [63:0]                  free_bytes_o,
    output logic [63:0]                  current_offset_o,
    output logic [63:0]                  current_tail_bytes_o,

    // HPS-bridge health/status pins for platform wrappers, LEDs, or later assertions.
    output logic                         writer_idle_o,
    output logic                         writer_busy_o,
    output logic                         writer_no_space_o,
    output logic                         malformed_config_o,
    output logic                         ring_full_o,
    output logic                         ddr_wait_o,
    output logic                         drop_active_o,
    output logic                         ring_configured_o,
    output logic                         pointers_valid_o,
    output logic                         writer_fault_sticky_o,
    output logic                         normal_commit_pulse_o,
    output logic                         wrap_commit_pulse_o,
    output logic                         writer_drop_pulse_o,
    output logic                         writer_malformed_pulse_o,
    output logic                         writer_oversized_pulse_o,
    output logic                         packet_fifo_full_status_o,
    output logic                         packet_fifo_overflow_status_o
);

    trecap_hps_bridge_ctrl_t ctrl_w;
    trecap_ring_config_t     ring_config_w;

    logic                    csr_leaf_valid;
    logic                    csr_leaf_write;
    logic [CSR_ADDR_W-1:0]   csr_leaf_addr;
    logic [31:0]             csr_leaf_wdata;
    logic                    csr_leaf_ready;
    logic                    csr_leaf_rvalid;
    logic [31:0]             csr_leaf_rdata;
    logic                    csr_leaf_error;
    logic                    csr_adapter_local_reject_pulse;

    logic                    csr_telemetry_soft_reset_pulse;
    logic                    csr_clear_metrics_pulse;
    logic                    csr_counter_clear_pulse;
    logic                    csr_replay_start_pulse;
    logic                    csr_replay_rearm_pulse;
    logic                    csr_thr2_apply_pulse;
    logic                    csr_source_mode_apply_pulse;
    logic                    csr_ring_config_commit_pulse;
    logic                    csr_ring_wr_snapshot_pulse;
    logic                    csr_ring_rd_commit_pulse;
    logic                    csr_core_count_snapshot_pulse;
    logic [31:0]             csr_clear_sticky_flags_w1c;
    logic [31:0]             csr_status;
    logic [31:0]             csr_dma_status;
    logic [31:0]             csr_overflow_flags;
    logic [31:0]             csr_command_reject_count;
    logic                    csr_reject_pulse;
    logic                    csr_malformed_config;
    logic [63:0]             csr_ring_rd_committed;
    logic                    csr_ring_rd_commit_pending;

    logic                    writer_ring_rd_commit_ready;
    logic [63:0]             writer_ring_wr_snapshot;
    logic                    writer_ring_wr_snapshot_valid;
    logic                    writer_ring_wr_snapshot_pulse;
    logic                    writer_idle;
    logic                    writer_busy;
    logic                    writer_no_space;
    logic                    writer_malformed_config;
    logic                    writer_ring_full;
    logic                    writer_ddr_wait;
    logic                    writer_drop_active;
    logic                    writer_ring_configured;
    logic                    writer_pointers_valid;
    logic                    writer_fault_sticky;
    logic [31:0]             writer_dma_drop_count;
    logic [31:0]             writer_dma_packet_count;
    logic [31:0]             writer_overflow_flags_set;
    logic                    writer_normal_commit_pulse;
    logic                    writer_wrap_commit_pulse;
    logic                    writer_drop_pulse;
    logic                    writer_malformed_pulse;
    logic                    writer_oversized_pulse;
    logic                    writer_ring_rd_accept_pulse;
    logic                    writer_ring_rd_reject_pulse;

    logic [31:0]             overflow_flags_set_comb;
    logic [31:0]             writer_overflow_flags_seen_q;
    logic [31:0]             writer_overflow_flags_new;
    logic                    packet_fifo_overflow_q;
    logic                    packet_fifo_overflow_rise;
    logic                    writer_fault_sticky_q;
    logic                    writer_fault_rise;
    logic                    writer_transport_clear;

    assign writer_transport_clear = csr_telemetry_soft_reset_pulse |
                                    external_transport_clear_i;
    assign writer_overflow_flags_new = writer_overflow_flags_set & ~writer_overflow_flags_seen_q;
    assign packet_fifo_overflow_rise = packet_fifo_overflow_i & ~packet_fifo_overflow_q;
    assign writer_fault_rise = writer_fault_sticky & ~writer_fault_sticky_q;

    // Convert local sticky/status sources into CSR set events. This keeps CLEAR_STICKY_FLAGS useful
    // at the CSR level even if a lower subblock keeps a debug sticky latch until telemetry soft
    // reset. writer_overflow_flags_seen_q is episode history, not a permanent ever-seen mask: a
    // bit re-arms after the lower source deasserts and can report a later recurrence. Quantitative
    // counters remain owned by their source blocks.
    always_comb begin
        overflow_flags_set_comb = external_overflow_flags_set_i | writer_overflow_flags_new;

        if (packet_fifo_drop_pulse_i || packet_fifo_overflow_rise) begin
            overflow_flags_set_comb |= TCSR_OVERFLOW_FLAGS_PACKET_FIFO_OVERFLOW_MASK;
        end
        if (writer_drop_pulse) begin
            overflow_flags_set_comb |= TCSR_OVERFLOW_FLAGS_RING_OVERFLOW_MASK;
        end
        if (writer_malformed_pulse) begin
            overflow_flags_set_comb |= TCSR_OVERFLOW_FLAGS_MALFORMED_PACKET_MASK;
        end
        if (writer_oversized_pulse) begin
            overflow_flags_set_comb |= TCSR_OVERFLOW_FLAGS_OVERSIZED_RECORD_MASK;
        end
        if (writer_fault_rise || writer_ring_rd_reject_pulse) begin
            overflow_flags_set_comb |= TCSR_OVERFLOW_FLAGS_CDC_ERROR_MASK;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            writer_overflow_flags_seen_q <= 32'd0;
            packet_fifo_overflow_q <= 1'b0;
            writer_fault_sticky_q <= 1'b0;
        end else begin
            if (writer_transport_clear) begin
                writer_overflow_flags_seen_q <= 32'd0;
                packet_fifo_overflow_q <= 1'b0;
                writer_fault_sticky_q <= 1'b0;
            end else begin
                writer_overflow_flags_seen_q <= writer_overflow_flags_set;
                packet_fifo_overflow_q <= packet_fifo_overflow_i;
                writer_fault_sticky_q <= writer_fault_sticky;
            end
        end
    end

    trecap_avmm_csr_adapter #(
        .AVMM_ADDR_W(CSR_AVMM_ADDR_W),
        .CSR_ADDR_W(CSR_ADDR_W),
        .BURSTCOUNT_W(CSR_BURSTCOUNT_W),
        .CSR_BASE_ADDR('0)
    ) u_avmm_csr_adapter (
        .clk(clk),
        .rst_n(rst_n),
        .avs_address_i(csr_avs_address_i),
        .avs_read_i(csr_avs_read_i),
        .avs_write_i(csr_avs_write_i),
        .avs_writedata_i(csr_avs_writedata_i),
        .avs_byteenable_i(csr_avs_byteenable_i),
        .avs_burstcount_i(csr_avs_burstcount_i),
        .avs_waitrequest_o(csr_avs_waitrequest_o),
        .avs_readdata_o(csr_avs_readdata_o),
        .avs_readdatavalid_o(csr_avs_readdatavalid_o),
        .avs_writeresponsevalid_o(csr_avs_writeresponsevalid_o),
        .avs_response_o(csr_avs_response_o),
        .csr_valid_o(csr_leaf_valid),
        .csr_write_o(csr_leaf_write),
        .csr_addr_o(csr_leaf_addr),
        .csr_wdata_o(csr_leaf_wdata),
        .csr_ready_i(csr_leaf_ready),
        .csr_rvalid_i(csr_leaf_rvalid),
        .csr_rdata_i(csr_leaf_rdata),
        .csr_error_i(csr_leaf_error),
        .local_reject_pulse_o(csr_adapter_local_reject_pulse),
        .busy_o()
    );

    trecap_csr_bank #(
        .CSR_ADDR_W(CSR_ADDR_W),
        .RING_SIZE_MIN_BYTES(RING_SIZE_MIN_BYTES)
    ) u_csr_bank (
        .clk(clk),
        .rst_n(rst_n),
        .external_transport_clear_i(external_transport_clear_i),
        .csr_valid_i(csr_leaf_valid),
        .csr_write_i(csr_leaf_write),
        .csr_addr_i(csr_leaf_addr),
        .csr_wdata_i(csr_leaf_wdata),
        .csr_ready_o(csr_leaf_ready),
        .csr_rvalid_o(csr_leaf_rvalid),
        .csr_rdata_o(csr_leaf_rdata),
        .csr_error_o(csr_leaf_error),
        .frame_boundary_i(frame_boundary_i),
        .source_safe_boundary_i(source_safe_boundary_i),
        .ring_rd_commit_ready_i(writer_ring_rd_commit_ready),
        .actual_source_mode_i(actual_source_mode_i),
        .source_transition_busy_i(source_transition_busy_i),
        .transport_epoch_idle_i(transport_epoch_idle_i),
        .replay_start_ready_i(replay_start_ready_i),
        .replay_request_busy_i(replay_request_busy_i),
        .replay_start_accept_pulse_i(replay_start_accept_pulse_i),
        .replay_start_reject_pulse_i(replay_start_reject_pulse_i),
        .replay_active_i(replay_active_i),
        .replay_path_busy_i(replay_path_busy_i),
        .replay_path_done_i(replay_path_done_i),
        .replay_e2e_busy_i(replay_e2e_busy_i),
        .replay_e2e_done_i(replay_e2e_done_i),
        .replay_error_i(replay_error_i),
        .replay_rearm_required_i(replay_rearm_required_i),
        .core_alive_i(core_alive_i),
        .ring_wr_ptr_i(producer_ptr_o),
        .core_frame_count_i(core_frame_count_i),
        .core_sample_count_i(core_sample_count_i),
        .writer_idle_i(writer_idle),
        .writer_busy_i(writer_busy),
        .writer_no_space_i(writer_no_space),
        .malformed_config_i(writer_malformed_config),
        .ring_full_i(writer_ring_full),
        .packet_fifo_full_i(packet_fifo_full_i),
        .ddr_wait_i(writer_ddr_wait),
        .writer_drop_active_i(writer_drop_active),
        .ring_pointers_valid_i(writer_pointers_valid),
        .dma_drop_count_i(writer_dma_drop_count),
        .dma_packet_count_i(writer_dma_packet_count),
        .packet_fifo_drop_count_i(packet_fifo_drop_count_i),
        .overflow_flags_set_i(overflow_flags_set_comb),
        .csr_command_reject_pulse_i(external_csr_reject_pulse_i |
                                    writer_ring_rd_reject_pulse),
        .csr_adapter_reject_pulse_i(csr_adapter_local_reject_pulse),
        .ctrl_o(ctrl_w),
        .ring_config_o(ring_config_w),
        .ring_rd_committed_o(csr_ring_rd_committed),
        .ring_rd_commit_pending_o(csr_ring_rd_commit_pending),
        .telemetry_soft_reset_pulse_o(csr_telemetry_soft_reset_pulse),
        .clear_metrics_pulse_o(csr_clear_metrics_pulse),
        .counter_clear_pulse_o(csr_counter_clear_pulse),
        .replay_start_pulse_o(csr_replay_start_pulse),
        .replay_rearm_pulse_o(csr_replay_rearm_pulse),
        .thr2_apply_pulse_o(csr_thr2_apply_pulse),
        .source_mode_apply_pulse_o(csr_source_mode_apply_pulse),
        .ring_config_commit_pulse_o(csr_ring_config_commit_pulse),
        .ring_wr_snapshot_pulse_o(csr_ring_wr_snapshot_pulse),
        .ring_rd_commit_pulse_o(csr_ring_rd_commit_pulse),
        .core_count_snapshot_pulse_o(csr_core_count_snapshot_pulse),
        .clear_sticky_flags_w1c_o(csr_clear_sticky_flags_w1c),
        .status_o(csr_status),
        .dma_status_o(csr_dma_status),
        .overflow_flags_o(csr_overflow_flags),
        .csr_command_reject_count_o(csr_command_reject_count),
        .csr_reject_pulse_o(csr_reject_pulse),
        .malformed_config_o(csr_malformed_config)
    );

    trecap_ddr_ring_writer #(
        .RECORD_DATA_W(RECORD_DATA_W),
        .RECORD_KEEP_W(RECORD_KEEP_W),
        .AVMM_ADDR_W(AVMM_ADDR_W),
        .AVMM_DATA_W(AVMM_DATA_W),
        .AVMM_BYTEEN_W(AVMM_BYTEEN_W),
        .AVMM_BURSTCOUNT_W(AVMM_BURSTCOUNT_W),
        .GUARD_BYTES(GUARD_BYTES),
        .RING_SIZE_MIN_BYTES(RING_SIZE_MIN_BYTES)
    ) u_ddr_ring_writer (
        .clk(clk),
        .rst_n(rst_n),
        .clear_i(writer_transport_clear),
        .counter_clear_i(csr_counter_clear_pulse),
        .ctrl_i(ctrl_w),
        .ring_config_i(ring_config_w),
        .ring_config_commit_pulse_i(csr_ring_config_commit_pulse),
        .ring_rd_commit_valid_i(csr_ring_rd_commit_pulse),
        .ring_rd_commit_ptr_i(csr_ring_rd_committed),
        .ring_rd_commit_ready_o(writer_ring_rd_commit_ready),
        .ring_rd_accept_pulse_o(writer_ring_rd_accept_pulse),
        .ring_rd_reject_pulse_o(writer_ring_rd_reject_pulse),
        .ring_wr_snapshot_req_i(csr_ring_wr_snapshot_pulse),
        .ring_wr_snapshot_o(writer_ring_wr_snapshot),
        .ring_wr_snapshot_valid_o(writer_ring_wr_snapshot_valid),
        .ring_wr_snapshot_pulse_o(writer_ring_wr_snapshot_pulse),
        .packet_fifo_full_i(packet_fifo_full_i),
        .record_valid_i(record_valid_i),
        .record_ready_o(record_ready_o),
        .record_meta_i(record_meta_i),
        .record_payload_data_i(record_payload_data_i),
        .record_payload_keep_i(record_payload_keep_i),
        .record_payload_last_i(record_payload_last_i),
        .avm_address_o(avm_address_o),
        .avm_write_o(avm_write_o),
        .avm_writedata_o(avm_writedata_o),
        .avm_byteenable_o(avm_byteenable_o),
        .avm_burstcount_o(avm_burstcount_o),
        .avm_waitrequest_i(avm_waitrequest_i),
        .avm_writeresponsevalid_i(avm_writeresponsevalid_i),
        .avm_response_i(avm_response_i),
        .producer_ptr_o(producer_ptr_o),
        .consumer_ptr_o(consumer_ptr_o),
        .sequence_o(sequence_o),
        .used_bytes_o(used_bytes_o),
        .free_bytes_o(free_bytes_o),
        .current_offset_o(current_offset_o),
        .current_tail_bytes_o(current_tail_bytes_o),
        .writer_idle_o(writer_idle),
        .writer_busy_o(writer_busy),
        .writer_no_space_o(writer_no_space),
        .malformed_config_o(writer_malformed_config),
        .ring_full_o(writer_ring_full),
        .ddr_wait_o(writer_ddr_wait),
        .drop_active_o(writer_drop_active),
        .ring_configured_o(writer_ring_configured),
        .pointers_valid_o(writer_pointers_valid),
        .writer_fault_sticky_o(writer_fault_sticky),
        .dma_drop_count_o(writer_dma_drop_count),
        .dma_packet_count_o(writer_dma_packet_count),
        .overflow_flags_set_o(writer_overflow_flags_set),
        .normal_commit_pulse_o(writer_normal_commit_pulse),
        .wrap_commit_pulse_o(writer_wrap_commit_pulse),
        .drop_pulse_o(writer_drop_pulse),
        .malformed_pulse_o(writer_malformed_pulse),
        .oversized_pulse_o(writer_oversized_pulse)
    );

    assign ctrl_o = ctrl_w;
    assign ring_config_o = ring_config_w;

    assign telemetry_soft_reset_pulse_o = csr_telemetry_soft_reset_pulse;
    assign clear_metrics_pulse_o = csr_clear_metrics_pulse;
    assign counter_clear_pulse_o = csr_counter_clear_pulse;
    assign replay_start_pulse_o = csr_replay_start_pulse;
    assign replay_rearm_pulse_o = csr_replay_rearm_pulse;
    assign thr2_apply_pulse_o = csr_thr2_apply_pulse;
    assign source_mode_apply_pulse_o = csr_source_mode_apply_pulse;
    assign clear_sticky_flags_w1c_o = csr_clear_sticky_flags_w1c;

    assign ring_config_commit_pulse_o = csr_ring_config_commit_pulse;
    assign ring_wr_snapshot_req_pulse_o = csr_ring_wr_snapshot_pulse;
    assign ring_rd_commit_req_pulse_o = csr_ring_rd_commit_pulse;
    assign ring_rd_accept_pulse_o = writer_ring_rd_accept_pulse;
    assign ring_rd_reject_pulse_o = writer_ring_rd_reject_pulse;
    assign core_count_snapshot_pulse_o = csr_core_count_snapshot_pulse;
    assign writer_ring_wr_snapshot_valid_o = writer_ring_wr_snapshot_valid;
    assign writer_ring_wr_snapshot_pulse_o = writer_ring_wr_snapshot_pulse;

    assign status_o = csr_status;
    assign dma_status_o = csr_dma_status;
    assign overflow_flags_o = csr_overflow_flags;
    assign csr_command_reject_count_o = csr_command_reject_count;
    assign dma_drop_count_o = writer_dma_drop_count;
    assign dma_packet_count_o = writer_dma_packet_count;

    assign writer_idle_o = writer_idle;
    assign writer_busy_o = writer_busy;
    assign writer_no_space_o = writer_no_space;
    assign malformed_config_o = csr_malformed_config || writer_malformed_config;
    assign ring_full_o = writer_ring_full;
    assign ddr_wait_o = writer_ddr_wait;
    assign drop_active_o = writer_drop_active;
    assign ring_configured_o = writer_ring_configured;
    assign pointers_valid_o = writer_pointers_valid;
    assign writer_fault_sticky_o = writer_fault_sticky;
    assign normal_commit_pulse_o = writer_normal_commit_pulse;
    assign wrap_commit_pulse_o = writer_wrap_commit_pulse;
    assign writer_drop_pulse_o = writer_drop_pulse;
    assign writer_malformed_pulse_o = writer_malformed_pulse;
    assign writer_oversized_pulse_o = writer_oversized_pulse;
    assign packet_fifo_full_status_o = packet_fifo_full_i;
    assign packet_fifo_overflow_status_o = packet_fifo_overflow_i;

    wire unused_writer_snapshot_data = |writer_ring_wr_snapshot;
    wire unused_csr_debug = csr_reject_pulse ^ csr_ring_rd_commit_pending;

`ifndef SYNTHESIS
    initial begin
        if (CSR_AVMM_ADDR_W < CSR_ADDR_W) begin
            $fatal(1, "trecap_hps_bridge_top: CSR_AVMM_ADDR_W must be >= CSR_ADDR_W");
        end
        if ((CSR_ADDR_W < 9) || (CSR_ADDR_W > 32)) begin
            $fatal(1, "trecap_hps_bridge_top: CSR_ADDR_W must be in [9, 32]");
        end
        if (CSR_BURSTCOUNT_W < 1) begin
            $fatal(1, "trecap_hps_bridge_top: CSR_BURSTCOUNT_W must be at least 1");
        end
        if ((RECORD_DATA_W < 8) || ((RECORD_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_hps_bridge_top: RECORD_DATA_W must be byte aligned");
        end
        if (RECORD_KEEP_W != ((RECORD_DATA_W + 7) / 8)) begin
            $fatal(1, "trecap_hps_bridge_top: RECORD_KEEP_W must match RECORD_DATA_W/8 rounded up");
        end
        if ((AVMM_DATA_W < 8) || ((AVMM_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_hps_bridge_top: AVMM_DATA_W must be byte aligned");
        end
        if (AVMM_BYTEEN_W != (AVMM_DATA_W / 8)) begin
            $fatal(1, "trecap_hps_bridge_top: AVMM_BYTEEN_W must match AVMM_DATA_W/8");
        end
    end
`endif

endmodule : trecap_hps_bridge_top

`default_nettype wire
