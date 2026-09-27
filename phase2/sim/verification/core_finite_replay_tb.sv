// SPDX-License-Identifier: MIT
// File class: [1] hand-written verification RTL.
// Layer: sim/verification/
// Purpose: V3 finite replay with exact independent-oracle comparison and completion ownership.

`timescale 1ns/1ps
`default_nettype none

module core_finite_replay_tb
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_artifact_expectations_pkg::*;
#(
    parameter string X_FILE = {"artifacts/test_vectors/", TEXP_VECTOR_NAME, "/x_in.memh"},
    parameter string Y_FILE = {"artifacts/reference_outputs/", TEXP_VECTOR_NAME, "/y_out.memh"},
    parameter string FRAME_FILE = {"artifacts/reference_outputs/", TEXP_VECTOR_NAME, "/frame_stats.csv"},
    parameter string BIN_FILE = {"artifacts/reference_outputs/", TEXP_VECTOR_NAME, "/bin_stats.csv"},
    parameter string IFFT_FILE = "",
    parameter int unsigned FINAL_STALL_CYCLES = 0,
    parameter bit STALL_PATTERN = 1'b0
) ();
    localparam longint unsigned ACTIVE_SAMPLES =
        longint'(TEXP_FRAMES) * longint'(T_HOP_H);
    localparam longint unsigned DRAIN_SAMPLES = T_DELAY_D;
    // Full-tail frame count follows the finite stream contract, including the
    // short-input boundary Ns=1 -> 2. It is not ceil(Ns/H).
    localparam longint unsigned CONTRACT_FRAMES =
        (longint'(TEXP_NS) + longint'(T_FFT_L) - 64'd2) / longint'(T_HOP_H);
    localparam longint unsigned CONTRACT_NY =
        CONTRACT_FRAMES * longint'(T_HOP_H) + longint'(T_DELAY_D);

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

    logic core_busy_o, top_busy_o, replay_done_o;
    logic source_sample_valid_o, source_sample_ready_o;
    logic signed [T_SAMPLE_W-1:0] source_sample_data_o;
    logic [63:0] source_sample_idx_o;
    logic [63:0] core_sample_count_o, core_frame_count_o;
    logic [63:0] replay_output_accept_count_o, wola_output_count_o;
    logic [63:0] top_output_accept_count_o, top_expected_output_count_o;
    logic tail_drain_accept_pulse_o, tail_drain_done_pulse_o;
    logic frame_boundary_pulse_o;
    integer source_count, active_count, drain_count, output_count, frame_boundary_count;
    integer drain_pulse_count, drain_done_count, cycle_count;
    integer source_fd, events_fd;
    string capture_dir;
    bit previous_source_stall;
    logic signed [T_SAMPLE_W-1:0] previous_source_data;
    logic [63:0] previous_source_idx;
    logic signed [T_SAMPLE_W-1:0] source_expected [0:TEXP_NS-1];
    logic signed [T_SAMPLE_W-1:0] expected_source_value;

    always #10ns clk = ~clk;

    // Optional ordinary stalls use a deterministic LFSR pattern. The directed
    // variant holds the final output for FINAL_STALL_CYCLES before acceptance.
    assign y_ready_i =
        (y_valid_o && (y_sample_idx_o == TEXP_NY - 1) &&
         (FINAL_STALL_CYCLES != 0) && !final_stall_complete_q) ?
        1'b0 : (!STALL_PATTERN || (ready_lfsr_q[2:0] != 3'b000));

    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ready_lfsr_q <= 16'h1ace;
            final_stall_started_q <= 1'b0;
            final_stall_complete_q <= (FINAL_STALL_CYCLES == 0);
            final_stall_remaining_q <= 0;
        end else begin
            ready_lfsr_q <=
                {ready_lfsr_q[14:0],
                 ready_lfsr_q[15] ^ ready_lfsr_q[13] ^
                 ready_lfsr_q[12] ^ ready_lfsr_q[10]};

            if ((FINAL_STALL_CYCLES != 0) && !final_stall_started_q && y_valid_o &&
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
        .X_MEMH_FILE( X_FILE ),
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
        .source_sample_valid_o( source_sample_valid_o ),
        .source_sample_ready_o( source_sample_ready_o ),
        .source_sample_data_o( source_sample_data_o ),
        .source_sample_idx_o( source_sample_idx_o ),
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
        .core_alive_o( ),
        .core_busy_o( core_busy_o ),
        .core_sample_count_o( core_sample_count_o ),
        .core_frame_count_o( core_frame_count_o ),
        .core_error_sample_count_o( core_error_sample_count_o ),
        .core_sum_abs_err_lo_o( core_sum_abs_err_lo_o ),
        .core_sum_sq_err_lo_o( core_sum_sq_err_lo_o ),
        .core_max_abs_err_o( core_max_abs_err_o ),
        .core_metric_overflow_sticky_o( core_metric_overflow_sticky_o ),
        .core_overflow_flags_o( core_overflow_flags_o ),
        .core_saturation_sticky_o( core_saturation_sticky_o ),
        .core_protocol_error_sticky_o( core_protocol_error_sticky_o ),
        .replay_active_o( ),
        .replay_done_o( replay_done_o ),
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
        .replay_output_accept_count_o( replay_output_accept_count_o ),
        .replay_configured_input_samples_o( ),
        .replay_configured_flush_samples_o( ),
        .tail_drain_active_o( ),
        .tail_drain_accept_pulse_o( tail_drain_accept_pulse_o ),
        .tail_drain_done_pulse_o( tail_drain_done_pulse_o ),
        .wola_output_count_o( wola_output_count_o ),
        .replay_config_error_sticky_o( ),
        .replay_mem_range_error_sticky_o( ),
        .replay_overrun_sticky_o( ),
        .source_discontinuity_pulse_o( ),
        .top_alive_o( ),
        .top_busy_o( top_busy_o ),
        .top_done_o( top_done_o ),
        .top_done_pulse_o( top_done_pulse_o ),
        .top_output_accept_count_o( top_output_accept_count_o ),
        .top_expected_output_count_o( top_expected_output_count_o ),
        .top_completion_error_sticky_o( top_completion_error_sticky_o ),
        .top_overflow_flags_o( top_overflow_flags_o ),
        .build_contract_error_o( build_contract_error_o )
    );

    core_exact_scoreboard #(
        .X_GOLDEN_FILE(X_FILE), .Y_GOLDEN_FILE(Y_FILE),
        .FRAME_GOLDEN_FILE(FRAME_FILE), .BIN_GOLDEN_FILE(BIN_FILE),
        .IFFT_GOLDEN_FILE(IFFT_FILE)
    ) scoreboard (
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
        // These hierarchical connections are passive probes: they never drive
        // a production signal and observe the same handshake consumed by WOLA.
        .ifft_valid_i(dut.u_core.ifft_valid_w),
        .ifft_ready_i(dut.u_core.ifft_ready_w),
        .ifft_frame_idx_i(dut.u_core.ifft_frame_idx_w),
        .ifft_sample_offset_i(dut.u_core.ifft_sample_offset_w),
        .ifft_re_i(dut.u_core.ifft_re_w),
        .ifft_im_i(dut.u_core.ifft_im_w),
        .ifft_last_i(dut.u_core.ifft_last_w),
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
        // WOLA scrub owns busy for D cycles after reset/clear. Admission waits
        // for the real structural condition, with an independent bounded guard.
        begin : await_initialization
            integer waited;
            waited = 0;
            @(negedge clk);
            while (top_busy_o !== 1'b0) begin
                @(negedge clk);
                waited = waited + 1;
                if (waited > T_DELAY_D + 32)
                    $fatal(1, "CORE_MISMATCH initialization did not quiesce");
            end
        end
        replay_start_i = 1'b1;
        @(negedge clk);
        replay_start_i = 1'b0;
    end

    initial begin : trace_setup
        if (!$value$plusargs("CORE_CAPTURE_DIR=%s", capture_dir) || capture_dir == "")
            $fatal(1, "CORE_MISMATCH required +CORE_CAPTURE_DIR=<existing-directory>");
        source_fd = $fopen({capture_dir, "/source_accepts.csv"}, "wb");
        events_fd = $fopen({capture_dir, "/lifecycle.csv"}, "wb");
        if (!source_fd || !events_fd) $fatal(1, "CORE_MISMATCH cannot open trace files");
        $fwrite(source_fd, "cycle,sample_idx,data,phase\n");
        $fwrite(events_fd, "cycle,event,source_count,output_count\n");
        $readmemh(X_FILE, source_expected);
        // Variable finite length is admitted within the fixed baseline numeric
        // profile. Expected artifact counts must agree before replay can start.
        if (T_SAMPLE_W != 12 || T_FFT_L != 256 || T_HOP_H != 128 || T_DELAY_D != 384 ||
            TEXP_NS == 0 || CONTRACT_FRAMES == 0 || TEXP_FRAMES != CONTRACT_FRAMES ||
            ACTIVE_SAMPLES < TEXP_NS || TEXP_NY != CONTRACT_NY ||
            TEXP_ERROR_SAMPLE_COUNT != TEXP_NY ||
            TEXP_UNIQUE_BINS != T_UNIQUE_BINS ||
            TEXP_BIN_ROWS != longint'(TEXP_FRAMES) * longint'(T_UNIQUE_BINS))
            $fatal(1, "CORE_MISMATCH inconsistent finite full-tail geometry Ns=%0d frames=%0d Ny=%0d",
                   TEXP_NS, TEXP_FRAMES, TEXP_NY);
    end

    always @(posedge clk) begin : p_test_contract
        // Ownership ledger: stream handshakes are sampled before NBA updates.
        if (!rst_n) begin
            source_count = 0; active_count = 0; drain_count = 0;
            output_count = 0; frame_boundary_count = 0;
            drain_pulse_count = 0; drain_done_count = 0; cycle_count = 0;
            previous_source_stall = 0;
        end else begin
            cycle_count = cycle_count + 1;
            if ($isunknown({source_sample_valid_o, source_sample_ready_o,
                            y_valid_o, y_ready_i}))
                $fatal(1, "CORE_MISMATCH unknown handshake control");
            if (previous_source_stall && (!source_sample_valid_o ||
                source_sample_data_o !== previous_source_data ||
                source_sample_idx_o !== previous_source_idx))
                $fatal(1, "CORE_MISMATCH replay beat changed while stalled");
            previous_source_stall = source_sample_valid_o && !source_sample_ready_o;
            previous_source_data = source_sample_data_o;
            previous_source_idx = source_sample_idx_o;
            if (source_sample_valid_o && source_sample_ready_o) begin
                if (source_count >= TEXP_NY)
                    $fatal(1, "CORE_MISMATCH extra source token");
                expected_source_value = (source_count < TEXP_NS) ? source_expected[source_count] : '0;
                if (source_sample_idx_o !== 64'(source_count) ||
                    source_sample_data_o !== expected_source_value)
                    $fatal(1, "CORE_MISMATCH source index/data row=%0d", source_count);
                if (source_count < ACTIVE_SAMPLES) active_count = active_count + 1;
                else drain_count = drain_count + 1;
                $fwrite(source_fd, "%0d,%0d,%0d,%s\n", cycle_count,
                        source_sample_idx_o, $signed(source_sample_data_o),
                        (source_count < TEXP_NS) ? string'("input") :
                        ((source_count < ACTIVE_SAMPLES) ? string'("analysis_flush") : string'("tail_drain")));
                source_count = source_count + 1;
            end
            if ((y_sample_o.valid !== y_valid_o) ||
                (y_valid_o && ((y_sample_o.data !== y_data_o) ||
                 (y_sample_o.sample_idx !== y_sample_idx_o))))
                $fatal(1, "CORE_MISMATCH y struct/breakout divergence");
            if (y_valid_o && y_ready_i) output_count = output_count + 1;
            if (y_valid_o && !y_ready_i && y_sample_idx_o == TEXP_NY - 1) begin
                final_stall_observed_q = final_stall_observed_q + 1;
                if (top_done_o || top_done_pulse_o)
                    $fatal(1, "CORE_MISMATCH done while final output is unaccepted");
            end
            // These are registered event pulses; consume their new values once.
            #1ps;
            if ($isunknown({build_contract_error_o, top_done_o, top_done_pulse_o,
                core_busy_o, top_busy_o, replay_done_o, replay_start_accept_pulse_o,
                replay_start_reject_pulse_o, frame_boundary_pulse_o,
                tail_drain_accept_pulse_o, tail_drain_done_pulse_o,
                top_completion_error_sticky_o, core_protocol_error_sticky_o,
                core_metric_overflow_sticky_o, core_saturation_sticky_o,
                top_overflow_flags_o, core_overflow_flags_o}))
                $fatal(1, "CORE_MISMATCH unknown lifecycle control");
            if (build_contract_error_o || replay_start_reject_pulse_o)
                $fatal(1, "CORE_MISMATCH invalid build or rejected replay start");
            if (top_completion_error_sticky_o || core_protocol_error_sticky_o ||
                core_metric_overflow_sticky_o || core_saturation_sticky_o ||
                top_overflow_flags_o != 0 || core_overflow_flags_o != 0)
                $fatal(1, "CORE_MISMATCH sticky error cycle=%0d top=%x core=%x protocol=%b",
                       cycle_count, top_overflow_flags_o, core_overflow_flags_o,
                       core_protocol_error_sticky_o);
            if (replay_start_accept_pulse_o) begin
                start_accept_count_q = start_accept_count_q + 1;
                if (start_accept_count_q != 1) $fatal(1, "CORE_MISMATCH duplicate replay start");
                $fwrite(events_fd, "%0d,start,%0d,%0d\n", cycle_count, source_count, output_count);
            end
            if (frame_boundary_pulse_o) frame_boundary_count = frame_boundary_count + 1;
            if (tail_drain_accept_pulse_o) drain_pulse_count = drain_pulse_count + 1;
            if (tail_drain_done_pulse_o) drain_done_count = drain_done_count + 1;
            if (top_done_o && output_count != TEXP_NY)
                $fatal(1, "CORE_MISMATCH premature done level");
            if (top_done_pulse_o) begin
                if (start_accept_count_q != 1 || source_count != TEXP_NY ||
                    active_count != ACTIVE_SAMPLES || drain_count != DRAIN_SAMPLES ||
                    output_count != TEXP_NY || frame_boundary_count != TEXP_FRAMES ||
                    drain_pulse_count != DRAIN_SAMPLES || drain_done_count != 1 ||
                    replay_output_accept_count_o !== 64'(TEXP_NY) ||
                    top_output_accept_count_o !== 64'(TEXP_NY) ||
                    top_expected_output_count_o !== 64'(TEXP_NY) ||
                    wola_output_count_o !== 64'(TEXP_NY) ||
                    core_sample_count_o !== 64'(ACTIVE_SAMPLES) ||
                    core_frame_count_o !== 64'(TEXP_FRAMES) ||
                    core_busy_o || top_busy_o || !replay_done_o ||
                    (FINAL_STALL_CYCLES != 0 && (!final_stall_started_q ||
                    !final_stall_complete_q || final_stall_observed_q < FINAL_STALL_CYCLES)))
                    $fatal(1, "CORE_MISMATCH completion ownership src=%0d active=%0d drain=%0d y=%0d frames=%0d drain_pulses=%0d drain_done=%0d stall=%0d",
                        source_count, active_count, drain_count, output_count,
                        frame_boundary_count, drain_pulse_count, drain_done_count,
                        final_stall_observed_q);
                $fwrite(events_fd, "%0d,done,%0d,%0d\n", cycle_count, source_count, output_count);
                $display("CORE_COMPLETION_COUNTS source=%0d active=%0d drain=%0d y=%0d frames=%0d bins=%0d final_stall=%0d",
                         source_count, active_count, drain_count, output_count,
                         frame_boundary_count, TEXP_BIN_ROWS, final_stall_observed_q);
                $fflush(source_fd); $fflush(events_fd);
            end
        end
    end
endmodule : core_finite_replay_tb
`default_nettype wire
