// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL integration source.
// Layer: rtl/top/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Pin-agnostic Step-11 BRAM replay -> core -> telemetry -> DDR/HPS composition.
// Contract: Keeps the core-only replay build independent while providing one elaboration/simulation
//           boundary for the end-to-end BRAM profile. Telemetry remains a valid-only observer and
//           DDR backpressure cannot reach the mathematical core.

`default_nettype none

module trecap_bram_replay_system_top
#(
    parameter int unsigned SAMPLE_W                   = trecap_core_pkg::T_SAMPLE_W,
    parameter int unsigned L                          = trecap_core_pkg::T_FFT_L,
    parameter int unsigned P                          = trecap_core_pkg::T_FFT_P,
    parameter int unsigned BIN_IDX_W                  = (trecap_core_pkg::T_UNIQUE_BINS <= 1) ? 1 : $clog2(trecap_core_pkg::T_UNIQUE_BINS),
    parameter              X_MEMH_FILE                = "artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh",
    parameter int unsigned REPLAY_MEM_DEPTH           = 4096,
    parameter int unsigned REPLAY_INPUT_SAMPLES       = 4096,
    parameter bit          REPLAY_START_ON_RESET_RELEASE = 1'b0,
    parameter bit          REPLAY_RESTART_ALLOWED     = 1'b1,
    parameter int unsigned SAMPLE_RATE_HZ             = 48_000,
    parameter int unsigned CSR_AVMM_ADDR_W            = 21,
    parameter int unsigned CSR_ADDR_W                 = 12,
    parameter int unsigned CSR_BURSTCOUNT_W           = 1,
    parameter int unsigned PAYLOAD_DATA_W             = 32,
    parameter int unsigned PAYLOAD_KEEP_W             = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned PACKET_FIFO_RECORDS        = 8,
    parameter int unsigned PACKET_FIFO_BYTES          = trecap_packet_pkg::TPKT_UDP_MAX_BYTES,
    parameter int unsigned AVMM_ADDR_W                = 64,
    parameter int unsigned AVMM_DATA_W                = 64,
    parameter int unsigned AVMM_BYTEEN_W              = (AVMM_DATA_W + 7) / 8,
    parameter int unsigned AVMM_BURSTCOUNT_W          = 1,
    parameter int unsigned GUARD_BYTES                = trecap_csr_pkg::TCSR_RING_GUARD_BYTES_MIN,
    parameter logic [31:0] RING_SIZE_MIN_BYTES        = 32'h0010_0000,
    parameter              WINDOW_FILE                = trecap_build_pkg::TBUILD_WINDOW_QW_MEMH,
    parameter              TWIDDLE_RE_FILE            = trecap_build_pkg::TBUILD_TWIDDLE_RE_MEMH,
    parameter              TWIDDLE_IM_FILE            = trecap_build_pkg::TBUILD_TWIDDLE_IM_MEMH,
    parameter              TWIDDLE_INV_RE_FILE        = trecap_build_pkg::TBUILD_TWIDDLE_INV_RE_MEMH,
    parameter              TWIDDLE_INV_IM_FILE        = trecap_build_pkg::TBUILD_TWIDDLE_INV_IM_MEMH
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         source_tick_i,
    input  logic                         replay_start_i,
    input  logic                         status_tick_i,
    input  logic                         metrics_tick_i,

    // HPS lightweight bridge CSR agent.
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

    // FPGA-to-HPS-DDR Avalon-MM write master.
    output logic [AVMM_ADDR_W-1:0]       avm_address_o,
    output logic                         avm_write_o,
    output logic [AVMM_DATA_W-1:0]       avm_writedata_o,
    output logic [AVMM_BYTEEN_W-1:0]     avm_byteenable_o,
    output logic [AVMM_BURSTCOUNT_W-1:0] avm_burstcount_o,
    input  logic                         avm_waitrequest_i,
    input  logic                         avm_writeresponsevalid_i,
    input  logic [1:0]                   avm_response_i,

    // Artifact-facing core output. The testbench/board capture sink, never telemetry, owns ready.
    output logic                         y_valid_o,
    input  logic                         y_ready_i,
    output trecap_iface_pkg::trecap_sample_t               y_sample_o,
    output logic signed [SAMPLE_W-1:0]   y_data_o,
    output logic [63:0]                  y_sample_idx_o,

    // Layered replay status. replay_source_done_o is source-token completion;
    // replay_path_done_o is BRAM-to-core Ny/count/quiescence completion; replay_e2e_done_o is the
    // Step-11 authority after a later STATUS record is committed to the HPS-visible DDR ring.
    output logic                         replay_source_active_o,
    output logic                         replay_source_done_o,
    output logic                         replay_path_busy_o,
    output logic                         replay_path_done_o,
    output logic                         replay_path_done_pulse_o,
    output logic [63:0]                  replay_source_accept_count_o,
    output logic [63:0]                  replay_core_output_accept_count_o,
    output logic [63:0]                  replay_expected_output_count_o,
    output logic                         replay_completion_error_sticky_o,
    output logic                         replay_e2e_busy_o,
    output logic                         replay_e2e_done_o,
    output logic                         replay_e2e_done_pulse_o,
    output logic                         replay_e2e_error_sticky_o,

    output logic [63:0]                  core_sample_count_o,
    output logic [63:0]                  core_frame_count_o,
    output logic [63:0]                  core_error_sample_count_o,
    output logic [31:0]                  core_overflow_flags_o,
    output logic                         core_protocol_error_sticky_o,
    output logic                         source_fault_sticky_o,
    output logic                         build_contract_error_o,

    // HPS-visible transport observations.
    output trecap_iface_pkg::trecap_hps_bridge_ctrl_t      ctrl_o,
    output trecap_iface_pkg::trecap_ring_config_t          ring_config_o,
    output logic [31:0]                  status_o,
    output logic [31:0]                  dma_status_o,
    output logic [31:0]                  overflow_flags_o,
    output logic [31:0]                  packet_fifo_drop_count_o,
    output logic [31:0]                  dma_drop_count_o,
    output logic [31:0]                  dma_packet_count_o,
    output logic [63:0]                  producer_ptr_o,
    output logic [63:0]                  consumer_ptr_o,
    output logic [31:0]                  sequence_o,
    output logic                         ring_configured_o,
    output logic                         writer_busy_o,
    output logic                         normal_commit_pulse_o,
    output logic                         wrap_commit_pulse_o,
    output logic                         full_path_alive_o
);
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;


    localparam logic [31:0] SAMPLE_RATE_HZ_U32 = SAMPLE_RATE_HZ;
    localparam logic [1:0] REPLAY_ORIGIN_NONE = 2'd0;
    localparam logic [1:0] REPLAY_ORIGIN_KEY  = 2'd1;
    localparam logic [1:0] REPLAY_ORIGIN_CSR  = 2'd2;

    trecap_core_tap_sample_t tap_sample_w;
    trecap_core_tap_frame_t  tap_frame_w;
    logic                    tap_bin_valid_w;
    logic [63:0]             tap_bin_frame_idx_w;
    logic [BIN_IDX_W-1:0]    tap_bin_idx_w;
    logic signed [T_CAN_W-1:0] tap_bin_re_w;
    logic signed [T_CAN_W-1:0] tap_bin_im_w;
    logic [T_MAG2_W-1:0]     tap_bin_mag2_w;
    logic                    tap_bin_pre_mask_w;
    logic                    tap_bin_mask_w;
    logic                    tap_bin_eligible_w;
    logic                    tap_bin_last_w;

    logic                    core_frame_boundary_w;
    logic [991:0] source_health_w;
    logic source_health_rearm_w;
    logic                    core_config_safe_boundary_w;
    logic                    source_safe_boundary_w;
    logic                    source_discontinuity_w;
    logic                    clear_metrics_apply_pulse_w;
    logic                    core_alive_w;
    logic                    core_busy_w;
    logic [63:0]             core_sum_abs_err_lo_w;
    logic [63:0]             core_sum_sq_err_lo_w;
    logic [15:0]             core_max_abs_err_w;
    logic                    core_metric_overflow_w;
    logic                    core_saturation_w;
    trecap_source_mode_e     active_source_mode_w;
    trecap_source_mode_e     pending_source_mode_w;
    logic                    source_switch_pending_w;
    logic                    source_switch_apply_w;

    logic                    replay_input_phase_w;
    logic                    replay_flush_phase_w;
    logic                    replay_tail_drain_phase_w;
    logic                    replay_start_accept_w;
    logic                    replay_start_reject_w;
    logic                    replay_start_ready_w;

    logic [31:0]             source_overflow_flags_set_w;
    logic                    source_csr_reject_pulse_w;
    logic                    source_fault_w;
    logic                    build_contract_error_w;

    trecap_hps_bridge_ctrl_t ctrl_w;
    trecap_ring_config_t     ring_config_w;
    logic                    telemetry_soft_reset_pulse_w;
    logic                    clear_metrics_pulse_w;
    logic                    thr2_apply_pulse_w;
    logic                    source_mode_apply_pulse_w;
    logic [31:0]             clear_sticky_flags_w1c_w;
    logic [31:0]             external_overflow_flags_set_w;
    logic                    external_csr_reject_pulse_w;

    logic                    packet_fifo_drop_pulse_w;
    logic                    packet_fifo_full_w;
    logic                    packet_fifo_overflow_w;
    logic                    scheduler_backpressure_w;
    logic                    scheduler_disabled_drop_w;
    logic                    scheduler_illegal_drop_w;
    logic [31:0]             csr_command_reject_count_w;
    logic [63:0]             used_bytes_w;
    logic [63:0]             free_bytes_w;
    logic [63:0]             current_offset_w;
    logic [63:0]             current_tail_bytes_w;
    logic                    writer_idle_w;
    logic                    writer_no_space_w;
    logic                    malformed_config_w;
    logic                    ring_full_w;
    logic                    ddr_wait_w;
    logic                    drop_active_w;
    logic                    pointers_valid_w;
    logic                    writer_fault_sticky_w;
    logic                    writer_drop_pulse_w;
    logic                    writer_malformed_pulse_w;
    logic                    writer_oversized_pulse_w;
    logic                    ring_rd_accept_pulse_w;
    logic                    ring_rd_reject_pulse_w;
    logic                    writer_ring_wr_snapshot_valid_w;
    logic                    writer_ring_wr_snapshot_pulse_w;
    logic                    packet_fifo_full_status_w;
    logic                    packet_fifo_overflow_status_w;
    logic                    packet_enable_illegal_w;
    logic                    spec_mode_illegal_w;
    logic                    spec_shift_illegal_w;
    logic                    wave_decim_illegal_w;
    logic                    telemetry_config_illegal_w;
    logic                    telemetry_active_w;
    logic                    core_tap_seen_w;
    logic                    rst_n_sync_unused_w;
    logic                    replay_start_admit_w;
    logic                    status_tick_to_transport_w;
    logic                    replay_e2e_transport_ready_w;
    logic                    replay_e2e_completion_fault_w;
    logic                    replay_e2e_transport_fault_w;
    logic                    replay_epoch_clear_w;
    logic                    transport_epoch_idle_w;
    logic                    transport_epoch_idle_stable_w;
    logic                    csr_counter_clear_w;
    logic                    csr_replay_start_w;
    logic                    csr_replay_rearm_w;
    logic                    replay_error_w;
    logic                    replay_rearm_required_w;
    logic [1:0]              replay_request_origin_q;
    logic                    csr_replay_queued_q;
    logic                    csr_replay_forward_w;
    logic                    key_replay_forward_w;
    logic                    replay_owner_start_w;
    logic                    replay_owner_terminal_w;
    logic                    replay_request_busy_w;
    logic                    csr_replay_feedback_enable_w;
    logic                    csr_replay_accept_feedback_w;
    logic                    csr_replay_reject_feedback_w;
    logic                    csr_replay_abort_reject_q;

    assign ctrl_o = ctrl_w;
    assign ring_config_o = ring_config_w;
    assign source_fault_sticky_o = source_fault_w;
    assign build_contract_error_o = build_contract_error_w;
    assign external_overflow_flags_set_w = source_overflow_flags_set_w;
    assign external_csr_reject_pulse_w = source_csr_reject_pulse_w ||
                                         csr_replay_reject_feedback_w;
    // A raw request always reaches the source owner so a denied start is observable as a reject.
    // Admission requires a configured STATUS-only transport and no prior E2E epoch in flight.
    assign replay_error_w = replay_completion_error_sticky_o || replay_e2e_error_sticky_o;
    assign replay_rearm_required_w = replay_error_w;
    assign replay_start_admit_w = replay_e2e_transport_ready_w && transport_epoch_idle_w &&
                                  transport_epoch_idle_stable_w && !replay_e2e_busy_o &&
                                  !replay_rearm_required_w;
    // Preserve the frozen CSR contract: TELEMETRY_SOFT_RESET is transport-only. The explicit
    // system clear/disable inputs are the replay/core/E2E abort and rearm controls.
    assign replay_epoch_clear_w = clear_i || !enable_i || csr_replay_rearm_w;

    // Serialize manual and CSR requests through the sole replay owner. A CSR request wins an idle
    // simultaneous arbitration. If a manual request is awaiting its registered terminal pulse, one
    // CSR W1P is retained and forwarded only after that manual result has been consumed.
    assign csr_replay_forward_w = !replay_epoch_clear_w &&
                                  (replay_request_origin_q == REPLAY_ORIGIN_NONE) &&
                                  (csr_replay_queued_q || csr_replay_start_w);
    assign key_replay_forward_w = !replay_epoch_clear_w &&
                                  (replay_request_origin_q == REPLAY_ORIGIN_NONE) &&
                                  !csr_replay_forward_w && replay_start_i;
    assign replay_owner_start_w = csr_replay_forward_w || key_replay_forward_w;
    assign replay_owner_terminal_w = replay_start_accept_w || replay_start_reject_w;
    // This busy predicate must be computed entirely from pre-clear request state. Using
    // replay_owner_start_w here would feed csr_replay_rearm_w back through replay_epoch_clear_w
    // and create a combinational REARM-admission loop on a simultaneous manual request.
    assign replay_request_busy_w =
        (replay_request_origin_q != REPLAY_ORIGIN_NONE) || csr_replay_queued_q ||
        csr_replay_start_w || replay_start_i;
    // The forward term covers a combinational local reject before the registered CSR-origin tag is
    // visible. An older KEY tag always wins, so adjacent KEY feedback cannot complete a CSR result.
    assign csr_replay_feedback_enable_w =
        (replay_request_origin_q == REPLAY_ORIGIN_CSR) ||
        ((replay_request_origin_q == REPLAY_ORIGIN_NONE) && csr_replay_forward_w);
    assign csr_replay_accept_feedback_w = !replay_epoch_clear_w && replay_start_accept_w &&
                                          csr_replay_feedback_enable_w;
    assign csr_replay_reject_feedback_w =
        (!replay_epoch_clear_w && replay_start_reject_w && csr_replay_feedback_enable_w) ||
        csr_replay_abort_reject_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            replay_request_origin_q <= REPLAY_ORIGIN_NONE;
            csr_replay_queued_q <= 1'b0;
            csr_replay_abort_reject_q <= 1'b0;
        end else begin
            csr_replay_abort_reject_q <= 1'b0;
            if (replay_epoch_clear_w) begin
                // Clear is an abort boundary. Resolve any host-owned forwarded or deferred START
                // on the following clock, after the CSR bank has latched a same-cycle W1P.
                csr_replay_abort_reject_q <=
                    (replay_request_origin_q == REPLAY_ORIGIN_CSR) ||
                    csr_replay_queued_q || csr_replay_start_w;
                replay_request_origin_q <= REPLAY_ORIGIN_NONE;
                csr_replay_queued_q <= 1'b0;
            end else begin
                if (csr_replay_start_w &&
                    (replay_request_origin_q != REPLAY_ORIGIN_NONE)) begin
                    csr_replay_queued_q <= 1'b1;
                end

                unique case (replay_request_origin_q)
                    REPLAY_ORIGIN_NONE: begin
                        if (csr_replay_forward_w) begin
                            csr_replay_queued_q <= 1'b0;
                            replay_request_origin_q <= replay_owner_terminal_w ?
                                                       REPLAY_ORIGIN_NONE : REPLAY_ORIGIN_CSR;
                        end else if (key_replay_forward_w) begin
                            replay_request_origin_q <= replay_owner_terminal_w ?
                                                       REPLAY_ORIGIN_NONE : REPLAY_ORIGIN_KEY;
                        end
                    end
                    REPLAY_ORIGIN_KEY,
                    REPLAY_ORIGIN_CSR: begin
                        if (replay_owner_terminal_w) begin
                            replay_request_origin_q <= REPLAY_ORIGIN_NONE;
                        end
                    end
                    default: begin
                        replay_request_origin_q <= REPLAY_ORIGIN_NONE;
                        csr_replay_queued_q <= 1'b0;
                    end
                endcase
            end
        end
    end

    trecap_source_core_integration #(
        .SAMPLE_W(SAMPLE_W),
        .L(L),
        .P(P),
        .BIN_IDX_W(BIN_IDX_W),
        .X_MEMH_FILE(X_MEMH_FILE),
        .REPLAY_MEM_DEPTH(REPLAY_MEM_DEPTH),
        .REPLAY_INPUT_SAMPLES(REPLAY_INPUT_SAMPLES),
        .REPLAY_START_ON_RESET_RELEASE(REPLAY_START_ON_RESET_RELEASE),
        .REPLAY_RESTART_ALLOWED(REPLAY_RESTART_ALLOWED),
        .RESET_SOURCE_MODE(TSRC_BRAM_REPLAY),
        .WINDOW_FILE(WINDOW_FILE),
        .TWIDDLE_RE_FILE(TWIDDLE_RE_FILE),
        .TWIDDLE_IM_FILE(TWIDDLE_IM_FILE),
        .TWIDDLE_INV_RE_FILE(TWIDDLE_INV_RE_FILE),
        .TWIDDLE_INV_IM_FILE(TWIDDLE_INV_IM_FILE)
    ) u_source_core_integration (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i),
        .clear_i(replay_epoch_clear_w),
        .source_rearm_i(source_health_rearm_w),
        .audio_ready_i(1'b0), .audio_stopped_i(1'b1),
        .adc_ready_i(1'b0), .adc_stopped_i(1'b1),
        .live_periodic_i(1'b0), .live_sample_rate_hz_i(32'd0),
        .audio_wrapper_drop_count_i(64'd0), .adc_wrapper_drop_count_i(64'd0),
        .audio_wrapper_drop_advanced_i(1'b0), .adc_wrapper_drop_advanced_i(1'b0),
        .audio_wrapper_protocol_i(1'b0), .adc_wrapper_protocol_i(1'b0),
        .live_source_enable_o(), .source_health_o(source_health_w),
        .thr2_i(ctrl_w.thr2_active),
        .requested_source_mode_i(ctrl_w.source_mode),
        .source_mode_apply_pulse_i(source_mode_apply_pulse_w),
        .clear_metrics_pulse_i(clear_metrics_pulse_w),
        .clear_sticky_flags_w1c_i(clear_sticky_flags_w1c_w),
        .source_tick_i(source_tick_i),
        .replay_start_i(replay_owner_start_w),
        .replay_start_admit_i(replay_start_admit_w),
        .diagnostic_mode_i(3'd0),
        .diagnostic_constant_i('0),
        .diagnostic_amplitude_i('0),
        .diagnostic_period_i(32'd1),
        .audio_sample_valid_i(1'b0),
        .audio_left_i('0),
        .audio_right_i('0),
        .audio_sample_count_i(64'd0),
        .adc_sample_valid_i(1'b0),
        .adc_sample_raw_i('0),
        .adc_sample_count_i(64'd0),
        .adc_zero_code_valid_i(1'b0),
        .adc_zero_code_i('0),
        .adc_dc_block_enable_i(1'b0),
        .y_valid_o(y_valid_o),
        .y_ready_i(y_ready_i),
        .y_sample_o(y_sample_o),
        .y_data_o(y_data_o),
        .y_sample_idx_o(y_sample_idx_o),
        .tap_sample_o(tap_sample_w),
        .tap_frame_o(tap_frame_w),
        .tap_bin_valid_o(tap_bin_valid_w),
        .tap_bin_frame_idx_o(tap_bin_frame_idx_w),
        .tap_bin_idx_o(tap_bin_idx_w),
        .tap_bin_re_o(tap_bin_re_w),
        .tap_bin_im_o(tap_bin_im_w),
        .tap_bin_mag2_o(tap_bin_mag2_w),
        .tap_bin_pre_mask_o(tap_bin_pre_mask_w),
        .tap_bin_mask_o(tap_bin_mask_w),
        .tap_bin_eligible_o(tap_bin_eligible_w),
        .tap_bin_last_o(tap_bin_last_w),
        .frame_boundary_pulse_o(core_frame_boundary_w),
        .core_config_safe_boundary_o(core_config_safe_boundary_w),
        .source_safe_boundary_o(source_safe_boundary_w),
        .clear_metrics_apply_pulse_o(clear_metrics_apply_pulse_w),
        .active_source_mode_o(active_source_mode_w),
        .pending_source_mode_o(pending_source_mode_w),
        .source_switch_pending_o(source_switch_pending_w),
        .source_switch_apply_pulse_o(source_switch_apply_w),
        .source_discontinuity_pulse_o(source_discontinuity_w),
        .core_alive_o(core_alive_w),
        .core_busy_o(core_busy_w),
        .core_sample_count_o(core_sample_count_o),
        .core_frame_count_o(core_frame_count_o),
        .core_error_sample_count_o(core_error_sample_count_o),
        .core_sum_abs_err_lo_o(core_sum_abs_err_lo_w),
        .core_sum_sq_err_lo_o(core_sum_sq_err_lo_w),
        .core_max_abs_err_o(core_max_abs_err_w),
        .core_metric_overflow_sticky_o(core_metric_overflow_w),
        .core_overflow_flags_o(core_overflow_flags_o),
        .core_saturation_sticky_o(core_saturation_w),
        .core_protocol_error_sticky_o(core_protocol_error_sticky_o),
        .replay_active_o(replay_source_active_o),
        .replay_done_o(replay_source_done_o),
        .replay_input_phase_o(replay_input_phase_w),
        .replay_flush_phase_o(replay_flush_phase_w),
        .replay_tail_drain_phase_o(replay_tail_drain_phase_w),
        .replay_start_accept_pulse_o(replay_start_accept_w),
        .replay_start_reject_pulse_o(replay_start_reject_w),
        .replay_start_ready_o(replay_start_ready_w),
        .replay_output_accept_count_o(replay_source_accept_count_o),
        .replay_expected_output_count_o(replay_expected_output_count_o),
        .replay_path_busy_o(replay_path_busy_o),
        .replay_path_done_o(replay_path_done_o),
        .replay_path_done_pulse_o(replay_path_done_pulse_o),
        .replay_core_output_accept_count_o(replay_core_output_accept_count_o),
        .replay_completion_error_sticky_o(replay_completion_error_sticky_o),
        .source_fault_sticky_o(source_fault_w),
        .build_contract_error_o(build_contract_error_w),
        .external_overflow_flags_set_o(source_overflow_flags_set_w),
        .external_csr_reject_pulse_o(source_csr_reject_pulse_w)
    );

    trecap_de1soc_full_top #(
        .CSR_AVMM_ADDR_W(CSR_AVMM_ADDR_W),
        .CSR_ADDR_W(CSR_ADDR_W),
        .CSR_BURSTCOUNT_W(CSR_BURSTCOUNT_W),
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W),
        .PACKET_FIFO_RECORDS(PACKET_FIFO_RECORDS),
        .PACKET_FIFO_BYTES(PACKET_FIFO_BYTES),
        .AVMM_ADDR_W(AVMM_ADDR_W),
        .AVMM_DATA_W(AVMM_DATA_W),
        .AVMM_BYTEEN_W(AVMM_BYTEEN_W),
        .AVMM_BURSTCOUNT_W(AVMM_BURSTCOUNT_W),
        .GUARD_BYTES(GUARD_BYTES),
        .RING_SIZE_MIN_BYTES(RING_SIZE_MIN_BYTES),
        .SYNC_TOP_RESET_DEASSERTION(1'b0),
        .BIN_IDX_W(BIN_IDX_W)
    ) u_full_top (
        .clk(clk),
        .rst_n(rst_n),
        .rst_n_sync_o(rst_n_sync_unused_w),
        // An accepted replay starts a fresh transport epoch, flushing any pre-run partial record.
        .external_transport_clear_i(clear_i || !enable_i),
        // Flush only uncommitted packetizer/FIFO state; committed ring pointers are preserved.
        .external_telemetry_flush_i(replay_start_accept_w),
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
        .avm_address_o(avm_address_o),
        .avm_write_o(avm_write_o),
        .avm_writedata_o(avm_writedata_o),
        .avm_byteenable_o(avm_byteenable_o),
        .avm_burstcount_o(avm_burstcount_o),
        .avm_waitrequest_i(avm_waitrequest_i),
        .avm_writeresponsevalid_i(avm_writeresponsevalid_i),
        .avm_response_i(avm_response_i),
        .tap_sample_i(tap_sample_w),
        .tap_frame_i(tap_frame_w),
        .tap_bin_valid_i(tap_bin_valid_w),
        .tap_bin_frame_idx_i(tap_bin_frame_idx_w),
        .tap_bin_idx_i(tap_bin_idx_w),
        .tap_bin_mag2_i(tap_bin_mag2_w),
        .tap_bin_mask_i(tap_bin_mask_w),
        .tap_bin_eligible_i(tap_bin_eligible_w),
        .tap_bin_last_i(tap_bin_last_w),
        .frame_boundary_i(core_config_safe_boundary_w),
        .source_safe_boundary_i(source_safe_boundary_w),
        .source_discontinuity_i(source_discontinuity_w),
        .actual_source_mode_i(active_source_mode_w),
        .source_health_i(source_health_w),
        .source_rearm_pulse_o(source_health_rearm_w),
        .codec_fpga_grant_o(),
        .source_transition_busy_i(source_switch_pending_w || source_discontinuity_w),
        .replay_start_ready_i(replay_start_ready_w &&
                              (replay_request_origin_q == REPLAY_ORIGIN_NONE) &&
                              !csr_replay_queued_q),
        .replay_request_busy_i(replay_request_busy_w),
        .replay_start_accept_pulse_i(csr_replay_accept_feedback_w),
        .replay_start_reject_pulse_i(csr_replay_reject_feedback_w),
        .replay_active_i(replay_source_active_o),
        .replay_path_busy_i(replay_path_busy_o),
        .replay_path_done_i(replay_path_done_o),
        .replay_e2e_busy_i(replay_e2e_busy_o),
        .replay_e2e_done_i(replay_e2e_done_o),
        .replay_error_i(replay_error_w),
        .replay_rearm_required_i(replay_rearm_required_w),
        .core_alive_i(core_alive_w),
        .core_frame_count_i(core_frame_count_o),
        .core_sample_count_i(core_sample_count_o),
        .core_sum_abs_err_lo_i(core_sum_abs_err_lo_w),
        .core_sum_sq_err_lo_i(core_sum_sq_err_lo_w),
        .core_max_abs_err_i({16'd0, core_max_abs_err_w}),
        .core_metric_truncated_i(core_metric_overflow_w),
        .clear_metrics_apply_pulse_i(clear_metrics_apply_pulse_w),
        .status_tick_i(status_tick_to_transport_w),
        .metrics_tick_i(metrics_tick_i),
        .sample_rate_hz_i(SAMPLE_RATE_HZ_U32),
        .external_overflow_flags_set_i(external_overflow_flags_set_w),
        .external_csr_reject_pulse_i(external_csr_reject_pulse_w),
        .ctrl_o(ctrl_w),
        .ring_config_o(ring_config_w),
        .telemetry_soft_reset_pulse_o(telemetry_soft_reset_pulse_w),
        .clear_metrics_pulse_o(clear_metrics_pulse_w),
        .counter_clear_pulse_o(csr_counter_clear_w),
        .replay_start_pulse_o(csr_replay_start_w),
        .replay_rearm_pulse_o(csr_replay_rearm_w),
        .thr2_apply_pulse_o(thr2_apply_pulse_w),
        .source_mode_apply_pulse_o(source_mode_apply_pulse_w),
        .clear_sticky_flags_w1c_o(clear_sticky_flags_w1c_w),
        .packet_fifo_drop_count_o(packet_fifo_drop_count_o),
        .packet_fifo_drop_pulse_o(packet_fifo_drop_pulse_w),
        .packet_fifo_full_o(packet_fifo_full_w),
        .packet_fifo_overflow_o(packet_fifo_overflow_w),
        .scheduler_backpressure_o(scheduler_backpressure_w),
        .scheduler_disabled_drop_o(scheduler_disabled_drop_w),
        .scheduler_illegal_drop_o(scheduler_illegal_drop_w),
        .status_o(status_o),
        .dma_status_o(dma_status_o),
        .overflow_flags_o(overflow_flags_o),
        .csr_command_reject_count_o(csr_command_reject_count_w),
        .dma_drop_count_o(dma_drop_count_o),
        .dma_packet_count_o(dma_packet_count_o),
        .producer_ptr_o(producer_ptr_o),
        .consumer_ptr_o(consumer_ptr_o),
        .sequence_o(sequence_o),
        .used_bytes_o(used_bytes_w),
        .free_bytes_o(free_bytes_w),
        .current_offset_o(current_offset_w),
        .current_tail_bytes_o(current_tail_bytes_w),
        .writer_idle_o(writer_idle_w),
        .writer_busy_o(writer_busy_o),
        .writer_no_space_o(writer_no_space_w),
        .malformed_config_o(malformed_config_w),
        .ring_full_o(ring_full_w),
        .ddr_wait_o(ddr_wait_w),
        .drop_active_o(drop_active_w),
        .ring_configured_o(ring_configured_o),
        .pointers_valid_o(pointers_valid_w),
        .writer_fault_sticky_o(writer_fault_sticky_w),
        .normal_commit_pulse_o(normal_commit_pulse_o),
        .wrap_commit_pulse_o(wrap_commit_pulse_o),
        .writer_drop_pulse_o(writer_drop_pulse_w),
        .writer_malformed_pulse_o(writer_malformed_pulse_w),
        .writer_oversized_pulse_o(writer_oversized_pulse_w),
        .ring_rd_accept_pulse_o(ring_rd_accept_pulse_w),
        .ring_rd_reject_pulse_o(ring_rd_reject_pulse_w),
        .writer_ring_wr_snapshot_valid_o(writer_ring_wr_snapshot_valid_w),
        .writer_ring_wr_snapshot_pulse_o(writer_ring_wr_snapshot_pulse_w),
        .packet_fifo_full_status_o(packet_fifo_full_status_w),
        .packet_fifo_overflow_status_o(packet_fifo_overflow_status_w),
        .packet_enable_illegal_o(packet_enable_illegal_w),
        .spec_mode_illegal_o(spec_mode_illegal_w),
        .spec_shift_illegal_o(spec_shift_illegal_w),
        .wave_decim_illegal_o(wave_decim_illegal_w),
        .telemetry_config_illegal_o(telemetry_config_illegal_w),
        .telemetry_active_o(telemetry_active_w),
        .core_tap_seen_o(core_tap_seen_w),
        .full_path_alive_o(full_path_alive_o),
        .transport_epoch_idle_o(transport_epoch_idle_w),
        .transport_epoch_idle_stable_o(transport_epoch_idle_stable_w)
    );

    assign replay_e2e_transport_ready_w = ring_configured_o &&
        ctrl_w.telemetry_enable && ctrl_w.ring_writer_enable &&
        (ctrl_w.packet_enable == TCSR_PACKET_ENABLE_STATUS_EN_MASK) &&
        !telemetry_config_illegal_w;
    // During a replay epoch periodic STATUS requests are quiesced. The exact core-done pulse emits
    // the single post-run STATUS whose later DDR commit qualifies E2E completion.
    assign status_tick_to_transport_w = replay_path_done_pulse_o ||
        (status_tick_i && !replay_e2e_busy_o && !replay_path_busy_o &&
         !replay_start_accept_w);
    assign replay_e2e_completion_fault_w = build_contract_error_w ||
        replay_completion_error_sticky_o || core_protocol_error_sticky_o ||
        core_metric_overflow_w || (core_overflow_flags_o != 32'd0);
    // Command rejects are deliberately absent: a rejected in-flight restart is observable but
    // does not corrupt the accepted replay epoch. Only transport data-integrity faults block E2E.
    assign replay_e2e_transport_fault_w = packet_fifo_overflow_w ||
        packet_fifo_overflow_status_w || scheduler_illegal_drop_w ||
        malformed_config_w || writer_fault_sticky_w || writer_drop_pulse_w ||
        writer_malformed_pulse_w || writer_oversized_pulse_w;

    trecap_bram_replay_e2e_supervisor u_replay_e2e_supervisor (
        .clk(clk),
        .rst_n(rst_n),
        .clear_i(replay_epoch_clear_w),
        .replay_start_accept_pulse_i(replay_start_accept_w),
        .replay_path_busy_i(replay_path_busy_o),
        .replay_path_done_i(replay_path_done_o),
        .replay_path_done_pulse_i(replay_path_done_pulse_o),
        .replay_completion_error_sticky_i(replay_completion_error_sticky_o),
        .completion_fault_i(replay_e2e_completion_fault_w),
        .transport_ready_i(replay_e2e_transport_ready_w),
        .transport_clear_pulse_i(telemetry_soft_reset_pulse_w),
        .transport_fault_i(replay_e2e_transport_fault_w),
        .writer_idle_i(writer_idle_w),
        .writer_busy_i(writer_busy_o),
        .normal_commit_pulse_i(normal_commit_pulse_o),
        .producer_ptr_i(producer_ptr_o),
        .dma_packet_count_i(dma_packet_count_o),
        .dma_drop_count_i(dma_drop_count_o),
        .packet_fifo_drop_count_i(packet_fifo_drop_count_o),
        .replay_e2e_busy_o(replay_e2e_busy_o),
        .replay_e2e_done_o(replay_e2e_done_o),
        .replay_e2e_done_pulse_o(replay_e2e_done_pulse_o),
        .replay_e2e_error_sticky_o(replay_e2e_error_sticky_o)
    );

    wire unused_control_events = telemetry_soft_reset_pulse_w ^ thr2_apply_pulse_w ^
                                 replay_input_phase_w ^ replay_flush_phase_w ^
                                 replay_tail_drain_phase_w ^ replay_start_accept_w ^
                                 replay_start_reject_w ^ core_frame_boundary_w ^
                                 source_switch_apply_w ^ source_switch_pending_w ^
                                 csr_counter_clear_w ^ csr_replay_start_w ^
                                 csr_replay_rearm_w ^ replay_start_ready_w ^
                                 ^active_source_mode_w ^ ^pending_source_mode_w;
    wire unused_transport_status = packet_fifo_drop_pulse_w ^ packet_fifo_full_w ^
                                   packet_fifo_overflow_w ^ scheduler_backpressure_w ^
                                   scheduler_disabled_drop_w ^ scheduler_illegal_drop_w ^
                                   ^csr_command_reject_count_w ^ ^used_bytes_w ^ ^free_bytes_w ^
                                   ^current_offset_w ^ ^current_tail_bytes_w ^ writer_idle_w ^
                                   writer_no_space_w ^ malformed_config_w ^ ring_full_w ^ ddr_wait_w ^
                                   drop_active_w ^ pointers_valid_w ^ writer_fault_sticky_w ^
                                   writer_drop_pulse_w ^ writer_malformed_pulse_w ^
                                   writer_oversized_pulse_w ^ ring_rd_accept_pulse_w ^
                                   ring_rd_reject_pulse_w ^ writer_ring_wr_snapshot_valid_w ^
                                   writer_ring_wr_snapshot_pulse_w ^ packet_fifo_full_status_w ^
                                   packet_fifo_overflow_status_w ^ packet_enable_illegal_w ^
                                   spec_mode_illegal_w ^ spec_shift_illegal_w ^ wave_decim_illegal_w ^
                                   telemetry_config_illegal_w ^ telemetry_active_w ^ core_tap_seen_w ^
                                   rst_n_sync_unused_w ^ tap_bin_pre_mask_w ^ ^tap_bin_re_w ^
                                   ^tap_bin_im_w ^ core_busy_w ^ core_saturation_w;
    wire unused_all = unused_control_events ^ unused_transport_status;

`ifndef SYNTHESIS
    initial begin
        if (!TBUILD_CONTRACT_OK) begin
            $fatal(1, "trecap_bram_replay_system_top: generated contract sanity check failed");
        end
        if (SAMPLE_RATE_HZ == 0) begin
            $fatal(1, "trecap_bram_replay_system_top: SAMPLE_RATE_HZ must be nonzero");
        end
        if ((PAYLOAD_DATA_W % 8) != 0 || PAYLOAD_KEEP_W != (PAYLOAD_DATA_W / 8)) begin
            $fatal(1, "trecap_bram_replay_system_top: payload width/keep contract mismatch");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && !clear_i) begin
            if (replay_path_done_o &&
                (replay_completion_error_sticky_o || build_contract_error_o ||
                 core_protocol_error_sticky_o ||
                 (core_overflow_flags_o != 32'd0))) begin
                $error("trecap_bram_replay_system_top: core-path done asserted with a completion fault");
            end
        end
    end
`endif

endmodule : trecap_bram_replay_system_top

`default_nettype wire
