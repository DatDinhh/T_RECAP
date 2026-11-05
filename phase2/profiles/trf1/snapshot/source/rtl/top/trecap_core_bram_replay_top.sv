// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/top/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: BRAM-replay source plus core build variant for artifact-facing Cut C0 signoff.
// Contract: Drives the core from frozen x_in.memh artifacts and Revision-J full-tail ticks.
//           Ticks before tau_last feed the analysis scheduler; ticks from tau_last through Ny-1
//           bypass analysis and drain only the WOLA OLA ring. This top intentionally excludes
//           board pins, HPS bridge, DDR writer, Ethernet telemetry, packetizers, and dashboard.

`default_nettype none

module trecap_core_bram_replay_top
#(
    parameter int unsigned SAMPLE_W              = trecap_core_pkg::T_SAMPLE_W,
    parameter int unsigned L                     = trecap_core_pkg::T_FFT_L,
    parameter int unsigned P                     = trecap_core_pkg::T_FFT_P,
    parameter int unsigned BIN_IDX_W             = (trecap_core_pkg::T_UNIQUE_BINS <= 1) ? 1 : $clog2(trecap_core_pkg::T_UNIQUE_BINS),

    parameter              X_MEMH_FILE           = "artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh",
    parameter int unsigned REPLAY_MEM_DEPTH      = 65536,
    parameter int unsigned INPUT_SAMPLES         = 4096,
    parameter bit          START_ON_RESET_RELEASE = 1'b0,
    parameter bit          RESTART_ALLOWED_WHILE_DONE = 1'b1,

    parameter              WINDOW_FILE           = trecap_build_pkg::TBUILD_WINDOW_QW_MEMH,
    parameter              TWIDDLE_RE_FILE       = trecap_build_pkg::TBUILD_TWIDDLE_RE_MEMH,
    parameter              TWIDDLE_IM_FILE       = trecap_build_pkg::TBUILD_TWIDDLE_IM_MEMH,
    parameter              TWIDDLE_INV_RE_FILE   = trecap_build_pkg::TBUILD_TWIDDLE_INV_RE_MEMH,
    parameter              TWIDDLE_INV_IM_FILE   = trecap_build_pkg::TBUILD_TWIDDLE_INV_IM_MEMH
) (
    input  logic                         clk,
    input  logic                         rst_n,

    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,
    input  logic                         clear_metrics_i,

    input  logic                         replay_start_i,
    input  logic [trecap_core_pkg::T_MAG2_W-1:0]          thr2_i,

    output logic                         y_valid_o,
    input  logic                         y_ready_i,
    output trecap_iface_pkg::trecap_sample_t               y_sample_o,
    output logic signed [SAMPLE_W-1:0]   y_data_o,
    output logic [63:0]                  y_sample_idx_o,

    output trecap_iface_pkg::trecap_sample_t               source_sample_o,
    output logic                         source_sample_valid_o,
    output logic                         source_sample_ready_o,
    output logic signed [SAMPLE_W-1:0]   source_sample_data_o,
    output logic [63:0]                  source_sample_idx_o,

    output trecap_iface_pkg::trecap_core_tap_sample_t      tap_sample_o,
    output trecap_iface_pkg::trecap_core_tap_frame_t       tap_frame_o,
    output logic                         tap_bin_valid_o,
    output logic [63:0]                  tap_bin_frame_idx_o,
    output logic [BIN_IDX_W-1:0]         tap_bin_idx_o,
    output logic signed [trecap_core_pkg::T_CAN_W-1:0]    tap_bin_re_o,
    output logic signed [trecap_core_pkg::T_CAN_W-1:0]    tap_bin_im_o,
    output logic [trecap_core_pkg::T_MAG2_W-1:0]          tap_bin_mag2_o,
    output logic                         tap_bin_pre_mask_o,
    output logic                         tap_bin_mask_o,
    output logic                         tap_bin_eligible_o,
    output logic                         tap_bin_last_o,

    output logic                         frame_boundary_pulse_o,
    output logic                         core_alive_o,
    output logic                         core_busy_o,
    output logic [63:0]                  core_sample_count_o,
    output logic [63:0]                  core_frame_count_o,
    output logic [63:0]                  core_error_sample_count_o,
    output logic [63:0]                  core_sum_abs_err_lo_o,
    output logic [63:0]                  core_sum_sq_err_lo_o,
    output logic [15:0]                  core_max_abs_err_o,
    output logic                         core_metric_overflow_sticky_o,
    output logic [31:0]                  core_overflow_flags_o,
    output logic                         core_saturation_sticky_o,
    output logic                         core_protocol_error_sticky_o,

    output logic                         replay_active_o,
    output logic                         replay_done_o,
    output logic                         replay_input_phase_o,
    output logic                         replay_flush_phase_o,
    output logic                         replay_analysis_flush_phase_o,
    output logic                         replay_tail_drain_phase_o,
    output logic                         replay_start_accept_pulse_o,
    output logic                         replay_start_reject_pulse_o,
    output logic                         replay_output_accept_pulse_o,
    output logic                         replay_last_sample_pulse_o,
    output logic                         replay_done_pulse_o,
    output logic [63:0]                  replay_next_issue_idx_o,
    output logic [63:0]                  replay_output_accept_count_o,
    output logic [63:0]                  replay_configured_input_samples_o,
    output logic [63:0]                  replay_configured_flush_samples_o,
    output logic                         tail_drain_active_o,
    output logic                         tail_drain_accept_pulse_o,
    output logic                         tail_drain_done_pulse_o,
    output logic [63:0]                  wola_output_count_o,
    output logic                         replay_config_error_sticky_o,
    output logic                         replay_mem_range_error_sticky_o,
    output logic                         replay_overrun_sticky_o,

    output logic                         source_discontinuity_pulse_o,
    output logic                         top_alive_o,
    output logic                         top_busy_o,
    output logic                         top_done_o,
    output logic                         top_done_pulse_o,
    output logic [63:0]                  top_output_accept_count_o,
    output logic [63:0]                  top_expected_output_count_o,
    output logic                         top_completion_error_sticky_o,
    output logic [31:0]                  top_overflow_flags_o,
    output logic                         build_contract_error_o
);
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;


    // Widen before addition/multiplication so geometry never depends on 32-bit parameter
    // expression overflow.
    localparam longint unsigned INPUT_SAMPLES_U64 = longint'(INPUT_SAMPLES);
    localparam longint unsigned FULL_TAIL_NFRAMES_U64 =
        (INPUT_SAMPLES_U64 + longint'(T_FFT_L) - 64'd2) / longint'(T_HOP_H);
    localparam longint unsigned FULL_TAIL_TAU_LAST_U64 =
        FULL_TAIL_NFRAMES_U64 * longint'(T_HOP_H);
    localparam longint unsigned FULL_TAIL_OUTPUT_SAMPLES_U64 =
        FULL_TAIL_TAU_LAST_U64 + longint'(T_CUSHION_G) + longint'(T_FFT_L);
    localparam longint unsigned FULL_TAIL_FLUSH_SAMPLES_U64 =
        FULL_TAIL_OUTPUT_SAMPLES_U64 - INPUT_SAMPLES_U64;
    localparam longint unsigned FULL_TAIL_DRAIN_SAMPLES_U64 =
        longint'(T_CUSHION_G) + longint'(T_FFT_L);
    localparam int unsigned FULL_TAIL_FLUSH_SAMPLES =
        int'(FULL_TAIL_FLUSH_SAMPLES_U64);
    localparam logic [31:0] FULL_TAIL_DRAIN_SAMPLES =
        FULL_TAIL_DRAIN_SAMPLES_U64[31:0];
    localparam logic [63:0] FULL_TAIL_NFRAMES =
        FULL_TAIL_NFRAMES_U64[63:0];
    localparam logic [63:0] FULL_TAIL_TAU_LAST =
        FULL_TAIL_TAU_LAST_U64[63:0];
    localparam logic [63:0] FULL_TAIL_OUTPUT_SAMPLES =
        FULL_TAIL_OUTPUT_SAMPLES_U64[63:0];
    localparam bit LOCAL_CONFIG_VALID =
        TBUILD_CONTRACT_OK &&
        (SAMPLE_W == T_SAMPLE_W) &&
        (L == T_FFT_L) &&
        (P == T_FFT_P) &&
        (REPLAY_MEM_DEPTH != 0) &&
        (INPUT_SAMPLES != 0) &&
        (INPUT_SAMPLES <= REPLAY_MEM_DEPTH) &&
        (FULL_TAIL_TAU_LAST_U64 >= INPUT_SAMPLES_U64) &&
        (FULL_TAIL_OUTPUT_SAMPLES_U64 != 0) &&
        (FULL_TAIL_FLUSH_SAMPLES_U64 <= 64'h0000_0000_ffff_ffff) &&
        (FULL_TAIL_DRAIN_SAMPLES_U64 <= 64'h0000_0000_ffff_ffff) &&
        (FULL_TAIL_DRAIN_SAMPLES_U64 == T_DELAY_D);

    trecap_sample_t bram_sample_w;
    logic           bram_sample_valid_w;
    logic           bram_sample_ready_w;
    logic           core_sample_ready_w;
    logic           analysis_tick_valid_w;
    logic           tail_tick_valid_w;
    logic           tail_tick_ready_w;
    logic           tail_tick_last_w;
    logic signed [T_SAMPLE_W-1:0] bram_sample_data_w;
    logic [63:0]    bram_sample_idx_w;

    logic           replay_start_accept_w;
    logic           replay_start_reject_w;
    logic           replay_start_qualified_w;
    logic           top_start_allowed_w;
    logic           top_start_reject_pulse_q;
    logic           top_start_reject_sticky_q;
    logic           replay_output_accept_w;
    logic           replay_last_sample_w;
    logic           replay_done_pulse_w;
    logic           replay_config_error_w;
    logic           replay_mem_range_error_w;
    logic           replay_overrun_w;
    logic           core_source_discontinuity_w;
    logic [31:0]    replay_overflow_flags_w;
    logic           top_y_accept_w;
    logic           top_structural_busy_w;
    logic           top_completion_quiescent_w;
    logic           top_exact_counts_w;
    logic           top_core_fault_w;
    logic           top_run_inflight_q;
    logic           top_done_q;
    logic           top_done_pulse_q;
    logic [63:0]    top_output_accept_count_q;
    logic           top_completion_error_sticky_q;

    assign source_sample_o = bram_sample_w;
    assign source_sample_valid_o = bram_sample_valid_w;
    assign source_sample_ready_o = bram_sample_ready_w;
    assign source_sample_data_o = bram_sample_data_w[SAMPLE_W-1:0];
    assign source_sample_idx_o = bram_sample_idx_w;

    assign analysis_tick_valid_w = bram_sample_valid_w &&
                                   (bram_sample_idx_w < FULL_TAIL_TAU_LAST_U64);
    assign tail_tick_valid_w = bram_sample_valid_w &&
                               (bram_sample_idx_w >= FULL_TAIL_TAU_LAST_U64);
    assign tail_tick_last_w = tail_tick_valid_w &&
                              (bram_sample_idx_w ==
                               (FULL_TAIL_OUTPUT_SAMPLES_U64 - 64'd1));
    assign bram_sample_ready_w =
        (bram_sample_idx_w < FULL_TAIL_TAU_LAST_U64) ?
        core_sample_ready_w : tail_tick_ready_w;

    assign replay_analysis_flush_phase_o =
        bram_sample_valid_w &&
        (bram_sample_idx_w >= INPUT_SAMPLES_U64) &&
        (bram_sample_idx_w < FULL_TAIL_TAU_LAST_U64);
    assign replay_tail_drain_phase_o = tail_tick_valid_w;

    // A source-level done occurs when the final logical drain token is accepted. The core may
    // still hold the final WOLA/delay/output beat at that point, so a restart is legal only after
    // the top-level exact-completion state is reached.
    assign top_start_allowed_w =
        rst_n &&
        !clear_i &&
        LOCAL_CONFIG_VALID &&
        !top_structural_busy_w &&
        !top_run_inflight_q &&
        ((!replay_done_o && !top_done_q) ||
         (RESTART_ALLOWED_WHILE_DONE && top_done_q));
    assign replay_start_qualified_w = replay_start_i && top_start_allowed_w;

    assign replay_start_accept_pulse_o = replay_start_accept_w;
    assign replay_start_reject_pulse_o =
        replay_start_reject_w || top_start_reject_pulse_q;
    assign replay_output_accept_pulse_o = replay_output_accept_w;
    assign replay_last_sample_pulse_o = replay_last_sample_w;
    assign replay_done_pulse_o = replay_done_pulse_w;
    assign replay_config_error_sticky_o = replay_config_error_w;
    assign replay_mem_range_error_sticky_o = replay_mem_range_error_w;
    assign replay_overrun_sticky_o =
        replay_overrun_w || top_start_reject_sticky_q;

    // The BRAM replay source owns start/restart discontinuities. The accepted-start pulse is
    // applied to the core on the following clock, which prevents the first replay sample from
    // being accepted while core-local rings are being cleared.
    assign core_source_discontinuity_w = replay_start_accept_w;
    assign source_discontinuity_pulse_o = core_source_discontinuity_w;

    assign replay_overflow_flags_w = {29'd0,
                                      replay_overrun_sticky_o,
                                      replay_mem_range_error_w,
                                      replay_config_error_w};
    assign top_overflow_flags_o = core_overflow_flags_o | replay_overflow_flags_w;
    assign build_contract_error_o = !LOCAL_CONFIG_VALID;

    assign top_y_accept_w = y_valid_o && y_ready_i;
    assign top_structural_busy_w =
        replay_active_o || source_sample_valid_o || core_busy_o || y_valid_o;
    assign top_completion_quiescent_w =
        replay_done_o && !top_structural_busy_w;
    assign top_exact_counts_w =
        LOCAL_CONFIG_VALID &&
        (top_output_accept_count_q == FULL_TAIL_OUTPUT_SAMPLES) &&
        (replay_output_accept_count_o == FULL_TAIL_OUTPUT_SAMPLES) &&
        (wola_output_count_o == FULL_TAIL_OUTPUT_SAMPLES) &&
        (core_sample_count_o == FULL_TAIL_TAU_LAST) &&
        (core_frame_count_o == FULL_TAIL_NFRAMES) &&
        (core_error_sample_count_o == FULL_TAIL_OUTPUT_SAMPLES);
    assign top_core_fault_w =
        core_protocol_error_sticky_o ||
        core_metric_overflow_sticky_o ||
        (core_overflow_flags_o != 32'd0);

    assign top_alive_o =
        rst_n && enable_i &&
        (top_run_inflight_q || top_structural_busy_w || core_alive_o);
    assign top_busy_o =
        rst_n && (top_run_inflight_q || top_structural_busy_w);
    // Gate the visible level with structural idle so a newly accepted restart drops done
    // immediately, one cycle before its registered start-accept pulse clears top_done_q.
    assign top_done_o =
        LOCAL_CONFIG_VALID && top_done_q && !top_structural_busy_w;
    assign top_done_pulse_o = top_done_pulse_q;
    assign top_output_accept_count_o = top_output_accept_count_q;
    assign top_expected_output_count_o =
        LOCAL_CONFIG_VALID ? FULL_TAIL_OUTPUT_SAMPLES : 64'd0;
    assign top_completion_error_sticky_o =
        top_completion_error_sticky_q;

    always_ff @(posedge clk or negedge rst_n) begin : p_exact_completion
        if (!rst_n) begin
            top_start_reject_pulse_q          <= 1'b0;
            top_start_reject_sticky_q         <= 1'b0;
            top_run_inflight_q                <= 1'b0;
            top_done_q                        <= 1'b0;
            top_done_pulse_q                  <= 1'b0;
            top_output_accept_count_q         <= 64'd0;
            top_completion_error_sticky_q     <= 1'b0;
        end else begin
            top_start_reject_pulse_q <= 1'b0;
            top_done_pulse_q <= 1'b0;

            if (clear_i) begin
                // Clear dominates start. Still report a one-cycle reject so a start command
                // presented on the clear edge is never lost without accept/reject evidence.
                top_start_reject_pulse_q      <= replay_start_i;
                top_start_reject_sticky_q     <= 1'b0;
                top_run_inflight_q            <= 1'b0;
                top_done_q                    <= 1'b0;
                top_output_accept_count_q     <= 64'd0;
                top_completion_error_sticky_q <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    top_start_reject_sticky_q <= 1'b0;
                    // A completion-epoch fault participates in the done decision. Do not
                    // permit a mid-run status clear to erase an index/count violation and
                    // convert that same run into a false pass.
                    if (!top_run_inflight_q) begin
                        top_completion_error_sticky_q <= 1'b0;
                    end
                end

                if (replay_start_i && !top_start_allowed_w) begin
                    top_start_reject_pulse_q  <= 1'b1;
                    top_start_reject_sticky_q <= 1'b1;
                end

                if (replay_start_accept_w) begin
                    top_run_inflight_q            <= 1'b1;
                    top_done_q                    <= 1'b0;
                    top_output_accept_count_q     <= 64'd0;
                    top_completion_error_sticky_q <= 1'b0;
                end else begin
                    if (top_run_inflight_q && top_core_fault_w) begin
                        // Capture core faults in the completion epoch. A generic sticky clear
                        // must not be able to turn a previously faulty replay into a false PASS.
                        top_completion_error_sticky_q <= 1'b1;
                    end

                    if (top_y_accept_w) begin
                        if (!top_run_inflight_q ||
                            (top_output_accept_count_q >=
                             FULL_TAIL_OUTPUT_SAMPLES) ||
                            (y_sample_idx_o != top_output_accept_count_q)) begin
                            top_completion_error_sticky_q <= 1'b1;
                        end
                        if (top_run_inflight_q &&
                            (top_output_accept_count_q <
                             FULL_TAIL_OUTPUT_SAMPLES)) begin
                            top_output_accept_count_q <=
                                top_output_accept_count_q + 64'd1;
                        end
                    end

                    // Do not decide completion on the final handshake edge itself. Waiting for
                    // structural quiescence proves that no additional output is already in flight.
                    if (top_run_inflight_q && top_completion_quiescent_w) begin
                        if (top_exact_counts_w &&
                            !top_core_fault_w &&
                            !top_completion_error_sticky_q) begin
                            top_run_inflight_q <= 1'b0;
                            top_done_q <= 1'b1;
                            top_done_pulse_q <= 1'b1;
                        end else begin
                            // Early idle with an undercount, overcount, or mismatched stage count
                            // is a terminal run error. Keep busy asserted until reset/clear_i.
                            top_completion_error_sticky_q <= 1'b1;
                        end
                    end

                    // Any post-completion activity that is not the accepted-restart branch above
                    // invalidates the exact completion claim.
                    if (!top_run_inflight_q && top_done_q &&
                        top_structural_busy_w) begin
                        top_done_q <= 1'b0;
                        top_completion_error_sticky_q <= 1'b1;
                    end
                end
            end
        end
    end

    trecap_bram_replay_source #(
        .INIT_FILE( X_MEMH_FILE ),
        .MEM_DEPTH( REPLAY_MEM_DEPTH ),
        .INPUT_SAMPLES( INPUT_SAMPLES ),
        .FLUSH_SAMPLES( FULL_TAIL_FLUSH_SAMPLES ),
        // Auto-start is internal to the source, so qualify the parameter here as well as
        // qualifying the explicit start input above.
        .START_ON_RESET_RELEASE( START_ON_RESET_RELEASE && LOCAL_CONFIG_VALID ),
        .RESTART_ALLOWED_WHILE_DONE( RESTART_ALLOWED_WHILE_DONE )
    ) u_bram_replay_source (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .start_i( replay_start_qualified_w ),
        .clear_i( clear_i ),
        .clear_sticky_i( clear_sticky_i ),
        .sample_ready_i( bram_sample_ready_w ),
        .sample_o( bram_sample_w ),
        .sample_valid_o( bram_sample_valid_w ),
        .sample_data_o( bram_sample_data_w ),
        .sample_idx_o( bram_sample_idx_w ),
        .active_o( replay_active_o ),
        .done_o( replay_done_o ),
        .input_phase_o( replay_input_phase_o ),
        .flush_phase_o( replay_flush_phase_o ),
        .start_accept_pulse_o( replay_start_accept_w ),
        .start_reject_pulse_o( replay_start_reject_w ),
        .output_accept_pulse_o( replay_output_accept_w ),
        .last_sample_pulse_o( replay_last_sample_w ),
        .done_pulse_o( replay_done_pulse_w ),
        .next_issue_idx_o( replay_next_issue_idx_o ),
        .output_accept_count_o( replay_output_accept_count_o ),
        .configured_input_samples_o( replay_configured_input_samples_o ),
        .configured_flush_samples_o( replay_configured_flush_samples_o ),
        .config_error_sticky_o( replay_config_error_w ),
        .mem_range_error_sticky_o( replay_mem_range_error_w ),
        .replay_overrun_sticky_o( replay_overrun_w )
    );

    trecap_core_top #(
        .SAMPLE_W( SAMPLE_W ),
        .L( L ),
        .P( P ),
        .BIN_IDX_W( BIN_IDX_W ),
        .WINDOW_FILE( WINDOW_FILE ),
        .TWIDDLE_RE_FILE( TWIDDLE_RE_FILE ),
        .TWIDDLE_IM_FILE( TWIDDLE_IM_FILE ),
        .TWIDDLE_INV_RE_FILE( TWIDDLE_INV_RE_FILE ),
        .TWIDDLE_INV_IM_FILE( TWIDDLE_INV_IM_FILE )
    ) u_core (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i ),
        .clear_sticky_i( clear_sticky_i ),
        .clear_metrics_i( clear_metrics_i | replay_start_accept_w ),
        .sample_i( bram_sample_w ),
        .sample_valid_i( analysis_tick_valid_w ),
        .sample_ready_o( core_sample_ready_w ),
        .thr2_i( thr2_i ),
        .source_discontinuity_i( core_source_discontinuity_w ),
        .finite_stream_i( 1'b1 ),
        .active_frame_count_i( FULL_TAIL_NFRAMES_U64 ),
        .tail_tick_valid_i( tail_tick_valid_w ),
        .tail_tick_ready_o( tail_tick_ready_w ),
        .tail_tick_sample_idx_i( bram_sample_idx_w ),
        .tail_tick_last_i( tail_tick_last_w ),
        .tail_tick_count_i( FULL_TAIL_DRAIN_SAMPLES ),
        .y_valid_o( y_valid_o ),
        .y_ready_i( y_ready_i ),
        .y_sample_o( y_sample_o ),
        .y_data_o( y_data_o ),
        .y_sample_idx_o( y_sample_idx_o ),
        .tap_sample_o( tap_sample_o ),
        .tap_frame_o( tap_frame_o ),
        .tap_bin_valid_o( tap_bin_valid_o ),
        .tap_bin_frame_idx_o( tap_bin_frame_idx_o ),
        .tap_bin_idx_o( tap_bin_idx_o ),
        .tap_bin_re_o( tap_bin_re_o ),
        .tap_bin_im_o( tap_bin_im_o ),
        .tap_bin_mag2_o( tap_bin_mag2_o ),
        .tap_bin_pre_mask_o( tap_bin_pre_mask_o ),
        .tap_bin_mask_o( tap_bin_mask_o ),
        .tap_bin_eligible_o( tap_bin_eligible_o ),
        .tap_bin_last_o( tap_bin_last_o ),
        .frame_boundary_pulse_o( frame_boundary_pulse_o ),
        .core_alive_o( core_alive_o ),
        .core_busy_o( core_busy_o ),
        .core_sample_count_o( core_sample_count_o ),
        .core_frame_count_o( core_frame_count_o ),
        .core_error_sample_count_o( core_error_sample_count_o ),
        .core_sum_abs_err_lo_o( core_sum_abs_err_lo_o ),
        .core_sum_sq_err_lo_o( core_sum_sq_err_lo_o ),
        .core_max_abs_err_o( core_max_abs_err_o ),
        .core_metric_overflow_sticky_o( core_metric_overflow_sticky_o ),
        .tail_drain_active_o( tail_drain_active_o ),
        .tail_drain_accept_pulse_o( tail_drain_accept_pulse_o ),
        .tail_drain_done_pulse_o( tail_drain_done_pulse_o ),
        .wola_output_count_o( wola_output_count_o ),
        .overflow_flags_o( core_overflow_flags_o ),
        .saturation_sticky_o( core_saturation_sticky_o ),
        .protocol_error_sticky_o( core_protocol_error_sticky_o )
    );

`ifndef SYNTHESIS
    initial begin
        if (!TBUILD_CONTRACT_OK) begin
            $fatal(1, "trecap_core_bram_replay_top: generated build/core/packet contract check failed");
        end
        if (SAMPLE_W != T_SAMPLE_W) begin
            $fatal(1, "trecap_core_bram_replay_top: SAMPLE_W must match generated T_SAMPLE_W");
        end
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_core_bram_replay_top: L must match generated T_FFT_L");
        end
        if (P != T_FFT_P) begin
            $fatal(1, "trecap_core_bram_replay_top: P must match generated T_FFT_P");
        end
        if (REPLAY_MEM_DEPTH == 0) begin
            $fatal(1, "trecap_core_bram_replay_top: REPLAY_MEM_DEPTH must be nonzero");
        end
        if (INPUT_SAMPLES == 0) begin
            $fatal(1, "trecap_core_bram_replay_top: INPUT_SAMPLES must be nonzero for Revision J signoff");
        end
        if (INPUT_SAMPLES > REPLAY_MEM_DEPTH) begin
            $fatal(1, "trecap_core_bram_replay_top: INPUT_SAMPLES exceeds REPLAY_MEM_DEPTH");
        end
        if (FULL_TAIL_TAU_LAST_U64 < INPUT_SAMPLES_U64) begin
            $fatal(1, "trecap_core_bram_replay_top: tau_last precedes Ns");
        end
        if (FULL_TAIL_DRAIN_SAMPLES_U64 != T_DELAY_D) begin
            $fatal(1, "trecap_core_bram_replay_top: full-tail drain must equal D");
        end
        if (FULL_TAIL_DRAIN_SAMPLES_U64 > 64'h0000_0000_ffff_ffff) begin
            $fatal(1, "trecap_core_bram_replay_top: drain geometry exceeds core port width");
        end
        if (FULL_TAIL_FLUSH_SAMPLES_U64 > 64'h0000_0000_ffff_ffff) begin
            $fatal(1, "trecap_core_bram_replay_top: flush geometry exceeds source parameter range");
        end
    end

    always_ff @(posedge clk) begin : p_sim_completion_contract
        if (rst_n && !clear_i) begin
            if (top_output_accept_count_q > FULL_TAIL_OUTPUT_SAMPLES) begin
                $error("trecap_core_bram_replay_top: public output count exceeded Ny");
            end
            if (top_done_o &&
                (!top_exact_counts_w || top_structural_busy_w ||
                 top_completion_error_sticky_q)) begin
                $error("trecap_core_bram_replay_top: done asserted without exact completion");
            end
            if (top_done_o && top_busy_o) begin
                $error("trecap_core_bram_replay_top: busy and done asserted together");
            end
        end
    end
`endif

endmodule : trecap_core_bram_replay_top

`default_nettype wire
