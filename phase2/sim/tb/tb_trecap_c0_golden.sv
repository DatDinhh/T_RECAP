// SPDX-License-Identifier: MIT
// File class: [1] hand-written verification RTL.
// Layer: sim/tb/
// Purpose: BRAM-replay Cut-C0 exact-artifact regression for Revision-J AC9..AC12.

`timescale 1ns/1ps
`default_nettype none

module tb_trecap_c0_golden
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_artifact_expectations_pkg::*;
();

    localparam int unsigned FINAL_STALL_CYCLES = 37;

    logic clk;
    logic rst_n;
    logic enable_i;
    logic clear_i;
    logic clear_sticky_i;
    logic clear_metrics_i;
    logic replay_start_i;

    logic y_valid_o;
    logic y_ready_i;
    trecap_sample_t y_sample_o;
    logic signed [T_SAMPLE_W-1:0] y_data_o;
    logic [63:0] y_sample_idx_o;

    trecap_core_tap_sample_t tap_sample_o;
    trecap_core_tap_frame_t tap_frame_o;
    logic tap_bin_valid_o;
    logic [63:0] tap_bin_frame_idx_o;
    logic [$clog2(T_UNIQUE_BINS)-1:0] tap_bin_idx_o;
    logic signed [T_CAN_W-1:0] tap_bin_re_o;
    logic signed [T_CAN_W-1:0] tap_bin_im_o;
    logic [T_MAG2_W-1:0] tap_bin_mag2_o;
    logic tap_bin_pre_mask_o;
    logic tap_bin_mask_o;
    logic tap_bin_eligible_o;
    logic tap_bin_last_o;

    logic [63:0] core_error_sample_count_o;
    logic [63:0] core_sum_abs_err_lo_o;
    logic [63:0] core_sum_sq_err_lo_o;
    logic [15:0] core_max_abs_err_o;
    logic core_metric_overflow_sticky_o;
    logic [31:0] core_overflow_flags_o;
    logic core_saturation_sticky_o;
    logic core_protocol_error_sticky_o;

    logic replay_start_accept_pulse_o;
    logic replay_start_reject_pulse_o;
    logic top_done_o;
    logic top_done_pulse_o;
    logic top_completion_error_sticky_o;
    logic [31:0] top_overflow_flags_o;
    logic build_contract_error_o;
    logic scoreboard_done_o;

    logic [15:0] ready_lfsr_q;
    logic final_stall_started_q;
    logic final_stall_complete_q;
    integer final_stall_remaining_q;
    integer final_stall_observed_q;
    integer start_accept_count_q;

    always #5ns clk = ~clk;

    // Ordinary output stalls use a deterministic maximal-length LFSR pattern.  The
    // final output is always held for a long directed stall before it may handshake.
    assign y_ready_i =
        (y_valid_o && (y_sample_idx_o == TEXP_NY - 1) &&
         !final_stall_complete_q) ?
        1'b0 : (ready_lfsr_q[2:0] != 3'b000);

    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ready_lfsr_q <= 16'h1ace;
            final_stall_started_q <= 1'b0;
            final_stall_complete_q <= 1'b0;
            final_stall_remaining_q <= 0;
        end else begin
            ready_lfsr_q <=
                {ready_lfsr_q[14:0],
                 ready_lfsr_q[15] ^ ready_lfsr_q[13] ^
                 ready_lfsr_q[12] ^ ready_lfsr_q[10]};

            if (!final_stall_started_q && y_valid_o &&
                (y_sample_idx_o == TEXP_NY - 1)) begin
                final_stall_started_q <= 1'b1;
                final_stall_remaining_q <= FINAL_STALL_CYCLES;
            end else if (final_stall_started_q &&
                         !final_stall_complete_q) begin
                if (final_stall_remaining_q <= 1) begin
                    final_stall_remaining_q <= 0;
                    final_stall_complete_q <= 1'b1;
                end else begin
                    final_stall_remaining_q <= final_stall_remaining_q - 1;
                end
            end
        end
    end

    trecap_core_bram_replay_top #(
        .X_MEMH_FILE(
            "artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh"
        ),
        .REPLAY_MEM_DEPTH( TEXP_NS ),
        .INPUT_SAMPLES( TEXP_NS ),
        .START_ON_RESET_RELEASE( 1'b0 ),
        .RESTART_ALLOWED_WHILE_DONE( 1'b0 )
    ) dut (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i ),
        .clear_sticky_i( clear_sticky_i ),
        .clear_metrics_i( clear_metrics_i ),
        .replay_start_i( replay_start_i ),
        .thr2_i( TEXP_THR2 ),
        .y_valid_o( y_valid_o ),
        .y_ready_i( y_ready_i ),
        .y_sample_o( y_sample_o ),
        .y_data_o( y_data_o ),
        .y_sample_idx_o( y_sample_idx_o ),
        .source_sample_o( ),
        .source_sample_valid_o( ),
        .source_sample_ready_o( ),
        .source_sample_data_o( ),
        .source_sample_idx_o( ),
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
        .frame_boundary_pulse_o( ),
        .core_alive_o( ),
        .core_busy_o( ),
        .core_sample_count_o( ),
        .core_frame_count_o( ),
        .core_error_sample_count_o( core_error_sample_count_o ),
        .core_sum_abs_err_lo_o( core_sum_abs_err_lo_o ),
        .core_sum_sq_err_lo_o( core_sum_sq_err_lo_o ),
        .core_max_abs_err_o( core_max_abs_err_o ),
        .core_metric_overflow_sticky_o( core_metric_overflow_sticky_o ),
        .core_overflow_flags_o( core_overflow_flags_o ),
        .core_saturation_sticky_o( core_saturation_sticky_o ),
        .core_protocol_error_sticky_o( core_protocol_error_sticky_o ),
        .replay_active_o( ),
        .replay_done_o( ),
        .replay_input_phase_o( ),
        .replay_flush_phase_o( ),
        .replay_analysis_flush_phase_o( ),
        .replay_tail_drain_phase_o( ),
        .replay_start_accept_pulse_o( replay_start_accept_pulse_o ),
        .replay_start_reject_pulse_o( replay_start_reject_pulse_o ),
        .replay_output_accept_pulse_o( ),
        .replay_last_sample_pulse_o( ),
        .replay_done_pulse_o( ),
        .replay_next_issue_idx_o( ),
        .replay_output_accept_count_o( ),
        .replay_configured_input_samples_o( ),
        .replay_configured_flush_samples_o( ),
        .tail_drain_active_o( ),
        .tail_drain_accept_pulse_o( ),
        .tail_drain_done_pulse_o( ),
        .wola_output_count_o( ),
        .replay_config_error_sticky_o( ),
        .replay_mem_range_error_sticky_o( ),
        .replay_overrun_sticky_o( ),
        .source_discontinuity_pulse_o( ),
        .top_alive_o( ),
        .top_busy_o( ),
        .top_done_o( top_done_o ),
        .top_done_pulse_o( top_done_pulse_o ),
        .top_output_accept_count_o( ),
        .top_expected_output_count_o( ),
        .top_completion_error_sticky_o( top_completion_error_sticky_o ),
        .top_overflow_flags_o( top_overflow_flags_o ),
        .build_contract_error_o( build_contract_error_o )
    );

    trecap_c0_golden_scoreboard scoreboard (
        .clk( clk ),
        .rst_n( rst_n ),
        .y_valid_i( y_valid_o ),
        .y_ready_i( y_ready_i ),
        .y_data_i( y_data_o ),
        .y_sample_idx_i( y_sample_idx_o ),
        .tap_sample_i( tap_sample_o ),
        .tap_frame_i( tap_frame_o ),
        .tap_bin_valid_i( tap_bin_valid_o ),
        .tap_bin_frame_idx_i( tap_bin_frame_idx_o ),
        .tap_bin_idx_i( tap_bin_idx_o ),
        .tap_bin_re_i( tap_bin_re_o ),
        .tap_bin_im_i( tap_bin_im_o ),
        .tap_bin_mag2_i( tap_bin_mag2_o ),
        .tap_bin_pre_mask_i( tap_bin_pre_mask_o ),
        .tap_bin_mask_i( tap_bin_mask_o ),
        .tap_bin_eligible_i( tap_bin_eligible_o ),
        .tap_bin_last_i( tap_bin_last_o ),
        .top_done_i( top_done_o ),
        .top_done_pulse_i( top_done_pulse_o ),
        .top_completion_error_sticky_i( top_completion_error_sticky_o ),
        .top_overflow_flags_i( top_overflow_flags_o ),
        .core_overflow_flags_i( core_overflow_flags_o ),
        .core_saturation_sticky_i( core_saturation_sticky_o ),
        .core_protocol_error_sticky_i( core_protocol_error_sticky_o ),
        .core_error_sample_count_i( core_error_sample_count_o ),
        .core_sum_abs_err_lo_i( core_sum_abs_err_lo_o ),
        .core_sum_sq_err_lo_i( core_sum_sq_err_lo_o ),
        .core_max_abs_err_i( core_max_abs_err_o ),
        .core_metric_overflow_sticky_i( core_metric_overflow_sticky_o ),
        .scoreboard_done_o( scoreboard_done_o )
    );

    initial begin : p_stimulus
        clk = 1'b0;
        rst_n = 1'b0;
        enable_i = 1'b1;
        clear_i = 1'b1;
        clear_sticky_i = 1'b0;
        clear_metrics_i = 1'b0;
        replay_start_i = 1'b0;
        final_stall_observed_q = 0;
        start_accept_count_q = 0;

        repeat (8) @(negedge clk);
        rst_n = 1'b1;
        repeat (3) @(negedge clk);
        clear_i = 1'b0;
        repeat (2) @(negedge clk);
        replay_start_i = 1'b1;
        @(negedge clk);
        replay_start_i = 1'b0;
    end

    always @(posedge clk) begin : p_test_contract
        // Observe the transaction accepted at this edge before DUT NBA updates.
        if (rst_n) begin
            if (build_contract_error_o) begin
                $fatal(1, "C0_ARTIFACT_MISMATCH generated build contract invalid");
            end
            if ((y_sample_o.valid !== y_valid_o) ||
                (y_sample_o.data !== y_data_o) ||
                (y_sample_o.sample_idx !== y_sample_idx_o)) begin
                $fatal(1, "C0_ARTIFACT_MISMATCH y struct/breakout divergence");
            end
            if (replay_start_reject_pulse_o) begin
                $fatal(1, "C0_ARTIFACT_MISMATCH replay start rejected");
            end
            if (replay_start_accept_pulse_o) begin
                start_accept_count_q = start_accept_count_q + 1;
                if (start_accept_count_q != 1) begin
                    $fatal(1, "C0_ARTIFACT_MISMATCH duplicate replay start");
                end
            end
            if (y_valid_o && !y_ready_i &&
                (y_sample_idx_o == TEXP_NY - 1)) begin
                final_stall_observed_q = final_stall_observed_q + 1;
            end
            if (top_done_pulse_o) begin
                if ((start_accept_count_q != 1) ||
                    !final_stall_started_q ||
                    !final_stall_complete_q ||
                    (final_stall_observed_q < FINAL_STALL_CYCLES)) begin
                    $fatal(
                        1,
                        "C0_ARTIFACT_MISMATCH start/final-stall coverage accept=%0d stall=%0d",
                        start_accept_count_q, final_stall_observed_q
                    );
                end
            end
        end
    end

endmodule : tb_trecap_c0_golden

`default_nettype wire
