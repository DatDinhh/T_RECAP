// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/top/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Full logical DE1-SoC integration top for telemetry plus HPS/DDR bridge.
// Contract: Connects non-stalling core telemetry taps to the HPS bridge DDR ring writer and CSR
//           bank. It does not implement the STFT/WOLA arithmetic core, does not implement
//           Ethernet/UDP software, and does not contain board-pin or Platform Designer generated
//           HDL. Board-specific pin binding belongs under rtl/platform/de1soc/.
// Generated dependencies: trecap_core_pkg, trecap_csr_pkg, trecap_packet_pkg,
//                         trecap_iface_pkg, trecap_build_pkg.

`default_nettype none

// T-RECAP full logical top for the DE1-SoC build.
//
// Forward data path owned here:
//   valid-only core taps
//     -> rtl/telemetry/ packetizers + priority packet FIFO
//     -> rtl/hps_bridge/ CSR/status + DDR record builder + DDR ring writer
//     -> Avalon-MM-style FPGA-side DDR write-master boundary
//
// Reverse control path owned here:
//   HPS lightweight Avalon-MM CSR accesses
//     -> trecap_avmm_csr_adapter + trecap_csr_bank inside trecap_hps_bridge_top
//     -> generated control structs and safe-boundary pulses
//     -> source/core/telemetry integration outputs
//
// This module is intentionally not the final board-pin wrapper.  The implemented
// rtl/platform/de1soc/de1_soc_trecap_top.sv wrapper binds CLOCK/KEY/SW, audio/ADC pins,
// the source/core integration, and the generated Platform Designer system to this logical top.
// Keeping this file pin-agnostic prevents board-demo logic from entering rtl/core/.
module trecap_de1soc_full_top
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned CSR_AVMM_ADDR_W            = 21,
    parameter int unsigned CSR_ADDR_W                 = 12,
    parameter int unsigned CSR_BURSTCOUNT_W           = 1,
    parameter int unsigned PAYLOAD_DATA_W             = 32,
    parameter int unsigned PAYLOAD_KEEP_W             = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned PACKET_FIFO_RECORDS        = 8,
    parameter int unsigned PACKET_FIFO_BYTES          = TPKT_UDP_MAX_BYTES,
    parameter int unsigned AVMM_ADDR_W                = 64,
    parameter int unsigned AVMM_DATA_W                = 64,
    parameter int unsigned AVMM_BYTEEN_W              = (AVMM_DATA_W + 7) / 8,
    parameter int unsigned AVMM_BURSTCOUNT_W          = 1,
    parameter int unsigned GUARD_BYTES                = TCSR_RING_GUARD_BYTES_MIN,
    parameter logic [31:0] RING_SIZE_MIN_BYTES        = 32'h0010_0000,
    parameter bit          SYNC_TOP_RESET_DEASSERTION = 1'b1,
    parameter int unsigned RESET_SYNC_STAGES          = 2,
    parameter bit          CLEAR_COUNTERS_ON_SOFT_RESET = 1'b1,
    parameter int unsigned BIN_IDX_W                  = (T_UNIQUE_BINS <= 1) ? 1 : $clog2(T_UNIQUE_BINS)
) (
    input  logic                         clk,

    // Active-low top reset.  When SYNC_TOP_RESET_DEASSERTION is set, assertion may be asynchronous
    // and deassertion is synchronized locally before entering the telemetry/HPS bridge blocks.
    input  logic                         rst_n,
    output logic                         rst_n_sync_o,
    // Synchronous integration-owned transport clear. This resets telemetry, writer, and committed
    // ring pointer state without erasing CSR configuration; use only at a coordinated system epoch.
    input  logic                         external_transport_clear_i,
    // Replay-epoch formatter/FIFO flush. Unlike transport clear, this must never rewind committed
    // DDR producer/consumer pointers or sequence state.
    input  logic                         external_telemetry_flush_i,

    // HPS lightweight-aperture Avalon-MM CSR agent. Address units are bytes/symbols.
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

    // Avalon-MM-style DDR write-master boundary toward the Platform Designer HPS-visible DDR path.
    output logic [AVMM_ADDR_W-1:0]       avm_address_o,
    output logic                         avm_write_o,
    output logic [AVMM_DATA_W-1:0]       avm_writedata_o,
    output logic [AVMM_BYTEEN_W-1:0]     avm_byteenable_o,
    output logic [AVMM_BURSTCOUNT_W-1:0] avm_burstcount_o,
    input  logic                         avm_waitrequest_i,
    input  logic                         avm_writeresponsevalid_i,
    input  logic [1:0]                   avm_response_i,

    // Valid-only observation taps from the core/source integration.  This top deliberately has no
    // ready output returning to the mathematical core.
    input  trecap_core_tap_sample_t      tap_sample_i,
    input  trecap_core_tap_frame_t       tap_frame_i,
    input  logic                         tap_bin_valid_i,
    input  logic [63:0]                  tap_bin_frame_idx_i,
    input  logic [BIN_IDX_W-1:0]         tap_bin_idx_i,
    input  logic [T_MAG2_W-1:0]          tap_bin_mag2_i,
    input  logic                         tap_bin_mask_i,
    input  logic                         tap_bin_eligible_i,
    input  logic                         tap_bin_last_i,

    // Safe-boundary inputs from the source/core integration. frame_boundary_i is the dedicated
    // core-configuration boundary (true frame start or structural idle); tap_frame_i.valid is
    // observation data and must never become a late control-commit boundary. The counters and
    // metric aggregates below are authoritative core-owned state for coherent STATUS/METRICS
    // payloads; telemetry must not reconstruct them from delayed observation-tap indices.
    input  logic                         frame_boundary_i,
    input  logic                         source_safe_boundary_i,
    input  logic                         source_discontinuity_i,
    input  trecap_source_mode_e          actual_source_mode_i,
    input  logic                         source_transition_busy_i,

    // Existing replay owner feedback used by the Step-14 CSR command/result extension.
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
    input  logic                         core_alive_i,
    input  logic [63:0]                  core_frame_count_i,
    input  logic [63:0]                  core_sample_count_i,
    input  logic [63:0]                  core_sum_abs_err_lo_i,
    input  logic [63:0]                  core_sum_sq_err_lo_i,
    input  logic [31:0]                  core_max_abs_err_i,
    input  logic                         core_metric_truncated_i,
    // Exact source/core-qualified metric-epoch clear. The raw CSR W1P is exported separately to
    // the source/core owner and must not clear telemetry aggregates before this applied event.
    input  logic                         clear_metrics_apply_pulse_i,

    // Low-rate scheduler ticks generated by the platform/source integration layer.
    input  logic                         status_tick_i,
    input  logic                         metrics_tick_i,
    input  logic [31:0]                  sample_rate_hz_i,

    // Additional one-cycle new-fault/reject events already synchronized to clk. Persistent sticky
    // owner levels must be edge-detected before they cross this boundary.
    input  logic [31:0]                  external_overflow_flags_set_i,
    input  logic                         external_csr_reject_pulse_i,

    // Active controls and command/apply events exported to the source/core/platform integration.
    // clear_metrics_pulse_o is the raw accepted CSR W1P; the source/core layer may queue it and
    // returns the exact applied event through clear_metrics_apply_pulse_i above.
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
    output logic                         ring_config_commit_pulse_o,
    output logic                         ring_wr_snapshot_req_pulse_o,
    output logic                         ring_rd_commit_req_pulse_o,
    output logic                         core_count_snapshot_pulse_o,

    // Telemetry-path observability.  These are useful for LEDs, SignalTap, HPS polling, and later
    // assertions, but they are not correctness-signoff artifacts.
    output logic [31:0]                  packet_fifo_drop_count_o,
    output logic                         packet_fifo_drop_pulse_o,
    output logic                         packet_fifo_full_o,
    output logic                         packet_fifo_overflow_o,
    output logic                         scheduler_backpressure_o,
    output logic                         scheduler_disabled_drop_o,
    output logic                         scheduler_illegal_drop_o,

    // CSR/HPS bridge status mirrors and counters.
    output logic [31:0]                  status_o,
    output logic [31:0]                  dma_status_o,
    output logic [31:0]                  overflow_flags_o,
    output logic [31:0]                  csr_command_reject_count_o,
    output logic [31:0]                  dma_drop_count_o,
    output logic [31:0]                  dma_packet_count_o,
    output logic [63:0]                  producer_ptr_o,
    output logic [63:0]                  consumer_ptr_o,
    output logic [31:0]                  sequence_o,
    output logic [63:0]                  used_bytes_o,
    output logic [63:0]                  free_bytes_o,
    output logic [63:0]                  current_offset_o,
    output logic [63:0]                  current_tail_bytes_o,

    // Full-path health pins.
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
    output logic                         ring_rd_accept_pulse_o,
    output logic                         ring_rd_reject_pulse_o,
    output logic                         writer_ring_wr_snapshot_valid_o,
    output logic                         writer_ring_wr_snapshot_pulse_o,
    output logic                         packet_fifo_full_status_o,
    output logic                         packet_fifo_overflow_status_o,

    // Integration-health signals derived at this top boundary.
    output logic                         packet_enable_illegal_o,
    output logic                         spec_mode_illegal_o,
    output logic                         spec_shift_illegal_o,
    output logic                         wave_decim_illegal_o,
    output logic                         telemetry_config_illegal_o,
    output logic                         telemetry_active_o,
    output logic                         core_tap_seen_o,
    output logic                         full_path_alive_o,
    output logic                         transport_epoch_idle_o,
    // One complete prior cycle of transport-idle evidence. Replay admission uses live AND stable
    // idle so an accepted start cannot outrun the formatter-flush quiescence proof.
    output logic                         transport_epoch_idle_stable_o
);

    logic rst_n_local;

    trecap_hps_bridge_ctrl_t ctrl_w;
    trecap_ring_config_t     ring_config_w;

    trecap_record_meta_t record_meta_w;
    logic                record_valid_w;
    logic                record_ready_w;
    logic [PAYLOAD_DATA_W-1:0] record_payload_data_w;
    logic [PAYLOAD_KEEP_W-1:0] record_payload_keep_w;
    logic                record_payload_last_w;

    logic [31:0] packet_fifo_drop_count_w;
    logic        packet_fifo_drop_pulse_w;
    logic        packet_fifo_full_w;
    logic        packet_fifo_overflow_w;
    logic        scheduler_backpressure_w;
    logic        scheduler_disabled_drop_w;
    logic        scheduler_illegal_drop_w;

    logic        telemetry_soft_reset_pulse_w;
    logic        telemetry_soft_clear_w;
    logic        formatter_flush_w;
    logic        telemetry_clear_w;
    logic        clear_metrics_pulse_w;
    logic        counter_clear_pulse_w;
    logic        replay_start_pulse_w;
    logic        replay_rearm_pulse_w;
    logic        thr2_apply_pulse_w;
    logic        source_mode_apply_pulse_w;
    logic [31:0] clear_sticky_flags_w1c_w;
    logic [31:0] overflow_flags_w;
    logic [31:0] dma_drop_count_w;
    logic [31:0] dma_packet_count_w;
    logic [31:0] csr_command_reject_count_w;

    logic        frame_boundary_w;
    logic        core_alive_w;
    logic        core_tap_seen_q;
    logic        full_path_alive_q;
    logic [31:0] external_overflow_flags_set_w;
    logic        telemetry_config_illegal_prior_q;
    logic        telemetry_config_illegal_set_pulse_w;
    logic        transport_epoch_idle_q;

    generate
        if (SYNC_TOP_RESET_DEASSERTION) begin : g_sync_top_reset
            trecap_reset_sync #(
                .STAGES(RESET_SYNC_STAGES)
            ) u_reset_sync (
                .clk(clk),
                .async_rst_n(rst_n),
                .rst_n(rst_n_local)
            );
        end else begin : g_no_sync_top_reset
            assign rst_n_local = rst_n;
        end
    endgenerate

    assign rst_n_sync_o = rst_n_local;
    assign telemetry_soft_clear_w = telemetry_soft_reset_pulse_w |
                                    external_transport_clear_i;
    // Flush only an admitted replay epoch or an accepted CSR source change, and only while no
    // queued/active record can be stranded. A board-local abort may raise source_discontinuity_i
    // mid-record; observation admission is suppressed for that cycle, but the formatter/FIFO is
    // left intact until a later quiescent admitted epoch establishes the next boundary.
    assign formatter_flush_w = transport_epoch_idle_q &&
        (external_telemetry_flush_i ||
         (source_discontinuity_i && source_mode_apply_pulse_w));
    assign telemetry_clear_w = telemetry_soft_clear_w | formatter_flush_w;
    // record_valid_w covers queued FIFO output; writer_idle_o covers record-builder/AVMM state.
    // A partial packetizer that has not reached the FIFO is safely discarded by the replay flush.
    assign transport_epoch_idle_o = writer_idle_o && !record_valid_w;
    assign transport_epoch_idle_stable_o = transport_epoch_idle_q;

    // Registered proof breaks any combinational path from FIFO flush back through record_valid.
    // Command admission separately checks the live transport_epoch_idle_o in the owner hierarchy.
    always_ff @(posedge clk or negedge rst_n_local) begin
        if (!rst_n_local) begin
            transport_epoch_idle_q <= 1'b0;
        end else begin
            transport_epoch_idle_q <= transport_epoch_idle_o;
        end
    end

    assign frame_boundary_w = frame_boundary_i;
    assign core_alive_w = core_alive_i | tap_sample_i.valid | tap_frame_i.valid | tap_bin_valid_i;

    // These checks are duplicated at the integration boundary for direct SignalTap/LED visibility.
    // The CSR bank remains the authority for rejecting illegal HPS writes.
    assign packet_enable_illegal_o =
        ((ctrl_w.packet_enable & TCSR_PACKET_ENABLE_RESERVED_31_6_MASK) != 32'h0000) ||
        ((ctrl_w.packet_enable & TCSR_PACKET_ENABLE_PEAKS_EN_MASK) != 32'h0000) ||
        ((ctrl_w.packet_enable & TCSR_PACKET_ENABLE_DEBUG_EN_MASK) != 32'h0000);

    assign spec_mode_illegal_o = !((ctrl_w.spec_mode == TSPEC_DISABLED) ||
                                   (ctrl_w.spec_mode == TSPEC_SPEC64)   ||
                                   (ctrl_w.spec_mode == TSPEC_SPEC129));
    assign spec_shift_illegal_o = (int'(ctrl_w.spec_shift) > TCSR_SPEC_SHIFT_MAX);
    assign wave_decim_illegal_o = (ctrl_w.wave_decim == 16'd0);

    assign telemetry_config_illegal_o = packet_enable_illegal_o ||
                                        spec_mode_illegal_o ||
                                        spec_shift_illegal_o ||
                                        wave_decim_illegal_o;
    // Match the formatter's fail-closed admission policy: an illegal runtime configuration is
    // observable, but it is not reported as an active telemetry path.
    assign telemetry_active_o = ctrl_w.telemetry_enable && ctrl_w.ring_writer_enable &&
                                !telemetry_config_illegal_o;

    always_ff @(posedge clk or negedge rst_n_local) begin
        if (!rst_n_local) begin
            core_tap_seen_q <= 1'b0;
            full_path_alive_q <= 1'b0;
        end else begin
            if (telemetry_clear_w) begin
                core_tap_seen_q <= 1'b0;
                full_path_alive_q <= 1'b0;
            end else begin
                if (core_alive_w) begin
                    core_tap_seen_q <= 1'b1;
                end
                if (record_valid_w || normal_commit_pulse_o || wrap_commit_pulse_o || dma_packet_count_w != 32'd0) begin
                    full_path_alive_q <= 1'b1;
                end
            end
        end
    end

    assign core_tap_seen_o = core_tap_seen_q;
    assign full_path_alive_o = full_path_alive_q;

    // Configuration errors are reported as FPGA/CSR-side illegal-command NEW-FAULT events only if
    // they escape CSR validation. A persistent malformed level is edge-detected so it cannot hold
    // the CSR set interface high forever or manufacture another event after W1C. Deassertion ends
    // the fault episode and re-arms a later recurrence. Normal command rejection still belongs in
    // trecap_csr_bank/HPS code.
    assign telemetry_config_illegal_set_pulse_w =
        telemetry_config_illegal_o && !telemetry_config_illegal_prior_q;

    always_ff @(posedge clk or negedge rst_n_local) begin
        if (!rst_n_local) begin
            telemetry_config_illegal_prior_q <= 1'b0;
        end else begin
            telemetry_config_illegal_prior_q <= telemetry_config_illegal_o;
        end
    end

    always_comb begin
        external_overflow_flags_set_w = external_overflow_flags_set_i;
        if (telemetry_config_illegal_set_pulse_w) begin
            external_overflow_flags_set_w |= TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
        end
        if (scheduler_illegal_drop_w) begin
            external_overflow_flags_set_w |= TCSR_OVERFLOW_FLAGS_MALFORMED_PACKET_MASK;
        end
    end

    trecap_telemetry_top #(
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W),
        .PACKET_FIFO_RECORDS(PACKET_FIFO_RECORDS),
        .PACKET_FIFO_BYTES(PACKET_FIFO_BYTES),
        .BIN_IDX_W(BIN_IDX_W),
        .CLEAR_COUNTERS_ON_SOFT_RESET(CLEAR_COUNTERS_ON_SOFT_RESET)
    ) u_telemetry_top (
        .clk(clk),
        .rst_n(rst_n_local),
        .telemetry_soft_reset_i(telemetry_soft_clear_w),
        .formatter_flush_i(formatter_flush_w),
        .counter_clear_i(counter_clear_pulse_w),
        .observation_epoch_reset_i(source_discontinuity_i),
        // Clear telemetry aggregates on the exact event applied to the mathematical core. This
        // keeps both metric epochs aligned even when the source integration has to queue the raw
        // CSR command until a true core-safe boundary.
        .metrics_clear_i(clear_metrics_apply_pulse_i),
        .ctrl_i(ctrl_w),

        .tap_sample_i(tap_sample_i),
        .tap_frame_i(tap_frame_i),
        .tap_bin_valid_i(tap_bin_valid_i),
        .tap_bin_frame_idx_i(tap_bin_frame_idx_i),
        .tap_bin_idx_i(tap_bin_idx_i),
        .tap_bin_mag2_i(tap_bin_mag2_i),
        .tap_bin_mask_i(tap_bin_mask_i),
        .tap_bin_eligible_i(tap_bin_eligible_i),
        .tap_bin_last_i(tap_bin_last_i),

        .status_tick_i(status_tick_i),
        .metrics_tick_i(metrics_tick_i),
        .core_sample_count_i(core_sample_count_i),
        .core_frame_count_i(core_frame_count_i),
        .core_sum_abs_err_lo_i(core_sum_abs_err_lo_i),
        .core_sum_sq_err_lo_i(core_sum_sq_err_lo_i),
        .core_max_abs_err_i(core_max_abs_err_i),
        .core_metric_truncated_i(core_metric_truncated_i),
        .sample_rate_hz_i(sample_rate_hz_i),
        .overflow_flags_i(overflow_flags_w),
        .dma_drop_count_i(dma_drop_count_w),
        .dma_packet_count_i(dma_packet_count_w),
        .csr_command_reject_count_i(csr_command_reject_count_w),

        .record_valid_o(record_valid_w),
        .record_ready_i(record_ready_w),
        .record_meta_o(record_meta_w),
        .record_payload_data_o(record_payload_data_w),
        .record_payload_keep_o(record_payload_keep_w),
        .record_payload_last_o(record_payload_last_w),

        .packet_fifo_drop_count_o(packet_fifo_drop_count_w),
        .packet_fifo_drop_pulse_o(packet_fifo_drop_pulse_w),
        .packet_fifo_full_o(packet_fifo_full_w),
        .packet_fifo_overflow_o(packet_fifo_overflow_w),
        .scheduler_backpressure_o(scheduler_backpressure_w),
        .scheduler_disabled_drop_o(scheduler_disabled_drop_w),
        .scheduler_illegal_drop_o(scheduler_illegal_drop_w)
    );

    trecap_hps_bridge_top #(
        .CSR_AVMM_ADDR_W(CSR_AVMM_ADDR_W),
        .CSR_ADDR_W(CSR_ADDR_W),
        .CSR_BURSTCOUNT_W(CSR_BURSTCOUNT_W),
        .RECORD_DATA_W(PAYLOAD_DATA_W),
        .RECORD_KEEP_W(PAYLOAD_KEEP_W),
        .AVMM_ADDR_W(AVMM_ADDR_W),
        .AVMM_DATA_W(AVMM_DATA_W),
        .AVMM_BYTEEN_W(AVMM_BYTEEN_W),
        .AVMM_BURSTCOUNT_W(AVMM_BURSTCOUNT_W),
        .GUARD_BYTES(GUARD_BYTES),
        .RING_SIZE_MIN_BYTES(RING_SIZE_MIN_BYTES)
    ) u_hps_bridge_top (
        .clk(clk),
        .rst_n(rst_n_local),
        .external_transport_clear_i(external_transport_clear_i),

        .csr_avs_address_i(csr_avs_address_i),
        .csr_avs_read_i(csr_avs_read_i),
        .csr_avs_write_i(csr_avs_write_i),
        .csr_avs_writedata_i(csr_avs_writedata_i),
        .csr_avs_byteenable_i(csr_avs_byteenable_i),
        .csr_avs_burstcount_i(csr_avs_burstcount_i),
        .csr_avs_waitrequest_o(csr_avs_waitrequest_o),
        .csr_avs_readdata_o(csr_avs_readdata_o),
        .csr_avs_readdatavalid_o(csr_avs_readdatavalid_o),
        .csr_avs_writeresponsevalid_o(csr_avs_writeresponsevalid_o),
        .csr_avs_response_o(csr_avs_response_o),

        .frame_boundary_i(frame_boundary_w),
        .source_safe_boundary_i(source_safe_boundary_i),
        .actual_source_mode_i(actual_source_mode_i),
        .source_transition_busy_i(source_transition_busy_i),
        .transport_epoch_idle_i(transport_epoch_idle_o),
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
        .core_alive_i(core_alive_w),
        .core_frame_count_i(core_frame_count_i),
        .core_sample_count_i(core_sample_count_i),

        .record_valid_i(record_valid_w),
        .record_ready_o(record_ready_w),
        .record_meta_i(record_meta_w),
        .record_payload_data_i(record_payload_data_w),
        .record_payload_keep_i(record_payload_keep_w),
        .record_payload_last_i(record_payload_last_w),

        .packet_fifo_drop_count_i(packet_fifo_drop_count_w),
        .packet_fifo_drop_pulse_i(packet_fifo_drop_pulse_w),
        .packet_fifo_full_i(packet_fifo_full_w),
        .packet_fifo_overflow_i(packet_fifo_overflow_w),
        .external_overflow_flags_set_i(external_overflow_flags_set_w),
        .external_csr_reject_pulse_i(external_csr_reject_pulse_i),

        .avm_address_o(avm_address_o),
        .avm_write_o(avm_write_o),
        .avm_writedata_o(avm_writedata_o),
        .avm_byteenable_o(avm_byteenable_o),
        .avm_burstcount_o(avm_burstcount_o),
        .avm_waitrequest_i(avm_waitrequest_i),
        .avm_writeresponsevalid_i(avm_writeresponsevalid_i),
        .avm_response_i(avm_response_i),

        .ctrl_o(ctrl_w),
        .ring_config_o(ring_config_w),
        .telemetry_soft_reset_pulse_o(telemetry_soft_reset_pulse_w),
        .clear_metrics_pulse_o(clear_metrics_pulse_w),
        .counter_clear_pulse_o(counter_clear_pulse_w),
        .replay_start_pulse_o(replay_start_pulse_w),
        .replay_rearm_pulse_o(replay_rearm_pulse_w),
        .thr2_apply_pulse_o(thr2_apply_pulse_w),
        .source_mode_apply_pulse_o(source_mode_apply_pulse_w),
        .clear_sticky_flags_w1c_o(clear_sticky_flags_w1c_w),
        .ring_config_commit_pulse_o(ring_config_commit_pulse_o),
        .ring_wr_snapshot_req_pulse_o(ring_wr_snapshot_req_pulse_o),
        .ring_rd_commit_req_pulse_o(ring_rd_commit_req_pulse_o),
        .core_count_snapshot_pulse_o(core_count_snapshot_pulse_o),
        .ring_rd_accept_pulse_o(ring_rd_accept_pulse_o),
        .ring_rd_reject_pulse_o(ring_rd_reject_pulse_o),
        .writer_ring_wr_snapshot_valid_o(writer_ring_wr_snapshot_valid_o),
        .writer_ring_wr_snapshot_pulse_o(writer_ring_wr_snapshot_pulse_o),

        .status_o(status_o),
        .dma_status_o(dma_status_o),
        .overflow_flags_o(overflow_flags_w),
        .csr_command_reject_count_o(csr_command_reject_count_w),
        .dma_drop_count_o(dma_drop_count_w),
        .dma_packet_count_o(dma_packet_count_w),
        .producer_ptr_o(producer_ptr_o),
        .consumer_ptr_o(consumer_ptr_o),
        .sequence_o(sequence_o),
        .used_bytes_o(used_bytes_o),
        .free_bytes_o(free_bytes_o),
        .current_offset_o(current_offset_o),
        .current_tail_bytes_o(current_tail_bytes_o),

        .writer_idle_o(writer_idle_o),
        .writer_busy_o(writer_busy_o),
        .writer_no_space_o(writer_no_space_o),
        .malformed_config_o(malformed_config_o),
        .ring_full_o(ring_full_o),
        .ddr_wait_o(ddr_wait_o),
        .drop_active_o(drop_active_o),
        .ring_configured_o(ring_configured_o),
        .pointers_valid_o(pointers_valid_o),
        .writer_fault_sticky_o(writer_fault_sticky_o),
        .normal_commit_pulse_o(normal_commit_pulse_o),
        .wrap_commit_pulse_o(wrap_commit_pulse_o),
        .writer_drop_pulse_o(writer_drop_pulse_o),
        .writer_malformed_pulse_o(writer_malformed_pulse_o),
        .writer_oversized_pulse_o(writer_oversized_pulse_o),
        .packet_fifo_full_status_o(packet_fifo_full_status_o),
        .packet_fifo_overflow_status_o(packet_fifo_overflow_status_o)
    );

    assign ctrl_o = ctrl_w;
    assign ring_config_o = ring_config_w;
    assign telemetry_soft_reset_pulse_o = telemetry_soft_reset_pulse_w;
    assign clear_metrics_pulse_o = clear_metrics_pulse_w;
    assign counter_clear_pulse_o = counter_clear_pulse_w;
    assign replay_start_pulse_o = replay_start_pulse_w;
    assign replay_rearm_pulse_o = replay_rearm_pulse_w;
    assign thr2_apply_pulse_o = thr2_apply_pulse_w;
    assign source_mode_apply_pulse_o = source_mode_apply_pulse_w;
    assign clear_sticky_flags_w1c_o = clear_sticky_flags_w1c_w;

    assign overflow_flags_o = overflow_flags_w;
    assign csr_command_reject_count_o = csr_command_reject_count_w;
    assign dma_drop_count_o = dma_drop_count_w;
    assign dma_packet_count_o = dma_packet_count_w;

    assign packet_fifo_drop_count_o = packet_fifo_drop_count_w;
    assign packet_fifo_drop_pulse_o = packet_fifo_drop_pulse_w;
    assign packet_fifo_full_o = packet_fifo_full_w;
    assign packet_fifo_overflow_o = packet_fifo_overflow_w;
    assign scheduler_backpressure_o = scheduler_backpressure_w;
    assign scheduler_disabled_drop_o = scheduler_disabled_drop_w;
    assign scheduler_illegal_drop_o = scheduler_illegal_drop_w;

`ifndef SYNTHESIS
    initial begin
        if (!TBUILD_CONTRACT_OK) begin
            $fatal(1, "trecap_de1soc_full_top: generated contract sanity check failed");
        end
        if ((CSR_ADDR_W < 2) || (CSR_AVMM_ADDR_W < CSR_ADDR_W)) begin
            $fatal(1, "trecap_de1soc_full_top: CSR address widths violate aperture/leaf contract");
        end
        if (CSR_BURSTCOUNT_W < 1) begin
            $fatal(1, "trecap_de1soc_full_top: CSR_BURSTCOUNT_W must be at least 1");
        end
        if ((PAYLOAD_DATA_W < 8) || ((PAYLOAD_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_de1soc_full_top: PAYLOAD_DATA_W must be byte aligned");
        end
        if (PAYLOAD_KEEP_W != ((PAYLOAD_DATA_W + 7) / 8)) begin
            $fatal(1, "trecap_de1soc_full_top: PAYLOAD_KEEP_W mismatch");
        end
        if ((AVMM_DATA_W < 8) || ((AVMM_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_de1soc_full_top: AVMM_DATA_W must be byte aligned");
        end
        if (AVMM_BYTEEN_W != (AVMM_DATA_W / 8)) begin
            $fatal(1, "trecap_de1soc_full_top: AVMM_BYTEEN_W mismatch");
        end
        if (RESET_SYNC_STAGES < 2) begin
            $warning("trecap_de1soc_full_top: RESET_SYNC_STAGES below recommended minimum 2");
        end
    end

    always_ff @(posedge clk or negedge rst_n_local) begin
        if (!rst_n_local) begin
            // No simulation state.
        end else begin
            if (record_valid_w && !record_meta_w.valid) begin
                $error("trecap_de1soc_full_top: record_valid without valid metadata");
            end
            if (record_valid_w && record_meta_w.packet_type == TPKT_WRAP) begin
                $error("trecap_de1soc_full_top: telemetry layer attempted to emit WRAP; WRAP belongs to hps_bridge");
            end
            if (packet_enable_illegal_o || spec_mode_illegal_o || spec_shift_illegal_o || wave_decim_illegal_o) begin
                $warning("trecap_de1soc_full_top: illegal runtime telemetry configuration observed after CSR layer");
            end
        end
    end
`endif

endmodule : trecap_de1soc_full_top

`default_nettype wire
