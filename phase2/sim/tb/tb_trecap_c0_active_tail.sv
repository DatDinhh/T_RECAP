// SPDX-License-Identifier: MIT
// File class: [1] hand-written self-checking RTL regression.
// Purpose: Prove that Revision-J active-frame scheduling and pure WOLA tail drain are separate.

`timescale 1ns/1ps
`default_nettype none

module tb_trecap_c0_active_tail;
    import trecap_core_pkg::*;
    import trecap_iface_pkg::*;

    localparam int unsigned NS                 = 1024;
    localparam int unsigned NFRAMES            = (NS + T_FFT_L - 2) / T_HOP_H;
    localparam int unsigned TAU_LAST           = NFRAMES * T_HOP_H;
    localparam int unsigned DRAIN_SAMPLES      = T_CUSHION_G + T_FFT_L;
    localparam int unsigned NY                 = TAU_LAST + DRAIN_SAMPLES;
    localparam int unsigned TOTAL_FLUSH        = NY - NS;
    localparam int unsigned ANALYSIS_FLUSH     = TAU_LAST - NS;
    localparam int unsigned UNIQUE_EVENTS      = NFRAMES * T_UNIQUE_BINS;
    localparam int unsigned OUTPUT_STALL_MIN   = 73;
    localparam int unsigned WATCHDOG_CYCLES    = 2_000_000;
    localparam logic [T_MAG2_W-1:0] THR2_ZERO_SUPPRESS = T_MAG2_W'(4096);

    logic clk;
    logic rst_n;
    logic enable_i;
    logic clear_i;
    logic clear_sticky_i;
    logic clear_metrics_i;
    logic replay_start_i;
    logic y_ready_i;

    logic y_valid_o;
    trecap_sample_t y_sample_o;
    logic signed [T_SAMPLE_W-1:0] y_data_o;
    logic [63:0] y_sample_idx_o;

    trecap_sample_t source_sample_o;
    logic source_sample_valid_o;
    logic source_sample_ready_o;
    logic signed [T_SAMPLE_W-1:0] source_sample_data_o;
    logic [63:0] source_sample_idx_o;

    trecap_core_tap_sample_t tap_sample_o;
    trecap_core_tap_frame_t tap_frame_o;
    logic tap_bin_valid_o;
    logic [63:0] tap_bin_frame_idx_o;
    logic [$clog2(T_UNIQUE_BINS)-1:0] tap_bin_idx_o;
    logic [T_MAG2_W-1:0] tap_bin_mag2_o;
    logic tap_bin_mask_o;
    logic tap_bin_eligible_o;
    logic tap_bin_last_o;

    logic frame_boundary_pulse_o;
    logic core_alive_o;
    logic core_busy_o;
    logic [63:0] core_sample_count_o;
    logic [63:0] core_frame_count_o;
    logic [31:0] core_overflow_flags_o;
    logic core_saturation_sticky_o;
    logic core_protocol_error_sticky_o;

    logic replay_active_o;
    logic replay_done_o;
    logic replay_input_phase_o;
    logic replay_flush_phase_o;
    logic replay_analysis_flush_phase_o;
    logic replay_tail_drain_phase_o;
    logic replay_start_accept_pulse_o;
    logic replay_start_reject_pulse_o;
    logic replay_output_accept_pulse_o;
    logic replay_last_sample_pulse_o;
    logic replay_done_pulse_o;
    logic [63:0] replay_next_issue_idx_o;
    logic [63:0] replay_output_accept_count_o;
    logic [63:0] replay_configured_input_samples_o;
    logic [63:0] replay_configured_flush_samples_o;
    logic tail_drain_active_o;
    logic tail_drain_accept_pulse_o;
    logic tail_drain_done_pulse_o;
    logic [63:0] wola_output_count_o;
    logic replay_config_error_sticky_o;
    logic replay_mem_range_error_sticky_o;
    logic replay_overrun_sticky_o;
    logic source_discontinuity_pulse_o;
    logic top_alive_o;
    logic top_busy_o;
    logic top_done_o;
    logic top_done_pulse_o;
    logic [63:0] top_output_accept_count_o;
    logic [63:0] top_expected_output_count_o;
    logic top_completion_error_sticky_o;
    logic [31:0] top_overflow_flags_o;
    logic build_contract_error_o;

    longint unsigned cycle_count_q;
    longint unsigned source_accept_count_q;
    longint unsigned analysis_flush_accept_count_q;
    longint unsigned source_tail_accept_count_q;
    longint unsigned frame_boundary_count_q;
    longint unsigned frame_stats_count_q;
    longint unsigned unique_bin_count_q;
    longint unsigned y_accept_count_q;
    longint unsigned y_drain_accept_count_q;
    longint unsigned tail_accept_pulse_count_q;
    longint unsigned tail_done_pulse_count_q;
    longint unsigned replay_start_accept_count_q;
    longint unsigned clear_start_reject_count_q;
    longint unsigned inflight_start_reject_count_q;
    longint unsigned y_stall_cycle_count_q;
    longint unsigned top_done_pulse_count_q;
    longint unsigned input_ring_hidden_busy_cycles_q;
    longint unsigned fft_hidden_busy_cycles_q;
    longint unsigned ifft_hidden_busy_cycles_q;

    logic stall_started_q;
    logic stall_complete_q;
    logic final_stall_completion_guard_seen_q;
    logic run_started_q;
    logic expect_clear_start_reject_i;
    logic expect_inflight_start_reject_i;
    int unsigned stall_remaining_q;

    logic prior_y_stall_q;
    logic signed [T_SAMPLE_W-1:0] prior_y_data_q;
    logic [63:0] prior_y_idx_q;
    logic [63:0] prior_core_frame_count_q;

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        rst_n = 1'b0;
        enable_i = 1'b1;
        clear_i = 1'b0;
        clear_sticky_i = 1'b0;
        clear_metrics_i = 1'b0;
        replay_start_i = 1'b0;
        expect_clear_start_reject_i = 1'b0;
        expect_inflight_start_reject_i = 1'b0;

        repeat (8) @(posedge clk);
        rst_n <= 1'b1;

        // Clear dominates a simultaneous start, but the command must produce a reject pulse
        // rather than disappearing without lifecycle evidence.
        repeat (2) @(posedge clk);
        clear_i <= 1'b1;
        replay_start_i <= 1'b1;
        expect_clear_start_reject_i <= 1'b1;
        @(posedge clk);
        clear_i <= 1'b0;
        replay_start_i <= 1'b0;
        wait (replay_start_reject_pulse_o);
        @(posedge clk);
        expect_clear_start_reject_i <= 1'b0;

        repeat (2) @(posedge clk);
        replay_start_i <= 1'b1;
        @(posedge clk);
        replay_start_i <= 1'b0;

        // A restart request while the final public output is stalled must be rejected. Clear
        // only the resulting start-reject sticky bit; the completion epoch must continue.
        wait (stall_started_q);
        expect_inflight_start_reject_i <= 1'b1;
        replay_start_i <= 1'b1;
        @(posedge clk);
        replay_start_i <= 1'b0;
        wait (replay_start_reject_pulse_o);
        clear_sticky_i <= 1'b1;
        @(posedge clk);
        clear_sticky_i <= 1'b0;
        @(posedge clk);
        expect_inflight_start_reject_i <= 1'b0;
    end

    // Force backpressure exactly at the final public output. Replay and WOLA will already have
    // accepted their final internal token/beat, so only a true public-handshake completion
    // counter can keep done low through this stall.
    always_comb begin
        y_ready_i = !((!stall_started_q && y_valid_o &&
                       (y_sample_idx_o == (NY - 1))) ||
                      (stall_remaining_q != 0));
    end

    trecap_core_bram_replay_top #(
        .X_MEMH_FILE( "artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh" ),
        .REPLAY_MEM_DEPTH( 4096 ),
        .INPUT_SAMPLES( NS ),
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
        .thr2_i( THR2_ZERO_SUPPRESS ),
        .y_valid_o( y_valid_o ),
        .y_ready_i( y_ready_i ),
        .y_sample_o( y_sample_o ),
        .y_data_o( y_data_o ),
        .y_sample_idx_o( y_sample_idx_o ),
        .source_sample_o( source_sample_o ),
        .source_sample_valid_o( source_sample_valid_o ),
        .source_sample_ready_o( source_sample_ready_o ),
        .source_sample_data_o( source_sample_data_o ),
        .source_sample_idx_o( source_sample_idx_o ),
        .tap_sample_o( tap_sample_o ),
        .tap_frame_o( tap_frame_o ),
        .tap_bin_valid_o( tap_bin_valid_o ),
        .tap_bin_frame_idx_o( tap_bin_frame_idx_o ),
        .tap_bin_idx_o( tap_bin_idx_o ),
        .tap_bin_re_o( ),
        .tap_bin_im_o( ),
        .tap_bin_mag2_o( tap_bin_mag2_o ),
        .tap_bin_pre_mask_o( ),
        .tap_bin_mask_o( tap_bin_mask_o ),
        .tap_bin_eligible_o( tap_bin_eligible_o ),
        .tap_bin_last_o( tap_bin_last_o ),
        .frame_boundary_pulse_o( frame_boundary_pulse_o ),
        .core_alive_o( core_alive_o ),
        .core_busy_o( core_busy_o ),
        .core_sample_count_o( core_sample_count_o ),
        .core_frame_count_o( core_frame_count_o ),
        .core_error_sample_count_o( ),
        .core_sum_abs_err_lo_o( ),
        .core_sum_sq_err_lo_o( ),
        .core_max_abs_err_o( ),
        .core_metric_overflow_sticky_o( ),
        .core_overflow_flags_o( core_overflow_flags_o ),
        .core_saturation_sticky_o( core_saturation_sticky_o ),
        .core_protocol_error_sticky_o( core_protocol_error_sticky_o ),
        .replay_active_o( replay_active_o ),
        .replay_done_o( replay_done_o ),
        .replay_input_phase_o( replay_input_phase_o ),
        .replay_flush_phase_o( replay_flush_phase_o ),
        .replay_analysis_flush_phase_o( replay_analysis_flush_phase_o ),
        .replay_tail_drain_phase_o( replay_tail_drain_phase_o ),
        .replay_start_accept_pulse_o( replay_start_accept_pulse_o ),
        .replay_start_reject_pulse_o( replay_start_reject_pulse_o ),
        .replay_output_accept_pulse_o( replay_output_accept_pulse_o ),
        .replay_last_sample_pulse_o( replay_last_sample_pulse_o ),
        .replay_done_pulse_o( replay_done_pulse_o ),
        .replay_next_issue_idx_o( replay_next_issue_idx_o ),
        .replay_output_accept_count_o( replay_output_accept_count_o ),
        .replay_configured_input_samples_o( replay_configured_input_samples_o ),
        .replay_configured_flush_samples_o( replay_configured_flush_samples_o ),
        .tail_drain_active_o( tail_drain_active_o ),
        .tail_drain_accept_pulse_o( tail_drain_accept_pulse_o ),
        .tail_drain_done_pulse_o( tail_drain_done_pulse_o ),
        .wola_output_count_o( wola_output_count_o ),
        .replay_config_error_sticky_o( replay_config_error_sticky_o ),
        .replay_mem_range_error_sticky_o( replay_mem_range_error_sticky_o ),
        .replay_overrun_sticky_o( replay_overrun_sticky_o ),
        .source_discontinuity_pulse_o( source_discontinuity_pulse_o ),
        .top_alive_o( top_alive_o ),
        .top_busy_o( top_busy_o ),
        .top_done_o( top_done_o ),
        .top_done_pulse_o( top_done_pulse_o ),
        .top_output_accept_count_o( top_output_accept_count_o ),
        .top_expected_output_count_o( top_expected_output_count_o ),
        .top_completion_error_sticky_o( top_completion_error_sticky_o ),
        .top_overflow_flags_o( top_overflow_flags_o ),
        .build_contract_error_o( build_contract_error_o )
    );

    always_ff @(posedge clk or negedge rst_n) begin : p_scoreboard
        longint unsigned expected_bin_frame;
        longint unsigned expected_bin_idx;

        if (!rst_n) begin
            cycle_count_q <= 0;
            source_accept_count_q <= 0;
            analysis_flush_accept_count_q <= 0;
            source_tail_accept_count_q <= 0;
            frame_boundary_count_q <= 0;
            frame_stats_count_q <= 0;
            unique_bin_count_q <= 0;
            y_accept_count_q <= 0;
            y_drain_accept_count_q <= 0;
            tail_accept_pulse_count_q <= 0;
            tail_done_pulse_count_q <= 0;
            replay_start_accept_count_q <= 0;
            clear_start_reject_count_q <= 0;
            inflight_start_reject_count_q <= 0;
            y_stall_cycle_count_q <= 0;
            top_done_pulse_count_q <= 0;
            input_ring_hidden_busy_cycles_q <= 0;
            fft_hidden_busy_cycles_q <= 0;
            ifft_hidden_busy_cycles_q <= 0;
            stall_started_q <= 1'b0;
            stall_complete_q <= 1'b0;
            final_stall_completion_guard_seen_q <= 1'b0;
            run_started_q <= 1'b0;
            stall_remaining_q <= 0;
            prior_y_stall_q <= 1'b0;
            prior_y_data_q <= '0;
            prior_y_idx_q <= 64'd0;
            prior_core_frame_count_q <= 64'd0;
        end else begin
            cycle_count_q <= cycle_count_q + 1;

            if (!stall_started_q && y_valid_o &&
                (y_sample_idx_o == (NY - 1))) begin
                stall_started_q <= 1'b1;
                stall_remaining_q <= OUTPUT_STALL_MIN;
            end else if (stall_remaining_q != 0) begin
                stall_remaining_q <= stall_remaining_q - 1;
                if (stall_remaining_q == 1) begin
                    stall_complete_q <= 1'b1;
                end
            end

            if (y_valid_o && !y_ready_i) begin
                y_stall_cycle_count_q <= y_stall_cycle_count_q + 1;
            end
            if (prior_y_stall_q) begin
                if (!y_valid_o || (y_data_o !== prior_y_data_q) ||
                    (y_sample_idx_o !== prior_y_idx_q)) begin
                    $fatal(1, "WOLA/delay output changed while y_ready was low");
                end
            end
            prior_y_stall_q <= y_valid_o && !y_ready_i;
            prior_y_data_q <= y_data_o;
            prior_y_idx_q <= y_sample_idx_o;

            if ($isunknown({
                source_sample_valid_o,
                source_sample_ready_o,
                y_valid_o,
                y_ready_i,
                frame_boundary_pulse_o,
                tap_frame_o.valid,
                tap_bin_valid_o,
                tail_drain_active_o,
                tail_drain_accept_pulse_o,
                tail_drain_done_pulse_o,
                core_busy_o,
                top_busy_o,
                top_done_o,
                top_done_pulse_o,
                top_output_accept_count_o,
                top_expected_output_count_o,
                top_completion_error_sticky_o
            })) begin
                $fatal(1, "active-tail control signal became X/Z");
            end

            if ((source_sample_o.valid !== source_sample_valid_o) ||
                (source_sample_o.data !== source_sample_data_o) ||
                (source_sample_o.sample_idx !== source_sample_idx_o)) begin
                $fatal(1, "source struct and breakout outputs diverged");
            end
            if ((y_sample_o.valid !== y_valid_o) ||
                (y_sample_o.data !== y_data_o) ||
                (y_sample_o.sample_idx !== y_sample_idx_o)) begin
                $fatal(1, "y struct and breakout outputs diverged");
            end

            if (replay_start_accept_pulse_o) begin
                replay_start_accept_count_q <= replay_start_accept_count_q + 1;
                run_started_q <= 1'b1;
            end
            if (replay_start_reject_pulse_o) begin
                if (expect_clear_start_reject_i) begin
                    clear_start_reject_count_q <= clear_start_reject_count_q + 1;
                end else if (expect_inflight_start_reject_i) begin
                    inflight_start_reject_count_q <=
                        inflight_start_reject_count_q + 1;
                end else begin
                    $fatal(1, "unexpected replay start rejection");
                end
            end

            if (source_sample_valid_o && source_sample_ready_o) begin
                if (source_sample_idx_o !== source_accept_count_q) begin
                    $fatal(1,
                           "source index gap/duplicate: got=%0d expected=%0d",
                           source_sample_idx_o, source_accept_count_q);
                end
                if (source_sample_data_o !== '0) begin
                    $fatal(1, "all-zero regression source became nonzero at index %0d",
                           source_sample_idx_o);
                end

                if (source_sample_idx_o < NS) begin
                    if (!replay_input_phase_o || replay_flush_phase_o ||
                        replay_analysis_flush_phase_o ||
                        replay_tail_drain_phase_o) begin
                        $fatal(1, "real-input phase classification failed at index %0d",
                               source_sample_idx_o);
                    end
                end else if (source_sample_idx_o < TAU_LAST) begin
                    if (replay_input_phase_o || !replay_flush_phase_o ||
                        !replay_analysis_flush_phase_o ||
                        replay_tail_drain_phase_o) begin
                        $fatal(1, "active-zero phase classification failed at index %0d",
                               source_sample_idx_o);
                    end
                    analysis_flush_accept_count_q <=
                        analysis_flush_accept_count_q + 1;
                end else begin
                    if (replay_input_phase_o || !replay_flush_phase_o ||
                        replay_analysis_flush_phase_o ||
                        !replay_tail_drain_phase_o) begin
                        $fatal(1, "pure-drain phase classification failed at index %0d",
                               source_sample_idx_o);
                    end
                    source_tail_accept_count_q <= source_tail_accept_count_q + 1;
                end
                source_accept_count_q <= source_accept_count_q + 1;
            end

            if (frame_boundary_pulse_o) begin
                if (frame_boundary_count_q >= NFRAMES) begin
                    $fatal(1, "dummy frame boundary observed after Nframes");
                end
                frame_boundary_count_q <= frame_boundary_count_q + 1;
            end

            if (core_frame_count_o < prior_core_frame_count_q) begin
                $fatal(1, "core frame count decreased: prior=%0d current=%0d",
                       prior_core_frame_count_q, core_frame_count_o);
            end
            if (core_frame_count_o > NFRAMES) begin
                $fatal(1, "core frame count exceeded Nframes: %0d", core_frame_count_o);
            end
            if (core_frame_count_o != prior_core_frame_count_q) begin
                if (!frame_boundary_pulse_o ||
                    (core_frame_count_o != (prior_core_frame_count_q + 64'd1))) begin
                    $fatal(1,
                           "core frame count changed without one accepted boundary: prior=%0d current=%0d boundary=%0b",
                           prior_core_frame_count_q, core_frame_count_o,
                           frame_boundary_pulse_o);
                end
            end else if (frame_boundary_pulse_o) begin
                $fatal(1, "accepted frame boundary did not increment core frame count");
            end
            prior_core_frame_count_q <= core_frame_count_o;

            if (dut.u_core.input_ring_busy_w && !core_busy_o) begin
                $fatal(1, "input-ring internal busy was missing from core_busy_o");
            end
            if (dut.u_core.analysis_busy_w && !core_busy_o) begin
                $fatal(1, "analysis internal busy was missing from core_busy_o");
            end
            if (dut.u_core.fft_busy_w && !core_busy_o) begin
                $fatal(1, "FFT internal busy was missing from core_busy_o");
            end
            if (dut.u_core.ifft_busy_w && !core_busy_o) begin
                $fatal(1, "IFFT internal busy was missing from core_busy_o");
            end
            if (dut.u_core.wola_busy_w && !core_busy_o) begin
                $fatal(1, "WOLA internal busy was missing from core_busy_o");
            end
            if (y_valid_o && !core_busy_o) begin
                $fatal(1, "held public output was missing from core_busy_o");
            end

            if (dut.u_core.input_ring_busy_w &&
                !dut.u_core.frame_sample_valid_w) begin
                input_ring_hidden_busy_cycles_q <=
                    input_ring_hidden_busy_cycles_q + 1;
            end
            if (dut.u_core.fft_busy_w &&
                !dut.u_core.window_valid_w &&
                !dut.u_core.fft_valid_w &&
                !dut.u_core.canon_valid_w) begin
                fft_hidden_busy_cycles_q <= fft_hidden_busy_cycles_q + 1;
            end
            if (dut.u_core.ifft_busy_w &&
                !dut.u_core.spec_valid_w &&
                !dut.u_core.ifft_valid_w &&
                !dut.u_core.wola_valid_w) begin
                ifft_hidden_busy_cycles_q <= ifft_hidden_busy_cycles_q + 1;
            end

            if (top_expected_output_count_o != NY) begin
                $fatal(1, "top expected output count mismatch: got=%0d expected=%0d",
                       top_expected_output_count_o, NY);
            end
            if (top_output_accept_count_o != y_accept_count_q) begin
                $fatal(1, "public output count diverged: dut=%0d scoreboard=%0d",
                       top_output_accept_count_o, y_accept_count_q);
            end
            if (top_output_accept_count_o > NY) begin
                $fatal(1, "public output count exceeded Ny");
            end

            if (run_started_q && !top_done_o && !top_busy_o) begin
                $fatal(1, "top_busy_o dropped before exact completion");
            end
            if (top_done_o) begin
                if ((top_output_accept_count_o != NY) ||
                    (replay_output_accept_count_o != NY) ||
                    (wola_output_count_o != NY) ||
                    (core_sample_count_o != TAU_LAST) ||
                    (core_frame_count_o != NFRAMES) ||
                    core_busy_o || y_valid_o || replay_active_o ||
                    source_sample_valid_o ||
                    top_completion_error_sticky_o) begin
                    $fatal(1, "top_done_o asserted without exact quiescent completion");
                end
            end
            if (top_done_pulse_o) begin
                if (!top_done_o) begin
                    $fatal(1, "top done pulse asserted without top done level");
                end
                top_done_pulse_count_q <= top_done_pulse_count_q + 1;
                run_started_q <= 1'b0;
            end

            if (y_valid_o && !y_ready_i &&
                (y_sample_idx_o == (NY - 1))) begin
                if (!replay_done_o ||
                    (replay_output_accept_count_o != NY) ||
                    (wola_output_count_o != NY) ||
                    (top_output_accept_count_o != (NY - 1)) ||
                    (core_sample_count_o != TAU_LAST) ||
                    (core_frame_count_o != NFRAMES) ||
                    !core_busy_o || !top_busy_o ||
                    top_done_o || top_done_pulse_o) begin
                    $fatal(1,
                           "exact-completion guard failed during final-output stall");
                end
                final_stall_completion_guard_seen_q <= 1'b1;
            end

            if (tap_frame_o.valid) begin
                if (tail_drain_active_o) begin
                    $fatal(1, "frame statistics updated during pure WOLA drain");
                end
                if (tap_frame_o.frame_idx !== frame_stats_count_q) begin
                    $fatal(1, "frame_stats index mismatch: got=%0d expected=%0d",
                           tap_frame_o.frame_idx, frame_stats_count_q);
                end
                if ((tap_frame_o.stats.unique_bins !== 32'd129) ||
                    (tap_frame_o.stats.unique_suppressed_bins !== 32'd128) ||
                    (tap_frame_o.stats.eligible_unique_bins !== 32'd128) ||
                    (tap_frame_o.stats.eligible_suppressed_bins !== 32'd128) ||
                    (tap_frame_o.stats.eligible_kept_mag2_lo !== 64'd0) ||
                    (tap_frame_o.stats.eligible_total_mag2_lo !== 64'd0) ||
                    tap_frame_o.stats.mag2_truncated) begin
                    $fatal(1, "zero-frame statistics mismatch at frame %0d",
                           tap_frame_o.frame_idx);
                end
                frame_stats_count_q <= frame_stats_count_q + 1;
            end

            if (tap_bin_valid_o) begin
                if (tail_drain_active_o) begin
                    $fatal(1, "bin metric event observed during pure WOLA drain");
                end
                expected_bin_frame = unique_bin_count_q / T_UNIQUE_BINS;
                expected_bin_idx = unique_bin_count_q % T_UNIQUE_BINS;
                if ((tap_bin_frame_idx_o !== expected_bin_frame) ||
                    (tap_bin_idx_o !== expected_bin_idx)) begin
                    $fatal(1,
                           "unique-bin sequence mismatch: got frame/bin=%0d/%0d expected=%0d/%0d",
                           tap_bin_frame_idx_o, tap_bin_idx_o,
                           expected_bin_frame, expected_bin_idx);
                end
                if (tap_bin_mag2_o !== '0) begin
                    $fatal(1, "zero vector produced nonzero mag2 at frame/bin=%0d/%0d",
                           tap_bin_frame_idx_o, tap_bin_idx_o);
                end
                if (expected_bin_idx == 0) begin
                    if (tap_bin_mask_o || tap_bin_eligible_o) begin
                        $fatal(1, "protected DC bin classification mismatch");
                    end
                end else if (!tap_bin_mask_o || !tap_bin_eligible_o) begin
                    $fatal(1, "eligible zero bin was not suppressed");
                end
                unique_bin_count_q <= unique_bin_count_q + 1;
            end

            if (tail_drain_accept_pulse_o) begin
                tail_accept_pulse_count_q <= tail_accept_pulse_count_q + 1;
            end
            if (tail_drain_done_pulse_o) begin
                tail_done_pulse_count_q <= tail_done_pulse_count_q + 1;
            end

            if (y_valid_o && y_ready_i) begin
                if (y_sample_idx_o !== y_accept_count_q) begin
                    $fatal(1, "y index gap/duplicate: got=%0d expected=%0d",
                           y_sample_idx_o, y_accept_count_q);
                end
                if (y_data_o !== '0) begin
                    $fatal(1, "all-zero regression produced y[%0d]=%0d",
                           y_sample_idx_o, y_data_o);
                end
                if (y_sample_idx_o >= TAU_LAST) begin
                    y_drain_accept_count_q <= y_drain_accept_count_q + 1;
                end
                y_accept_count_q <= y_accept_count_q + 1;
            end

            if (replay_config_error_sticky_o ||
                replay_mem_range_error_sticky_o ||
                (replay_overrun_sticky_o &&
                 !expect_inflight_start_reject_i)) begin
                $fatal(1, "BRAM replay source reported a configuration/protocol error");
            end
            if (core_saturation_sticky_o) begin
                $fatal(1, "all-zero regression unexpectedly saturated");
            end
            if (core_protocol_error_sticky_o) begin
                $fatal(1, "core protocol error asserted");
            end
            if (build_contract_error_o) begin
                $fatal(1, "generated build contract or finite geometry is invalid");
            end
            if (top_completion_error_sticky_o) begin
                $fatal(1, "top exact-completion guard reported a sequence/count error");
            end
        end
    end

    initial begin : p_test_control
        wait (rst_n);
        fork
            begin : p_watchdog
                repeat (WATCHDOG_CYCLES) @(posedge clk);
                $fatal(1,
                       "watchdog: source=%0d frames=%0d stats=%0d bins=%0d y=%0d tail=%0d",
                       source_accept_count_q, frame_boundary_count_q,
                       frame_stats_count_q, unique_bin_count_q,
                       y_accept_count_q, tail_accept_pulse_count_q);
            end

            begin : p_completion
                wait ((source_accept_count_q == NY) &&
                      (y_accept_count_q == NY) &&
                      (tail_done_pulse_count_q == 1) &&
                      top_done_o);
                repeat (40) @(posedge clk);

                if (source_accept_count_q != NY ||
                    replay_output_accept_count_o != NY) begin
                    $fatal(1, "replay tick conservation failed");
                end
                if (analysis_flush_accept_count_q != ANALYSIS_FLUSH) begin
                    $fatal(1, "analysis flush count mismatch: got=%0d expected=%0d",
                           analysis_flush_accept_count_q, ANALYSIS_FLUSH);
                end
                if (source_tail_accept_count_q != DRAIN_SAMPLES ||
                    tail_accept_pulse_count_q != DRAIN_SAMPLES) begin
                    $fatal(1,
                           "tail token conservation failed: source=%0d wola=%0d expected=%0d",
                           source_tail_accept_count_q, tail_accept_pulse_count_q,
                           DRAIN_SAMPLES);
                end
                if (frame_boundary_count_q != NFRAMES ||
                    frame_stats_count_q != NFRAMES) begin
                    $fatal(1, "active-frame conservation failed: boundary=%0d stats=%0d expected=%0d",
                           frame_boundary_count_q, frame_stats_count_q, NFRAMES);
                end
                if (unique_bin_count_q != UNIQUE_EVENTS) begin
                    $fatal(1, "unique-bin event count mismatch: got=%0d expected=%0d",
                           unique_bin_count_q, UNIQUE_EVENTS);
                end
                if (y_accept_count_q != NY ||
                    wola_output_count_o != NY ||
                    top_output_accept_count_o != NY ||
                    y_drain_accept_count_q != DRAIN_SAMPLES) begin
                    $fatal(1,
                           "output conservation failed: y=%0d wola=%0d top=%0d drain_y=%0d",
                           y_accept_count_q, wola_output_count_o,
                           top_output_accept_count_o,
                           y_drain_accept_count_q);
                end
                if (tail_done_pulse_count_q != 1 || tail_drain_active_o) begin
                    $fatal(1, "tail drain did not complete exactly once");
                end
                if (!stall_started_q || !stall_complete_q ||
                    (y_stall_cycle_count_q < OUTPUT_STALL_MIN) ||
                    !final_stall_completion_guard_seen_q) begin
                    $fatal(1, "directed output backpressure was not fully exercised");
                end
                if (replay_configured_input_samples_o != NS ||
                    replay_configured_flush_samples_o != TOTAL_FLUSH) begin
                    $fatal(1, "replay geometry output mismatch");
                end
                if (!replay_done_o || replay_active_o ||
                    (replay_start_accept_count_q != 1) ||
                    (clear_start_reject_count_q != 1) ||
                    (inflight_start_reject_count_q != 1)) begin
                    $fatal(1, "replay lifecycle mismatch");
                end
                if (!top_done_o || top_busy_o || core_busy_o ||
                    (top_done_pulse_count_q != 1) ||
                    (core_sample_count_o != TAU_LAST) ||
                    (core_frame_count_o != NFRAMES) ||
                    (top_expected_output_count_o != NY) ||
                    top_completion_error_sticky_o) begin
                    $fatal(1,
                           "exact top completion mismatch: done=%0b busy=%0b core_busy=%0b pulses=%0d frames=%0d count=%0d expected=%0d error=%0b",
                           top_done_o, top_busy_o, core_busy_o,
                           top_done_pulse_count_q, core_frame_count_o,
                           top_output_accept_count_o,
                           top_expected_output_count_o,
                           top_completion_error_sticky_o);
                end
                if ((input_ring_hidden_busy_cycles_q == 0) ||
                    (fft_hidden_busy_cycles_q == 0) ||
                    (ifft_hidden_busy_cycles_q == 0)) begin
                    $fatal(1,
                           "hidden busy coverage missing: ring=%0d fft=%0d ifft=%0d",
                           input_ring_hidden_busy_cycles_q,
                           fft_hidden_busy_cycles_q,
                           ifft_hidden_busy_cycles_q);
                end
                if (y_valid_o || tap_frame_o.valid || tap_bin_valid_o) begin
                    $fatal(1, "activity remained after finite-tail completion");
                end

                $display(
                    "C0_EXACT_COMPLETION_PASS frames=%0d outputs=%0d final_stall=%0d done_pulses=%0d start_rejects=%0d",
                    core_frame_count_o, top_output_accept_count_o,
                    y_stall_cycle_count_q, top_done_pulse_count_q,
                    clear_start_reject_count_q + inflight_start_reject_count_q
                );
                $display(
                    "C0_ACTIVE_TAIL_PASS Ns=%0d frames=%0d tau_last=%0d drain=%0d Ny=%0d bins=%0d cycles=%0d",
                    NS, NFRAMES, TAU_LAST, DRAIN_SAMPLES, NY,
                    unique_bin_count_q, cycle_count_q
                );
                $finish;
            end
        join_any
        disable fork;
    end

endmodule : tb_trecap_c0_active_tail

`default_nettype wire
